"""离线解析资料库，低频收集公开投稿，人工确认后导出插件曲库。"""
import argparse
import html
import gzip
import hashlib
import json
import re
import sqlite3
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BV = re.compile(r"BV[0-9A-Za-z]{10}\Z")
WBI_ORDER = (46,47,18,2,53,8,23,32,15,50,10,31,58,3,45,35,27,43,5,49,33,9,42,19,29,28,14,39,12,38,41,13,37,48,7,16,24,55,40,61,26,17,0,1,60,51,30,4,22,25,54,21,56,59,6,63,57,62,11,36,20,34,44,52)


def wbi_params(params, img_key, sub_key, timestamp):
    """公开 WBI 参数签名；不注入账号凭据或设备指纹。"""
    raw = img_key + sub_key
    if len(raw) != 64 or not re.fullmatch('[0-9a-fA-F]{64}', raw):
        raise StopCollection('WBI公钥格式变化，停止本轮。')
    mixin = ''.join(raw[i] for i in WBI_ORDER)[:32]
    clean = {k: ''.join(c for c in str(v) if c not in "!'()*")
             for k, v in params.items() if k not in ('w_rid', 'wts')}
    clean['wts'] = str(int(timestamp))
    query = urllib.parse.urlencode(sorted(clean.items()))
    clean['w_rid'] = hashlib.md5((query + mixin).encode()).hexdigest()
    return clean
ARTISTS = {
    'kaf': '花譜', 'rim': '理芽', 'harusaruhi': '春猿火',
    'isekaijoucho': 'ヰ世界情緒', 'koko': '幸祜', 'asu': '明透',
    'ciel': 'CIEL', 'vwp': 'V.W.P', 'kaika': '廻花', 'valis': 'VALIS',
    'albemuth': 'Albemuth', 'aru': '存流', 'dustcell': 'DUSTCELL',
    'empty-old-city': 'Empty old City', 'awairo': 'Awairo', 'loluet': 'LOLUET',
    'orihime': '御莉姫', 'kakyoin': '佳鏡院',
}


def video_artists(title, defaults=()):
    # 翻唱者在 covered by 后；原唱名不能当作本次演唱者。
    covered = re.search(r'cover(?:ed)?\s+by\s*(.*)', title, re.I)
    text = covered.group(1) if covered else title
    aliases = {a: [name] for a, name in ARTISTS.items()}
    for a, names in {'kaf':['花谱'], 'isekaijoucho':['异世界情绪','異世界情緒','ヰ世界情绪'],
                     'valis':['瓦利斯'], 'orihime':['御莉姬'], 'kakyoin':['佳镜院','佳境院'],
                     'vwp':['VWP'], 'asu':['ASU'], 'rim':['RIM'], 'koko':['KOKO']}.items():
        aliases[a].extend(names)
    found = []
    for artist, names in aliases.items():
        if any(re.search((r'(?<![A-Za-z])' + re.escape(n) + r'(?![A-Za-z])') if n.isascii()
                         else re.escape(n), text, re.I) for n in names):
            found.append(artist)
    return found if covered or found else list(defaults)


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(path)


def title_key(value):
    value = unicodedata.normalize('NFKC', html.unescape(value)).casefold()
    value = re.sub(r'\s*\(feat\..*?\)', '', value)
    value = re.sub(r'\([^()]*(?:live|remix|ver\.|version)[^()]*\)', '', value)
    return ''.join(c for c in value if c.isalnum())


class StopCollection(RuntimeError):
    pass


