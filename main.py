import asyncio
import weakref
import shutil
from pathlib import Path
from urllib.parse import urlparse

import aiohttp
from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Star, register
import astrbot.api.message_components as Comp

from .catalog import Catalog
from .cover_cache import prune_cache, save_cover, touch_cover
from .management import Management

DATA = Path('/AstrBot/data/plugin_data/astrbot_plugin_daily_kamitsubaki')
VIEW_URL = 'https://api.bilibili.com/x/web-interface/view'
HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36', 'Referer': 'https://www.bilibili.com/'}


@register('astrbot_plugin_daily_kamitsubaki', 'JXMc', '今日神椿：B站歌曲与封面推荐', '1.1.1')
class DailyKamitsubaki(Star):
    def __init__(self, context):
        super().__init__(context)
        DATA.mkdir(parents=True, exist_ok=True)
        prune_cache(DATA / 'covers')
        catalog_path = DATA / 'catalog.json'
        if not catalog_path.exists():
            shutil.copyfile(Path(__file__).with_name('catalog.json'), catalog_path)
        self.catalog = Catalog(catalog_path, DATA / 'history.db')
        self.management = Management(self, DATA)
        for route, handler, methods in (
            ('stats', self.management.stats, ['GET']),
            ('songs', self.management.songs, ['GET']),
            ('job/start', self.management.start, ['POST']),
            ('job/stop', self.management.stop, ['POST']),
            ('review', self.management.decide, ['POST']),
            ('songs/<song_id>/update', self.management.toggle, ['POST']),
        ):
            context.register_web_api('/astrbot_plugin_daily_kamitsubaki/' + route, handler, methods, '今日神椿曲库管理')
        self.locks = weakref.WeakValueDictionary()
        self.media_lock = asyncio.Lock()
        logger.info('独立今日神椿已加载：%s 首B站歌曲', len(self.catalog.songs))

    async def cover(self, bvid, cover_url=''):
        path = DATA / 'covers' / (bvid + '.jpg')
        if path.is_file():
            touch_cover(path)
            return path
        async with self.media_lock:
            if path.is_file():
                touch_cover(path)
                return path
            async with aiohttp.ClientSession(headers=HEADERS, timeout=aiohttp.ClientTimeout(total=12)) as session:
                parsed = urlparse(cover_url)
                if parsed.scheme == 'https' and (parsed.hostname or '').endswith('.hdslb.com') and not parsed.username and not parsed.password:
                    url = cover_url
                else:
                    async with session.get(VIEW_URL, params={'bvid': bvid}) as response:
                        response.raise_for_status()
                        payload = await response.json(content_type=None)
                    if payload.get('code') != 0:
                        raise ValueError(f"B站视频不可用：{payload.get('code')}")
                    url = payload['data']['pic']
                if url.startswith('//'):
                    url = 'https:' + url
                url = url.replace('http://', 'https://', 1)
                async with session.get(url) as response:
                    response.raise_for_status()
                    if not response.headers.get('Content-Type', '').startswith('image/'):
                        raise ValueError('B站封面不是图片')
                    content = await response.read()
                if len(content) < 1024:
                    raise ValueError('B站封面不完整')
                cached = save_cover(path, content)
                if cached is None:
                    raise ValueError('封面超过缓存大小限制或缓存已清理')
                return cached

    @filter.command('今日神椿')
    async def daily(self, event: AstrMessageEvent):
        session = str(event.unified_msg_origin)
        lock = self.locks.get(session)
        if lock is None:
            lock = asyncio.Lock()
            self.locks[session] = lock
        async with lock:
            song = self.catalog.recommend(session)
            if song is None:
                await event.send(event.plain_result('🎵 今日神椿暂无可推荐的歌曲，最近七天推送过的歌曲会暂时排除。'))
                return
            msg = (f"🎵 今日神椿\n\n《{song['title']}》\n歌手：{song['artist']}\n"
                   f"发行：{song['date'] or '未知'}\n\n▶ Bilibili：https://www.bilibili.com/video/{song['bvid']}\n"
                   f"资料来源：{song.get('source_name', '神椿观测站')}\n{song['source']}")
            try:
                image = None
                try:
                    path = await self.cover(song['bvid'], song.get('cover_url', ''))
                    image = Comp.Image.fromFileSystem(str(path))
                except Exception:
                    logger.exception('今日神椿B站封面获取失败')
                if image is not None:
                    try:
                        await asyncio.wait_for(event.send(event.chain_result([image, Comp.Plain(msg)])), timeout=15)
                    except Exception:
                        logger.exception('今日神椿图片发送失败，降级文字')
                        await asyncio.wait_for(event.send(event.plain_result(msg)), timeout=15)
                else:
                    await asyncio.wait_for(event.send(event.plain_result(msg)), timeout=15)
            except Exception:
                logger.exception('今日神椿发送失败，不记录冷却')
                return
            self.catalog.record(session, song)
            logger.info('今日神椿发送成功：%s / %s / %s', song['title'], song['artist'], song['bvid'])

    async def terminate(self):
        await self.management.terminate()
