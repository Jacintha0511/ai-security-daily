/* Public strings use textContent. Reading choices stay in this browser. */
(() => {
'use strict';
const $=id=>document.getElementById(id),R=Reading;
let storage;try{storage=localStorage;}catch{storage=null;}
const saved=R.createStore(storage);
const state={manifest:null,library:{items:[],editions:{},themes:[]},indexFailed:false,report:null,latestReport:null,view:'daily',selectedDate:null,kind:'all',query:'',theme:'all',days:'all',guide:'all',status:'all',loadId:0};
const titles={daily:'今日研究精选',library:'研究资料库',later:'稍后读',explore:'探索更多 AI 安全方向',archive:'历史研究日报',weekly:'每周动态回顾'};
const beijing=d=>new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(d);
const today=()=>beijing(new Date());
const time=v=>v&&!Number.isNaN(Date.parse(v))?new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}).format(new Date(v)):'未知';
function el(tag,cls,text){const n=document.createElement(tag);if(cls)n.className=cls;if(text!==undefined)n.textContent=String(text);return n;}
function link(text,url,cls){const a=el('a',cls,text);try{const u=new URL(url,location.href);if(!['https:','http:'].includes(u.protocol))throw Error();a.href=u.href;a.target='_blank';a.rel='noopener noreferrer';}catch{}return a;}
function empty(n,text){n.append(el('div','empty-state',text));}
async function json(path){const r=await fetch(new URL(path,document.baseURI),{cache:'no-store'});if(!r.ok)throw Error('HTTP '+r.status);return r.json();}
function decorate(item){const known=state.library.items.find(r=>R.key(r)===R.key(item));return {...known,...item,analysis:known?.analysis||null,themes:known?.themes||[],record_key:R.key(item)};}
function stateURL(){const u=new URL(location.href);u.search='';u.searchParams.set('view',state.view);if(state.selectedDate&&['archive','weekly'].includes(state.view))u.searchParams.set('date',state.selectedDate);for(const [p,k]of [['q','query'],['kind','kind'],['theme','theme'],['days','days'],['guide','guide'],['status','status']])if(state[k]&&state[k]!=='all')u.searchParams.set(p,state[k]);return u;}
function backURL(){const u=stateURL();return u.pathname+u.search;}
function guideLink(item){const a=item.analysis,button=el('a','analysis-link',a?'查看导读':'导读准备中');button.href='analysis.html?id='+encodeURIComponent(item.id)+(a?'&v='+encodeURIComponent(a.fingerprint):'')+'&back='+encodeURIComponent(backURL());return button;}
function storageNote(){const n=$('storage-note');n.hidden=saved.persistent;n.textContent='当前浏览器不允许持久保存，阅读状态只在本页临时保留，刷新后可能丢失。';}
function actions(item){const box=el('div','read-actions');for(const [value,label]of [['later','稍后读'],['read','已读'],['ignored','不感兴趣']]){const b=el('button',saved.get(item)===value?'selected':'',label);b.setAttribute('aria-pressed',String(saved.get(item)===value));b.addEventListener('click',()=>{saved.set(item,saved.get(item)===value?'unread':value);storageNote();render();});box.append(b);}return box;}
function card(item,index){
 const a=item.analysis,note=a?.recommendation||{},isPaper=item.kind==='paper';
 const c=el('article',isPaper?'paper-card'+(state.view==='daily'&&index===0?' lead':''):item.kind==='repo'?'repo-row':'news-row');
 const meta=el('div','item-meta');meta.append(el('span','source-label',item.source),el('span','',isPaper?(item.version||'版本待核'):item.kind==='repo'?(item.project_role||'工程项目'):''),el('span','priority-label',a?'有导读 · 核查范围可见':'公开元信息 · 待全文评读'));
 if(state.view==='daily'&&isPaper)meta.append(el('span','priority-label',index===0?'本期重点':'备选'));
 c.append(meta);
 const h=el('h3');h.append(link(note.headline||item.title,item.url));c.append(h);
 if(note.headline)c.append(el('p','original-title',item.title));
 c.append(el('p','summary',a?.overview||item.summary||'暂无公开摘要。'));
 if(a){const points=el('div','decision-points');for(const [label,text]of [['值得读：',note.why_read||a.verdict],['先看：',note.read_next||'先读概览，再看方法和关键结果。'],['本版变化：',note.update_summary]])if(text){const p=el('p');p.append(el('strong','',label),el('span','',text));points.append(p);}c.append(points);}
 if(item.kind==='repo')c.append(el('span','stars',new Intl.NumberFormat('zh-CN').format(item.stars||0)+' star · 星数仅为快照'));
 const bottom=el('div','item-bottom');bottom.append(guideLink(item),link('原文／仓库',item.url,'read-link'),el('span','item-date','发表 '+(item.published_at||'未知').slice(0,10)+' · 更新 '+(item.updated_at||item.published_at||'未知').slice(0,10)));c.append(bottom,actions(item));
 const versions=state.library.items.filter(r=>r.id===item.id&&R.key(r)!==R.key(item)&&r.analysis);
 if(versions.length){const d=el('details','version-links');d.append(el('summary','','其他已收录版本'));for(const r of versions){const b=guideLink(r);b.textContent=r.version||r.analysis.version.slice(0,8);d.append(b);}c.append(d);}
 if(state.view==='archive'||state.view==='weekly'){const d=el('details','evidence-detail');d.append(el('summary','','当期推荐依据'),el('p','',item.reason||'当期主题规则预筛'),el('p','',item.selection_basis||'历史内容保留原记录。'));c.append(d);}
 return c;
}
function baseItems(){
 if(['archive','weekly'].includes(state.view))return Object.values(state.report?.items||{}).flat().map(decorate);
 if(state.view==='daily')return R.home(state.library,today()).items.filter(r=>!['read','ignored'].includes(saved.get(r)));
 if(state.view==='later')return state.library.items.filter(r=>saved.get(r)==='later');
 const all=R.latest(state.library.items).sort((a,b)=>Number(b.focus)-Number(a.focus)||(b.updated_at||b.published_at||'').localeCompare(a.updated_at||a.published_at||''));
 if(state.view==='explore')return all.filter(r=>state.theme!=='all'||!r.focus||r.project_role==='早期观察');
 return all.filter(r=>r.origin==='history'||r.analysis||r.project_role==='登记基准');
}
function filters(){return {kind:state.kind,query:state.query,theme:state.theme,days:state.days,guide:state.guide};}
function render(){
 const original=baseItems(),accept=r=>R.match(r,filters())&&(state.status==='all'||saved.get(r)===state.status);
 const observations=state.view==='explore'?original.filter(r=>r.kind==='repo'&&r.project_role==='早期观察'):[];
 const base=original.filter(r=>!observations.includes(r)),matched=base.filter(accept);let count=0;
 const obs=observations.filter(accept),obsPanel=$('observation-panel');obsPanel.hidden=state.view!=='explore'||!obs.length;$('observation-title').textContent='早期项目观察 · '+obs.length+'（不属于精选）';$('observation-list').replaceChildren();for(const r of obs)$('observation-list').append(card(r,0));count+=obs.length;
 for(const kind of ['paper','repo','news']){
  const all=base.filter(r=>r.kind===kind),items=matched.filter(r=>r.kind===kind),list=$(kind+'-list');list.replaceChildren();$(kind+'-count').textContent=all.length;$(kind+'-total').textContent=items.length;
  const section=document.querySelector(`[data-section="${kind}"]`);section.hidden=state.kind!=='all'&&state.kind!==kind||kind==='news'&&!all.length;
  items.forEach((r,i)=>list.append(card(r,i)));
  if(!items.length&&kind!=='news'&&(state.kind===kind||state.kind==='all'&&kind==='paper'))empty(list,state.indexFailed&&!['archive','weekly'].includes(state.view)?'精选索引暂时无法读取，可继续查看历史日报。':state.view==='later'?'还没有稍后阅读的内容。点击任意条目的“稍后读”即可加入。':state.view==='daily'?'没有新的可读精选，或本期内容已读／已屏蔽。可到资料库查看其他资料。':'没有符合筛选的条目。');
  if(!section.hidden)count+=items.length;
 }
 $('no-results').hidden=count>0||!state.query;$('later-count').textContent=state.library.items.filter(r=>saved.get(r)==='later').length;
 $('paper-heading').textContent=state.view==='daily'?'先选一篇值得读的论文':'论文';$('repo-heading').textContent=state.view==='daily'?'本期值得看代码的项目':'项目与研究基准';
 renderContext();renderSources();renderUpdates();storageNote();
}
function renderContext(){
 const selected=['archive','weekly'].includes(state.view),home=R.home(state.library,today());
 $('report-file').hidden=true;
 if(selected){if(state.report){$('report-title').textContent=`${state.selectedDate} · ${state.view==='weekly'?'每周回顾':'研究日报'}`;$('report-note').textContent='这里保留当期论文、项目和来源状态；不会替换成今天的推荐。';$('report-file').href='data/'+(state.view==='weekly'?'weekly':'reports')+'/'+state.selectedDate+'.json';$('report-file').hidden=false;}return;}
 if(state.view==='daily'){
  $('report-title').textContent=home.date?(home.date===today()?'本期精选 · '+home.date:'最近一期精选 · '+home.date):'尚未形成可读精选';
  $('report-note').textContent=[home.date&&home.date!==today()?'今天没有新的精选，以下保留最近一期；不会用旧内容冒充新增。':'同一版本只精选一次。',home.note].filter(Boolean).join(' ');
 }else{$('report-title').textContent=state.view==='library'?'跨日期查找研究资料':state.view==='later'?'把想读的内容留到这里':'主线之外，也看看新的研究方向';$('report-note').textContent=state.view==='later'?'只保存在此浏览器；不同版本分别记录阅读状态。':state.view==='explore'?'这里包含未经全文评读的候选和早期项目；它们不等同于首页精选。':'默认合并同一论文／项目；旧版本仍可从版本入口和历史日报打开。';}
}
function renderSources(){
 const selected=['archive','weekly'].includes(state.view),report=selected?state.report:state.latestReport;
 const sources=report?.sources||(selected?[]:state.manifest?.latest_attempt?.sources||[]),list=$('source-list');list.replaceChildren();
 $('source-count').textContent=sources.filter(s=>s.status==='ok').length+'/'+sources.length;
 for(const s of sources){const row=el('div','source-row');row.dataset.status=s.status;row.append(el('span','',s.name),el('span','',({ok:'已采集',partial:'部分覆盖',failed:'需检查',not_connected:'待接入'})[s.status]||s.status));row.title=s.detail||'';list.append(row);}
 const warnings=sources.filter(s=>s.status!=='ok'),wx=warnings.some(s=>/扫码|授权|登录/.test(s.detail||''));
 $('health-title').textContent=selected?(state.report?'正在查看 '+state.selectedDate+' 的历史记录':'正在读取所选报告'):state.manifest?.latest?.date===today()?'今天的动态已采集':'今天尚无采集结果';
 $('health-detail').textContent=(report?'采集于 '+time(report.generated_at)+'。':'')+(wx?'公众号暂缺，需要重新扫码；论文与项目可继续阅读。':warnings.length?'部分来源尚未覆盖，可展开查看详情。':'公开来源状态可在详情中核对。');
 $('health-tag').textContent=selected?'历史记录':warnings.length?'来源未齐':'已更新';
 if(!selected&&state.manifest?.latest_attempt?.status==='failed'){$('health-title').textContent='最近一次采集失败，保留已有内容';$('health-detail').textContent='失败不等于没有新动态，请在运行详情中核对原因。';}
 $('analysis-updated').textContent=state.library.updated_at?'精选索引更新于 '+time(state.library.updated_at):'';
 $('news-updated').textContent=report?.news_updated_at?'公众号同步尝试于 '+time(report.news_updated_at):'';
 $('last-published').textContent=state.manifest?'站点数据更新于 '+time(state.manifest.updated_at):'';
 const growth=$('growth-list');growth.replaceChildren();
 function label(v){return !v||v.delta===null?'观察期不足':(v.delta>0?'+':'')+v.delta+(v.status==='complete'?'':' / '+v.days+'天');}
 for(const r of (report?.repo_growth||[]).slice(0,5)){const row=el('div','growth-row');row.append(link(r.title,r.url,'growth-name'),el('span','growth-numbers',label(r.day_growth)+' / '+label(r.week_growth)));growth.append(row);}
}
function renderUpdates(){
 const panel=$('updates-panel');panel.hidden=state.view!=='daily';if(panel.hidden)return;
 const used=new Set(Object.values(state.library.editions||{}).flatMap(e=>Object.values(e.items).flat()));
 const items=R.latest(state.library.items).filter(r=>!used.has(R.key(r))&&r.kind!=='repo'&&Date.parse(r.updated_at||r.published_at||'')>=Date.now()-7*86400000).sort((a,b)=>(b.updated_at||'').localeCompare(a.updated_at||''));
 $('updates-title').textContent='新版本与待评读 · '+items.length;const list=$('updates-list');list.replaceChildren();
 for(const r of items.slice(0,8)){const row=el('div','update-row');row.append(link(r.title,r.url),el('p','',(r.version||'')+' · '+(r.analysis?'有导读，尚未入选本期':'公开摘要，等待全文评读')+' · 首次发表 '+(r.published_at||'未知').slice(0,10)));list.append(row);}
 if(items.length>8)list.append(el('p','','其余候选可在“更多方向”中按主题查看。'));
 if(!items.length)empty(list,'暂无待评读的新版本或论文。');
}
function syncControls(){
 $('search').value=state.query;for(const [id,name]of [['theme-select','theme'],['time-select','days'],['guide-select','guide'],['status-select','status']])$(id).value=state[name];
 document.querySelectorAll('[data-kind]').forEach(b=>b.classList.toggle('selected',b.dataset.kind===state.kind));
}
function resetFilters(){Object.assign(state,{kind:'all',query:'',theme:'all',days:'all',guide:'all',status:'all'});syncControls();}
function writeURL(replace=false){const u=stateURL();if(u.href!==location.href)history[replace?'replaceState':'pushState']({},'',u);}
function markDate(date){
 document.querySelectorAll('[data-report-date]').forEach(a=>{const on=a.dataset.reportDate===date;a.classList.toggle('selected',on);if(on)a.setAttribute('aria-current','date');else a.removeAttribute('aria-current');});
 const d=new Date(date+'T12:00:00+08:00');$('calendar-date').textContent=new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',month:'long',day:'numeric'}).format(d);$('calendar-day').textContent='北京时间';
}
async function selectDate(date,{updateURL=true,replace=false,scroll=false,reset=true}={}){
 const view=state.view,record=(view==='weekly'?state.manifest.weekly:state.manifest.archive).find(r=>r.date===date);if(!record)return;
 const id=++state.loadId;if(reset)resetFilters();state.report=null;state.selectedDate=date;$('date-select').value=date;markDate(date);render();$('report-context').setAttribute('aria-busy','true');$('report-title').textContent='正在读取 '+date+' 的报告…';$('report-note').textContent='';
 try{const r=await json(record.path);if(id!==state.loadId||view!==state.view)return;state.report=r;if(date===state.manifest.latest?.date)state.latestReport=r;render();$('heading-detail').textContent='当前显示 '+date+' 的论文、项目和报道';if(updateURL)writeURL(replace);if(scroll){$('report-context').scrollIntoView({block:'start',behavior:'smooth'});$('report-context').focus({preventScroll:true});}}
 catch{if(id!==state.loadId)return;state.report=null;render();$('report-title').textContent=date+' 的报告暂时无法读取';$('report-note').textContent='请重选日期或刷新；不会显示其他日期的内容作为替代。';$('health-title').textContent='所选报告读取失败';}
 finally{if(id===state.loadId)$('report-context').setAttribute('aria-busy','false');}
}
async function setView(view,date=null,options={}){
 ++state.loadId;state.view=titles[view]?view:'daily';view=state.view;state.report=null;state.selectedDate=null;if(options.reset!==false)resetFilters();
 document.querySelectorAll('[data-view]').forEach(b=>b.classList.toggle('active',b.dataset.view===view));$('page-title').textContent=titles[view];$('edition').textContent=view==='daily'?'DAILY PICKS':view==='archive'?'DAILY ARCHIVE':'RESEARCH LIBRARY';
 $('archive-panel').hidden=view!=='archive';$('date-select').hidden=!['archive','weekly'].includes(view);$('catalog-filters').hidden=['archive','weekly'].includes(view);$('archive-list').replaceChildren();
 if(['archive','weekly'].includes(view)){
  const archive=view==='weekly'?state.manifest.weekly:state.manifest.archive;$('date-select').replaceChildren();for(const record of archive){const o=el('option','',record.date);o.value=record.date;$('date-select').append(o);if(view==='archive'){const a=el('a','archive-row');a.dataset.reportDate=record.date;a.href='?view=archive&date='+record.date;a.append(el('strong','',record.date),el('span','',record.count+' 条原始推荐 · 查看当期'));a.addEventListener('click',e=>{if(e.ctrlKey||e.metaKey||e.shiftKey||e.altKey)return;e.preventDefault();selectDate(record.date,{scroll:true});});$('archive-list').append(a);}}
  if(!archive.length){render();$('report-title').textContent='暂无报告';return;}
  if(date&&!archive.some(r=>r.date===date)){render();$('report-title').textContent='没有找到 '+date+' 的报告';return;}
  return selectDate(date||archive[0].date,{...options,reset:options.reset!==false});
 }
 markDate(today());$('heading-detail').textContent=view==='daily'?'先选一篇，再决定是否深入。':view==='explore'?'主线优先，保留发现其他方向的空间。':'按主题和阅读状态查找，不必记住在哪一天看到。';render();if(options.updateURL!==false)writeURL(options.replace);
 if(!state.latestReport&&state.manifest.latest){const id=state.loadId;try{state.latestReport=await json(state.manifest.latest.path);if(id===state.loadId)renderSources();}catch{}}
}
function fromURL(){const p=new URLSearchParams(location.search);Object.assign(state,{query:p.get('q')||'',kind:['paper','repo','news'].includes(p.get('kind'))?p.get('kind'):'all',theme:state.library.themes.includes(p.get('theme'))?p.get('theme'):'all',days:['7','30'].includes(p.get('days'))?p.get('days'):'all',guide:['yes','no'].includes(p.get('guide'))?p.get('guide'):'all',status:['unread','later','read','ignored'].includes(p.get('status'))?p.get('status'):'all'});syncControls();return setView(p.get('view')||(p.get('date')?'archive':'daily'),p.get('date'),{reset:false,updateURL:false});}
for(const b of document.querySelectorAll('[data-view]'))b.addEventListener('click',()=>{if(state.manifest)setView(b.dataset.view);});
for(const b of document.querySelectorAll('[data-kind]'))b.addEventListener('click',()=>{state.kind=b.dataset.kind;syncControls();render();writeURL(true);});
$('search').addEventListener('input',e=>{state.query=e.target.value.trim();if(state.query&&!['library','explore','later'].includes(state.view))setView('library',null,{reset:false,replace:true});else{render();writeURL(true);}});
for(const [id,name]of [['theme-select','theme'],['time-select','days'],['guide-select','guide'],['status-select','status']])$(id).addEventListener('change',e=>{state[name]=e.target.value;render();writeURL(true);});
$('clear-filters').addEventListener('click',()=>{resetFilters();render();writeURL(true);});$('date-select').addEventListener('change',e=>setView(state.view==='daily'?'archive':state.view,e.target.value));
window.addEventListener('popstate',()=>{if(state.manifest)fromURL();});
Promise.all([json('data/manifest.json'),json('data/library.json').catch(()=>{state.indexFailed=true;return {items:[],editions:{},themes:[]};})]).then(([m,l])=>{state.manifest=m;state.library=l;for(const t of l.themes){const o=el('option','',t);o.value=t;$('theme-select').append(o);}return fromURL();}).catch(()=>{$('health-title').textContent='暂时无法读取公开数据';$('health-detail').textContent='请检查网络，或稍后再试。';$('report-title').textContent='内容尚未载入';});
})();
