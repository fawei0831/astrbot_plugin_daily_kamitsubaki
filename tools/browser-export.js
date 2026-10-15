(() => {
  'use strict';
  const mid = location.pathname.match(/^\/(\d+)(?:\/|$)/)?.[1];
  if (location.hostname !== 'space.bilibili.com' || !mid || !/\/upload(?:\/video)?\/?$/.test(location.pathname)) {
    alert('请先打开歌手的 B站空间 → 投稿 → 视频，再点击此书签。'); return;
  }
  const videos = new Map();
  for (const card of document.querySelectorAll('a.bili-cover-card')) {
    const url = new URL(card.href, location.href);
    if (url.hostname !== 'www.bilibili.com' && url.hostname !== 'bilibili.com') continue;
    const bvid = url.pathname.match(/^\/video\/(BV[0-9A-Za-z]{10})(?:\/|$)/)?.[1];
    const image = card.querySelector('img');
    const title = (image?.alt || '').trim();
    let cover = image?.getAttribute('src') || image?.getAttribute('data-src') || '';
    if (!bvid || !title || !cover) continue;
    try {
      const u = new URL(cover, location.href);
      if (u.protocol !== 'https:' || !u.hostname.endsWith('.hdslb.com')) continue;
      cover = u.origin + u.pathname.split('@')[0];
    } catch { continue; }
    videos.set(bvid, { bvid, title, mid, cover_url: cover });
  }
  if (!videos.size) { alert('没有读到带封面的视频。请等待投稿列表加载，向下滚动后再试。'); return; }
  const payload = { format: 'daily-kamitsubaki-browser-v1', mid,
    source: location.origin + location.pathname, exported_at: new Date().toISOString(),
    videos: [...videos.values()] };
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json;charset=utf-8' });
  const href = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = href; a.download = `kamitsubaki-${mid}-${Date.now()}.json`;
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(href), 30000);
  alert(`已导出当前页 ${videos.size} 条视频资料。\n这是视频数，不代表已经匹配的歌曲数。\n下一页需手动翻页，加载完成后再次点击书签。`);
})();