class Client:
    """单进程串行网络访问；缓存、请求时间及风控暂停均跨运行保存。"""
    def __init__(self, state, budget=10, interval=8, opener=None, clock=time.time, sleep=time.sleep):
        self.db = sqlite3.connect(state)
        self.db.execute('CREATE TABLE IF NOT EXISTS cache(url TEXT PRIMARY KEY,body TEXT,at REAL)')
        self.db.execute('CREATE TABLE IF NOT EXISTS state(key TEXT PRIMARY KEY,value REAL)')
        self.clock, self.sleep = clock, sleep
        self.budget, self.count, self.interval = min(budget, 50), 0, max(interval, 8)
        self.opener = opener or urllib.request.build_opener()

    def state(self, key):
        row = self.db.execute('SELECT value FROM state WHERE key=?', (key,)).fetchone()
        return row[0] if row else 0

    def put_state(self, key, value):
        self.db.execute('INSERT OR REPLACE INTO state VALUES (?,?)', (key, value))
        self.db.commit()

    def pause(self, reason, seconds=86400):
        self.put_state('paused_until', self.clock() + max(86400, seconds))
        raise StopCollection(reason + '；已暂停至少24小时，不自动重试。')

    def get(self, endpoint, params, *, nav=False):
        url = 'https://api.bilibili.com' + endpoint + '?' + urllib.parse.urlencode(params)
        cache_url = 'https://api.bilibili.com' + endpoint + '?' + urllib.parse.urlencode(
            sorted((k, v) for k, v in params.items() if k not in ('wts', 'w_rid')))
        row = self.db.execute('SELECT body,at FROM cache WHERE url=?', (cache_url,)).fetchone()
        if row and self.clock() - row[1] < (3600 if nav else 7 * 86400):
            return json.loads(row[0])
        if self.state('paused_until') > self.clock():
            raise StopCollection('上次触发风控，仍在暂停期；本次未发送网络请求。')
        if self.count >= self.budget:
            raise StopCollection('已达到本次请求上限，进度已保留。')
        self.sleep(max(0, self.state('next_request') - self.clock()))
        self.put_state('next_request', self.clock() + self.interval)
        self.count += 1
        request = urllib.request.Request(url, headers={
            'User-Agent': 'DailyKamitsubakiCatalog/1.0 (public metadata; low frequency)',
            'Accept': 'application/json', 'Referer': 'https://www.bilibili.com/',
        })
        try:
            with self.opener.open(request, timeout=20) as response:
                body = response.read().decode('utf-8')
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403, 412, 429):
                retry = exc.headers.get('Retry-After', '0')
                self.pause('HTTP访问限制 ' + str(exc.code), int(retry) if retry.isdigit() else 86400)
            raise StopCollection('HTTP错误，停止本轮：' + str(exc.code)) from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise StopCollection('网络异常，停止本轮；不连续重试。') from exc
        try:
            payload = json.loads(body)
        except ValueError:
            self.pause('返回非JSON页面，可能需要验证')
        if not isinstance(payload, dict):
            self.pause('接口返回格式异常')
        code = payload.get('code')
        # nav 未登录时 code=-101，但仍可能提供公开 wbi_img。
        if nav and code in (0, -101) and isinstance(payload.get('data'), dict):
            if isinstance(payload['data'].get('wbi_img'), dict):
                self.db.execute('INSERT OR REPLACE INTO cache VALUES (?,?,?)', (cache_url, body, self.clock()))
                self.db.commit()
                return payload
        if code in (-352, -412, -429, -403, -101, -401):
            self.pause('B站访问限制 ' + str(code))
        if code != 0 or not isinstance(payload.get('data'), dict):
            self.pause('接口返回异常 ' + str(code))
        self.db.execute('INSERT OR REPLACE INTO cache VALUES (?,?,?)', (cache_url, body, self.clock()))
        self.db.commit()
        return payload

    def space_page(self, mid, page):
        # 暂停检查先于 nav，避免为取签名公钥而绕过已有暂停。
        if self.state('paused_until') > self.clock():
            raise StopCollection('上次触发风控，仍在暂停期；本次未发送网络请求。')
        if not hasattr(self, '_wbi_keys'):
            images = self.get('/x/web-interface/nav', {}, nav=True)['data']['wbi_img']
            try:
                self._wbi_keys = tuple(Path(urllib.parse.urlparse(images[k]).path).stem
                                       for k in ('img_url', 'sub_url'))
            except (KeyError, TypeError) as exc:
                raise StopCollection('WBI公钥结构变化，停止本轮。') from exc
        params = wbi_params({'mid': mid, 'pn': page, 'ps': 30}, *self._wbi_keys, self.clock())
        return self.get('/x/space/wbi/arc/search', params)


