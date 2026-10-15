void (() => {
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
  const key = 'daily-kamitsubaki-collection-v1';
  let all;
  try {
    all = JSON.parse(localStorage.getItem(key) || '{}');
    if (!all || typeof all !== 'object' || Array.isArray(all)) throw Error('bad storage');
    const previous = all[mid]?.videos || [];
    const merged = new Map(previous.map(v => [v.bvid, v]));
    for (const [bv, video] of videos) merged.set(bv, video);
    all[mid] = { format: 'daily-kamitsubaki-browser-v1', mid,
      source: location.origin + location.pathname, exported_at: new Date().toISOString(),
      videos: [...merged.values()] };
    localStorage.setItem(key, JSON.stringify(all));
  } catch {
    alert('无法保存累积资料（存储被禁用、已满或数据异常），本次没有下载或清空资料。'); return;
  }
  document.getElementById('daily-kamitsubaki-panel')?.remove();
  const panel = document.createElement('div'); panel.id = 'daily-kamitsubaki-panel';
  panel.style.cssText = 'position:fixed;right:24px;top:100px;z-index:2147483647';
  const ui = panel.attachShadow({ mode: 'open' });
  const box = document.createElement('div');
  box.style.cssText = 'width:310px;padding:20px;border-radius:14px;background:#132b30;color:white;box-shadow:0 6px 30px #0008;font:15px/1.7 system-ui';
  const total = () => Object.values(all).reduce((n, p) => n + p.videos.length, 0);
  const message = document.createElement('p');
  message.textContent = `本页收集 ${videos.size} 条；当前歌手累计 ${all[mid].videos.length} 条；全部歌手 ${total()} 条。翻页后再点书签即可继续累积。`;
  box.appendChild(message);
  const button = (label, action) => {
    const b = document.createElement('button'); b.textContent = label;
    b.style.cssText = 'margin:4px;padding:8px;border:0;border-radius:6px;cursor:pointer';
    b.addEventListener('click', e => { e.stopPropagation(); action(); });
    box.appendChild(b);
  };
  button('下载总清单', () => {
    // 重新读取，避免另一标签刚收集的资料被遗漏。
    let batches;
    try { batches = Object.values(JSON.parse(localStorage.getItem(key) || '{}')); }
    catch { alert('累积数据异常，请保留现场。'); return; }
    if (!batches.length) { alert('暂无已收集资料。'); return; }
    const payload = { format: 'daily-kamitsubaki-bundle-v1', batches };
    const href = URL.createObjectURL(new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json;charset=utf-8' }));
    const a = document.createElement('a'); a.href = href;
    a.download = `kamitsubaki-all-${Date.now()}.json`;
    a.addEventListener('click', e => e.stopPropagation()); a.click();
    setTimeout(() => URL.revokeObjectURL(href), 30000);
  });
  button('清空累积（可恢复）', () => {
    try {
      localStorage.setItem(key + '-backup', localStorage.getItem(key) || '{}');
      localStorage.removeItem(key); all = {};
      message.textContent = '已清空累积资料；误操作可点“恢复上次清空”。下载过的JSON不受影响。';
    } catch { alert('清空失败，资料未确认清空。'); }
  });
  button('恢复上次清空', () => {
    try {
      all = JSON.parse(localStorage.getItem(key + '-backup') || '{}');
      localStorage.setItem(key, JSON.stringify(all));
      message.textContent = `已恢复，全部歌手累计 ${total()} 条。`;
    } catch { alert('恢复失败，请保留现场。'); }
  });
  button('收起', () => panel.remove());
  ui.appendChild(box); document.body.appendChild(panel);
})();
