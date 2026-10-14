const bridge = window.AstrBotPluginPage;
const $ = id => document.getElementById(id);
let offset = 0, total = 0, busy = false, polling = false;
const phaseNames = {idle:'尚未运行',starting:'正在启动',wiki:'正在读取离线歌曲资料',collect:'正在低频收集B站投稿',match:'正在匹配歌曲',completed:'本轮任务完成',paused:'遇到B站访问限制，已暂停',stopped:'任务已停止',interrupted:'上次任务中断，可从进度继续',failed:'任务失败'};
function notice(message) { $('notice').textContent=message; $('notice').hidden=!message; }
async function api(path, body, params={}) {
  if (!bridge) throw new Error('请从 AstrBot 插件页面打开此管理页。');
  const result = body === undefined ? await bridge.apiGet(path,params) : await bridge.apiPost(path,body);
  if (result?.status === 'error' || result?.error) throw new Error(result.message || result.error);
  return result;
}
function text(tag, content) { const e=document.createElement(tag); e.textContent=content; return e; }
async function action(button, fn) { button.disabled=true; try { notice(''); await fn(); await refresh(); } catch(e) { notice(e.message || String(e)); } finally { if(!['start','stop'].includes(button.id))button.disabled=false; } }
async function stats() {
  const s=await api('stats');
  for (const key of ['total','enabled','index','pending']) $(key).textContent=s[key];
  const job=s.job || {}, paused=s.paused_until>Date.now()/1000;
  $('start').disabled=!!job.running || paused;
  $('stop').disabled=!job.running;
  $('job-status').textContent=(phaseNames[job.phase] || job.phase || '尚未运行') + (paused ? '；可再次运行时间：'+new Date(s.paused_until*1000).toLocaleString() : '') + (job.error ? '；'+job.error : '');
  $('logs').textContent=(job.logs || []).join('\n') || '暂无任务记录';
}
async function list() {
  const mode=$('mode').value;
  const data=await api('songs',undefined,{mode,q:$('search').value,offset});
  total=data.total;
  const body=$('rows'); body.replaceChildren();
  for (const s of data.items) {
    const tr=document.createElement('tr'), title=text('td',s.title || s.song);
    if(s.video_title) title.append(text('small',s.video_title));
    tr.append(title,text('td',s.artist));
    const link=document.createElement('td');
    if(/^BV[0-9A-Za-z]{10}$/.test(s.bvid || '')) {const a=text('a',s.bvid);a.href='https://www.bilibili.com/video/'+s.bvid;a.target='_blank';a.rel='noopener noreferrer';link.append(a);} else link.textContent='待补充';
    tr.append(link,text('td',mode==='review' ? ({approve:'已收录',reject:'已跳过'}[s.decision] || '待审核') : mode==='missing' ? '尚未入库' : s.disabled ? '已停用' : '已启用'));
    const controls=document.createElement('td');
    if(mode==='catalog') {
      const b=text('button',s.disabled?'启用':'停用'); b.onclick=()=>action(b,()=>api('songs/'+encodeURIComponent(s.id)+'/update',{enabled:!!s.disabled}));controls.append(b);
    } else if(mode==='review' && !s.decision) {
      for (const [decision,label] of [['approve','确认收录'],['reject','跳过']]) {const b=text('button',label);b.onclick=()=>action(b,()=>api('review',{song_id:s.song_id,bvid:s.bvid,decision}));controls.append(b);}
    } else if(mode==='missing') controls.textContent='运行补曲后匹配';
    tr.append(controls);body.append(tr);
  }
  if(!data.items.length) {const row=document.createElement('tr'),cell=text('td',mode==='review'?'暂无候选；请查看补曲任务进度或暂停原因。':'暂无符合条件的歌曲。');cell.colSpan=5;cell.className='empty';row.append(cell);body.append(row);}
  $('count').textContent=total ? `${offset+1}–${Math.min(offset+30,total)} / 共 ${total} 条` : '共 0 条';
  $('prev').disabled=offset===0;$('next').disabled=offset+30>=total;
}
async function refresh() { if(busy)return;busy=true;try{await stats();await list();}finally{busy=false;} }
$('refresh').onclick=()=>refresh().catch(e=>notice(e.message));
$('start').onclick=()=>action($('start'),()=>api('job/start',{}));
$('stop').onclick=()=>action($('stop'),()=>api('job/stop',{}));
$('mode').onchange=()=>{offset=0;list().catch(e=>notice(e.message));};
let debounce;$('search').oninput=()=>{clearTimeout(debounce);debounce=setTimeout(()=>{offset=0;list().catch(e=>notice(e.message));},300);};
$('prev').onclick=()=>{offset=Math.max(0,offset-30);list().catch(e=>notice(e.message));};
$('next').onclick=()=>{offset+=30;list().catch(e=>notice(e.message));};
refresh().catch(e=>notice(e.message));
setInterval(async()=>{if(document.hidden || polling || busy)return;polling=true;try{await stats();}catch(e){notice(e.message);}finally{polling=false;}},5000);