def wiki(args):
    if not args.source_dir:
        with gzip.open(ROOT / 'tools/song_index.json.gz', 'rt', encoding='utf-8') as f:
            songs = json.load(f)
        write(args.work / 'songs.json', songs)
        print(json.dumps({'songs': len(songs), 'source': 'bundled-offline-snapshot'}))
        return
    import yaml
    source = Path(args.source_dir) / 'src/content/songs'
    if not source.is_dir():
        raise ValueError('请提供神椿观测站本地仓库根目录，不是网址。')
    songs = []
    for f in sorted(source.rglob('zh.md')):
        text = f.read_text(encoding='utf-8-sig')
        if not text.startswith('---'):
            continue
        meta = yaml.safe_load(text.split('---', 2)[1]) or {}
        artists = [x['entity'] for x in meta.get('performers', []) if x.get('entity')]
        if 'vwp' in artists:
            artists = ['vwp']
        if not artists or any(a not in ARTISTS for a in artists):
            continue
        bvids = re.findall(r'@\[bilibili\]\([^\n]*?(BV[0-9A-Za-z]{10})', text)
        songs.append(dict(id=meta['id'], title=meta['title'], artists=artists,
                          artist=' / '.join(ARTISTS[a] for a in artists),
                          date=str(meta.get('releaseDate') or ''),
                          source='https://kamitsubaki.wiki/zh/database/music/songs/' + meta['id'] + '/',
                          bvid=bvids[0] if bvids else ''))
    write(args.work / 'songs.json', songs)
    print(json.dumps({'songs': len(songs), 'with_bvid': sum(bool(s['bvid']) for s in songs)}))


def collect(args):
    channels = read(args.channels)
    videos_path = args.work / 'videos.json'
    videos = {v['bvid']: v for v in read(videos_path)} if videos_path.exists() else {}
    client = Client(args.work / 'requests.sqlite', args.max_requests, args.interval)
    try:
        for channel in channels:
            if channel.get('source_type') == 'fan':
                continue
            if channel['artist'] not in ARTISTS or not str(channel['mid']).isdigit():
                raise ValueError('无效的歌手或账号ID')
            key = 'page:' + str(channel['mid'])
            # 已完成的账号一周后才重新扫描；中断的账号从下一页继续。
            if client.state('done:' + str(channel['mid'])) > time.time() - 7 * 86400:
                continue
            page = int(client.state(key)) or 1
            while True:
                payload = client.space_page(channel['mid'], page)
                data = payload['data']
                items = data.get('list', {}).get('vlist')
                if not isinstance(items, list) or not isinstance(data.get('page', {}).get('count'), int):
                    raise StopCollection('投稿接口结构变化，停止本轮，不标记扫描完成。')
                for v in items:
                    if not BV.fullmatch(str(v.get('bvid', ''))):
                        continue
                    if str(v.get('mid')) != str(channel['mid']):
                        continue
                    pic = str(v.get('pic') or '')
                    if pic.startswith('//'):
                        pic = 'https:' + pic
                    videos[v['bvid']] = dict(bvid=v['bvid'], title=html.unescape(v['title']),
                        mid=str(channel['mid']), artist=channel['artist'], artists=channel.get('artists', [channel['artist']]), cover_url=pic,
                        source='https://space.bilibili.com/' + str(channel['mid']))
                write(videos_path, list(videos.values()))
                if page * 30 >= data['page']['count']:
                    client.put_state('done:' + str(channel['mid']), time.time())
                    client.put_state(key, 1)
                    break
                page += 1
                client.put_state(key, page)
    except StopCollection as exc:
        print(str(exc))
    finally:
        write(videos_path, list(videos.values()))
        client.db.close()
    print(json.dumps({'videos': len(videos), 'network_requests': client.count}))


