(() => {
'use strict';
const $=id=>document.getElementById(id);
function el(tag,cls,text){const e=document.createElement(tag);if(cls)e.className=cls;if(text!==undefined)e.textContent=String(text);return e;}
function link(text,url){const a=el('a','',text);try{const u=new URL(url,location.href);if(!['http:','https:'].includes(u.protocol))throw Error();a.href=u.href;a.target='_blank';a.rel='noopener noreferrer';}catch{}return a;}
async function json(path){const r=await fetch(path,{cache:'no-store'});if(!r.ok)throw Error('HTTP '+r.status);return r.json();}
function list(root,values){const ul=el('ul');(values||[]).forEach(v=>ul.append(el('li','',v)));root.append(ul);}
function panel(id,title,values){if(!values?.length)return;$(id).append(el('h2','',title));list($(id),values);}
async function start(){
const p=new URLSearchParams(location.search),id=p.get('id'),version=p.get('v');
const back=p.get('back');if(back){const target=new URL(back,location.href);if(target.origin===location.origin&&target.pathname.replace(/index\.html$/,'')===location.pathname.replace(/analysis\.html$/,'')){const a=document.querySelector('.back-link')||document.querySelector('header a');if(a)a.href=target.href;}}
if(!/^item_[a-f0-9]{16}$/.test(id||'')||(version&&!/^[a-f0-9]{20}$/.test(version)))throw Error('无效的解析地址');
const idx=await json('data/analyses/index.json');
const entries=Object.values(idx.items||{}).filter(e=>e.item_id===id&&(!version||e.fingerprint===version)).sort((a,b)=>b.updated_at.localeCompare(a.updated_at));
const entry=entries[0];
if(!entry?.path){$('analysis-title').textContent=entry?.title||'全文解析尚待生成';$('overview').append(el('h2','',entry?.status==='failed'?'材料读取失败，等待补跑':'等待本机 Codex 解析'),el('p','',entry?.message||'本机任务每天北京时间 02:00 启动，03:45 补跑。电脑须开机、联网，并保持 Codex 应用开启。'),el('p','','日报采集与解析独立进行。尚无解析时，不以摘要替代全文分析。'));return;}
if(!/^data\/analyses\/item_[a-f0-9]{16}-[a-f0-9]{20}\.json$/.test(entry.path))throw Error('解析路径不合法');
const a=await json(entry.path);$('analysis-title').textContent=a.title;document.title=a.title+' · 研究解析';
const when=new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',dateStyle:'medium',timeStyle:'short',hour12:false}).format(new Date(a.generated_at));
$('analysis-meta').append(el('span','','导读已生成 · 核查范围见下方'),el('span','',a.model),el('span','',when+' 北京时间'),el('span','','材料版本 '+a.version));
$('overview').append(el('p','eyebrow','ONE MINUTE / 一分钟判断'),el('h2','',a.verdict),el('p','',a.overview),link('阅读原始材料 ↗',a.url));
const note=a.recommendation||{};
const brief=el('div','quick-reading');brief.append(el('h3','','3 分钟概览'));
if(note.why_read)brief.append(el('p','','为什么读：'+note.why_read));
if(note.read_next)brief.append(el('p','','重点阅读：'+note.read_next));
if(a.limitations?.length)brief.append(el('p','reading-boundary','阅读边界：'+a.limitations[0]));
$('overview').append(brief);
const controls=el('div','reading-controls');for(const [label,opened]of [['展开全部详解',true],['收起详解',false]]){const b=el('button','quiet-button',label);b.addEventListener('click',()=>document.querySelectorAll('.analysis-section').forEach(s=>s.open=opened));controls.append(b);}controls.append(el('span','','30 分钟精读：按目录阅读方法、实验和局限。'));$('overview').append(controls);
const openHash=()=>{const target=document.getElementById(location.hash.slice(1));if(target?.className==='analysis-section')target.open=true;};window.addEventListener('hashchange',openHash);
json('data/library.json').then(l=>{const r=l.items.find(x=>x.analysis?.fingerprint===a.fingerprint&&x.id===a.item_id);if(!r)return;let storage;try{storage=localStorage;}catch{storage=null;}const saved=Reading.createStore(storage);const box=el('div','read-actions');const paint=()=>{box.replaceChildren();for(const [v,t]of [['later','稍后读'],['read','已读'],['ignored','不感兴趣']]){const b=el('button',saved.get(r)===v?'selected':'',t);b.addEventListener('click',()=>{const persisted=saved.set(r,saved.get(r)===v?'unread':v);paint();if(!persisted)box.append(el('span','','浏览器未允许保存，刷新后可能丢失。'));});box.append(b);}};paint();$('overview').append(box);}).catch(()=>{});

const sourceMap=Object.fromEntries(a.sources.map(s=>[s.id,s]));
a.sections.forEach((s,i)=>{const section=el('details','analysis-section');section.id='part-'+i;const nav=el('a','',String(i+1).padStart(2,'0')+' '+s.title);nav.href='#'+section.id;nav.addEventListener('click',()=>{section.open=true;});$('toc').append(nav);const heading=el('summary','section-summary',s.title);section.append(heading);(s.paragraphs||[]).forEach(v=>section.append(el('p','',v)));if(s.bullets)list(section,s.bullets);
if(s.diagram){const d=el('ol','method-flow');s.diagram.forEach(v=>d.append(el('li','',v)));section.append(d);}
if(s.table){const wrap=el('div','table-wrap'),table=el('table'),head=el('tr');s.table.headers.forEach(v=>head.append(el('th','',v)));const th=el('thead');th.append(head);table.append(th);const body=el('tbody');s.table.rows.forEach(row=>{const tr=el('tr');row.forEach(v=>tr.append(el('td','',v)));body.append(tr);});table.append(body);wrap.append(table);section.append(wrap);}
(s.qa||[]).forEach(q=>{const d=el('details','quiz');d.append(el('summary','',q.question),el('p','',q.answer));section.append(d);});
const refs=el('div','reference-line');(s.refs||[]).forEach(r=>{const src=sourceMap[r.source];if(src)refs.append(link('依据：'+src.label+' · '+r.locator,src.url));});section.append(refs);$('sections').append(section);});
openHash();
panel('limitations','阅读边界与待核实内容',a.limitations);panel('checks','本次实际核查范围',a.checks);$('sources').append(el('h2','','原始材料'));a.sources.forEach(s=>{const p=el('p');p.append(link(s.id+' · '+s.label,s.url));$('sources').append(p);});
}
start().catch(e=>{$('analysis-title').textContent='解析暂时无法读取';$('overview').append(el('p','','请返回日报查看最新状态。'+(e.message==='无效的解析地址'?e.message:'')));});
})();