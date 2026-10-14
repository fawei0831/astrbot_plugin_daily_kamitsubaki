import asyncio
import gzip
import json
import os
import sqlite3
import sys
import time
from contextlib import closing
from pathlib import Path

from astrbot.api.web import error_response, json_response, request
from .tools.build_catalog import BV, read, write


class Management:
    def __init__(self, plugin, data):
        self.plugin, self.data = plugin, Path(data)
        self.root = Path(__file__).parent
        self.work = self.data / 'catalog-work'
        self.work.mkdir(parents=True, exist_ok=True)
        with gzip.open(self.root / 'tools/song_index.json.gz', 'rt', encoding='utf-8') as f:
            self.index = {s['id']: s for s in json.load(f)}
        self.task = None
        self.process = None
        self.state_path = self.work / 'job.json'
        self.state = read(self.state_path) if self.state_path.exists() else {'phase': 'idle', 'logs': []}
        self.state['running'] = False
        if self.state.get('phase') in ('wiki', 'collect', 'match'):
            self.state['phase'] = 'interrupted'
        self.save_state()

    def save_state(self):
        self.state['updated_at'] = time.time()
        write(self.state_path, self.state)

    def paused_until(self):
        path = self.work / 'requests.sqlite'
        if not path.exists():
            return 0
        with closing(sqlite3.connect(path)) as conn:
            row = conn.execute("SELECT value FROM state WHERE key='paused_until'").fetchone()
            return row[0] if row else 0

    def reviews(self):
        path = self.work / 'review.json'
        return read(path) if path.exists() else []

    def persist_catalog(self, songs):
        write(self.data / 'catalog.json', songs)
        self.plugin.catalog.songs = songs

    async def stats(self):
        counts = {}
        for s in self.plugin.catalog.songs:
            counts[s['artist']] = counts.get(s['artist'], 0) + 1
        return json_response(dict(total=len(self.plugin.catalog.songs),
            enabled=sum(not s.get('disabled', False) for s in self.plugin.catalog.songs),
            index=len(self.index), pending=sum(not r.get('decision') for r in self.reviews()),
            artists=counts, paused_until=self.paused_until(), job=self.state))

    async def songs(self):
        q = str(request.query.get('q') or '').casefold()
        mode = request.query.get('mode') or 'catalog'
        if mode not in ('catalog', 'missing', 'review'):
            return error_response('未知列表类型', status_code=400)
        offset = max(0, request.query.get('offset', 0, type=int) or 0)
        formal = {s['id']: s for s in self.plugin.catalog.songs}
        if mode == 'review':
            items = self.reviews()
        elif mode == 'missing':
            items = [s for sid, s in self.index.items() if sid not in formal]
        else:
            items = list(formal.values())
        if q:
            items = [s for s in items if q in ' '.join(str(s.get(k, '')) for k in ('title', 'song', 'artist', 'bvid', 'video_title')).casefold()]
        return json_response(dict(items=items[offset:offset + 30], total=len(items), offset=offset))

    async def start(self):
        if self.task and not self.task.done():
            return error_response('补曲任务已经在运行', status_code=409)
        if self.paused_until() > time.time():
            return error_response('仍在B站访问限制暂停期，本次没有发起请求', status_code=429)
        self.state = dict(running=True, phase='starting', logs=[], started_at=time.time())
        self.save_state()
        self.task = asyncio.create_task(self.run())
        return json_response({'started': True})

    async def run(self):
        try:
            for phase, options in [('wiki', []), ('collect', ['--max-requests', '10']), ('match', [])]:
                self.state['phase'] = phase
                self.save_state()
                self.process = await asyncio.create_subprocess_exec(
                    sys.executable, '-u', str(self.root / 'tools/build_catalog.py'),
                    '--work', str(self.work), phase, *options,
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
                    env={**os.environ, 'PYTHONIOENCODING': 'utf-8'})
                async for line in self.process.stdout:
                    self.state['logs'] = (self.state['logs'] + [line.decode('utf-8', errors='replace').strip()])[-40:]
                    self.save_state()
                if await self.process.wait() != 0:
                    raise RuntimeError('补曲脚本异常退出，进度已保留')
            self.state['phase'] = 'paused' if self.paused_until() > time.time() else 'completed'
        except asyncio.CancelledError:
            self.state['phase'] = 'stopped'
            raise
        except Exception as exc:
            self.state.update(phase='failed', error=str(exc))
        finally:
            if self.process and self.process.returncode is None:
                self.process.terminate()
                await self.process.wait()
            self.process = None
            self.state['running'] = False
            self.save_state()

    async def stop(self):
        if self.task and not self.task.done():
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        return json_response({'stopped': True})

    async def decide(self):
        if self.state.get('running'):
            return error_response('请等待任务结束再审核', status_code=409)
        payload = await request.json(default={})
        if not isinstance(payload, dict):
            return error_response('无效请求', status_code=400)
        sid, bvid = payload.get('song_id'), payload.get('bvid')
        decision = payload.get('decision')
        reviews = self.reviews()
        row = next((r for r in reviews if r['song_id'] == sid and r['bvid'] == bvid), None)
        if row is None or sid not in self.index or decision not in ('approve', 'reject'):
            return error_response('候选条目或审核操作无效', status_code=400)
        if decision == 'approve':
            if not BV.fullmatch(bvid):
                return error_response('无效BV号', status_code=400)
            # 审核确认后沿用已核对的百科歌曲资料，历史数据库保持原样。
            formal = {s['id']: s for s in self.plugin.catalog.songs}
            formal[sid] = dict(self.index[sid], bvid=bvid)
            self.persist_catalog(list(formal.values()))
        row['decision'] = decision
        row['approved'] = decision == 'approve'
        write(self.work / 'review.json', reviews)
        return json_response({'saved': True})

    async def toggle(self, song_id):
        payload = await request.json(default={})
        if not isinstance(payload, dict):
            return error_response('无效请求', status_code=400)
        if not isinstance(payload.get('enabled'), bool):
            return error_response('enabled必须是布尔值', status_code=400)
        songs = [dict(s) for s in self.plugin.catalog.songs]
        row = next((s for s in songs if s['id'] == song_id), None)
        if row is None:
            return error_response('歌曲不存在', status_code=404)
        row['disabled'] = not payload['enabled']
        self.persist_catalog(songs)
        return json_response({'saved': True})

    async def terminate(self):
        await self.stop()