def match(args):
    songs, videos = read(args.work / 'songs.json'), read(args.work / 'videos.json')
    review_path = args.work / 'review.json'
    previous = {(r['song_id'], r['bvid']): r for r in read(review_path)} if review_path.exists() else {}
    candidates = []
    for song in songs:
        if song['bvid']:
            continue
        key = title_key(song['title'])
        if len(key) < 2:
            continue
        for v in videos:
            if not set(v.get('artists', [v.get('artist')])).intersection(song['artists']) or not BV.fullmatch(v['bvid']):
                continue
            if re.search(r'切片|合集|杂谈|reaction|歌回|即将|还有\d+天|公開決定|公开決定|预告|告知|teaser|trailer', v['title'], re.I):
                continue
            # 冷却可合并版本，但匹配不能把现场版当作某位制作人的Remix。
            remix = re.search(r'[（(]([^()（）]*remix)[）)]', song['title'], re.I)
            if remix and title_key(remix.group(1)) not in title_key(v['title']):
                continue
            if not remix and re.search(r'\bremix\b', v['title'], re.I):
                continue
            quoted = re.findall(r'[「《『](.*?)[」》』]', v['title'])
            exact = any(title_key(t) == key for t in quoted) or title_key(v['title']) == key
            if exact or key in title_key(v['title']):
                candidates.append(dict(song_id=song['id'], song=song['title'], artist=song['artist'],
                    bvid=v['bvid'], video_title=v['title'], cover_url=v.get('cover_url', ''),
                    mid=v.get('mid', ''), source_type=v.get('source_type', 'official'),
                    match='exact-title' if exact else 'needs-review', approved=False))
    # 同一首歌只保留最优来源层级，官号存在时不输出搬运站候选。
    official = {r['song_id'] for r in candidates if r['source_type'] == 'official'}
    candidates = [r for r in candidates if r['source_type'] == 'official' or r['song_id'] not in official]
    for item in candidates:
        old = previous.get((item['song_id'], item['bvid']), {})
        if old.get('decision') in ('approve', 'reject'):
            item.update(decision=old['decision'], approved=old.get('approved', False))
    write(review_path, candidates)
    preferred = {}
    for item in sorted(candidates, key=lambda r: (
            bool(re.search(r'live|现场|現場', r['video_title'], re.I)),
            r['match'] != 'exact-title', r['bvid'])):
        preferred.setdefault(item['song_id'], item)
    write(args.work / 'preferred.json', list(preferred.values()))
    print(json.dumps({'candidates': len(candidates), 'auto_approved': 0}))


def export(args):
    songs = {s['id']: s for s in read(args.work / 'songs.json')}
    catalog = {s['id']: s for s in read(args.base)}
    seen = set()
    for item in read(args.review):
        if item.get('approved') is not True:
            continue
        sid, bvid = item['song_id'], item['bvid']
        if sid not in songs or not BV.fullmatch(bvid) or sid in seen:
            raise ValueError('确认清单有无效或重复条目，未写入输出。')
        seen.add(sid)
        catalog[sid] = dict(songs[sid], bvid=bvid)
    if Path(args.output).resolve() == Path(args.base).resolve():
        raise ValueError('请先输出到新文件，检查后再替换正式曲库。')
    write(args.output, list(catalog.values()))
    print(json.dumps({'catalog': len(catalog), 'approved': len(seen)}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work', type=Path, default=ROOT / '.catalog-work')
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('wiki'); p.add_argument('--source-dir'); p.set_defaults(run=wiki)
    p = sub.add_parser('collect'); p.add_argument('--channels', default=ROOT / 'tools/channels.json')
    p.add_argument('--max-requests', type=int, default=10, choices=range(1, 51))
    p.add_argument('--interval', type=float, default=8); p.set_defaults(run=collect)
    p = sub.add_parser('match'); p.set_defaults(run=match)
    p = sub.add_parser('export'); p.add_argument('--review', required=True)
    p.add_argument('--base', default=ROOT / 'catalog.json'); p.add_argument('--output', required=True); p.set_defaults(run=export)
    args = parser.parse_args(); args.work.mkdir(parents=True, exist_ok=True)
    args.run(args)


if __name__ == '__main__':
    main()
