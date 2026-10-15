"""离线导入浏览器导出的公开投稿清单，生成候选；不访问网络或修改正式曲库。"""
import argparse
import gzip
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlparse

from build_catalog import ROOT, BV, read, write, match, video_artists


def import_files(paths, work, channels=None):
    channels = read(channels or ROOT / 'tools/channels.json')
    artists = {str(c['mid']): c['artist'] for c in channels}
    groups = {str(c['mid']): c.get('artists', [c['artist']]) for c in channels}
    kinds = {str(c['mid']): c.get('source_type', 'official') for c in channels}
    incoming = {}
    # 全部文件验证成功才写入，不让坏文件造成半次导入。
    batches = []
    for path in paths:
        if Path(path).stat().st_size > 5 * 1024 * 1024:
            raise ValueError('清单超过5MB，请选择工具导出的单页JSON。')
        data = read(path)
        if isinstance(data, dict) and data.get('format') == 'daily-kamitsubaki-bundle-v1':
            parts = data.get('batches')
            if not isinstance(parts, list) or not 0 < len(parts) <= 100:
                raise ValueError('总清单歌手分组无效。')
            batches.extend(parts)
        else:
            batches.append(data)
    for data in batches:
        if not isinstance(data, dict) or data.get('format') != 'daily-kamitsubaki-browser-v1':
            raise ValueError('这不是今日神椿浏览器导出的清单。')
        mid = str(data.get('mid', ''))
        if mid not in artists:
            raise ValueError('此账号尚未核对歌手归属：' + mid + '；请先核对后加入channels.json。')
        source = urlparse(str(data.get('source', '')))
        if source.scheme != 'https' or source.netloc != 'space.bilibili.com' or source.path.rstrip('/') not in (f'/{mid}/upload', f'/{mid}/upload/video'):
            raise ValueError('清单来源与歌手账号不一致。')
        videos = data.get('videos')
        if not isinstance(videos, list) or not 0 < len(videos) <= 10000:
            raise ValueError('清单视频数量不正确。')
        for v in videos:
            if not isinstance(v, dict):
                raise ValueError('视频资料格式错误。')
            bvid, title = str(v.get('bvid', '')), str(v.get('title', '')).strip()
            cover = urlparse(str(v.get('cover_url', '')))
            if (not BV.fullmatch(bvid) or not title or len(title) > 1000
                    or str(v.get('mid', '')) != mid or cover.scheme != 'https'
                    or not (cover.hostname or '').endswith('.hdslb.com') or cover.username or cover.password):
                raise ValueError('视频号、标题、账号或封面地址无效；未导入。')
            incoming[bvid] = dict(bvid=bvid, title=title, mid=mid, artist=artists[mid],
                artists=video_artists(title, () if kinds[mid] == 'fan' or len(groups[mid]) > 1 else groups[mid]),
                source_type=kinds[mid], cover_url=cover.geturl(), source=data['source'])
    work = Path(work); work.mkdir(parents=True, exist_ok=True)
    vp = work / 'videos.json'
    existing = {v['bvid']: v for v in read(vp)} if vp.exists() else {}
    added = len(incoming.keys() - existing.keys())
    existing.update(incoming)
    if not (work / 'songs.json').exists():
        with gzip.open(ROOT / 'tools/song_index.json.gz', 'rt', encoding='utf-8') as f:
            import json
            write(work / 'songs.json', json.load(f))
    write(vp, list(existing.values()))
    match(SimpleNamespace(work=work))
    print(f'导入完成：本次资料 {len(incoming)} 条，新视频 {added} 条，总视频 {len(existing)} 条。')
    print('候选已保存到：' + str(work / 'review.json'))
    print('正式曲库未修改；候选可能包含现场版、预告或同名歌曲，需核对。')
    return added


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('files', nargs='*', type=Path)
    p.add_argument('--work', type=Path, default=ROOT / '.catalog-work')
    args = p.parse_args()
    if not args.files:
        from tkinter import Tk, filedialog
        root = Tk(); root.withdraw()
        args.files = [Path(x) for x in filedialog.askopenfilenames(title='选择下载的神椿投稿清单（可多选）', filetypes=[('JSON清单', '*.json')])]
        root.destroy()
    if not args.files:
        print('未选择文件，没有修改资料。'); return
    try:
        import_files(args.files, args.work)
    except (ValueError, OSError, KeyError) as exc:
        p.exit(1, '导入失败：' + str(exc) + '\n')


if __name__ == '__main__':
    main()
