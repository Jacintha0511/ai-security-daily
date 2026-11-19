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
if(!/^item_[a-f0-9]{16}$/.test(id||'')||(version&&!/^[a-f0-9]{20}$/.test(version)))throw Error('无效的解析地址');
const idx=await json('data/analyses/index.json');
const entries=Object.values(idx.items||{}).filter(e=>e.item_id===id&&(!version||e.fingerprint===version)).sort((a,b)=>b.updated_at.localeCompare(a.updated_at));
const entry=entries[0];
if(!entry?.path){$('analysis-title').textContent=entry?.title||'全文解析尚待生成';$('overview').append(el('h2','',entry?.status==='failed'?'材料读取失败，等待补跑':'等待本机 Codex 解析'),el('p','',entry?.message||'本机任务每天北京时间 02:00 启动，03:45 补跑。电脑须开机、联网，并保持 Codex 应用开启。'),el('p','','日报采集与解析独立进行。尚无解析时，不以摘要替代全文分析。'));return;}
if(!/^data\/analyses\/item_[a-f0-9]{16}-[a-f0-9]{20}\.json$/.test(entry.path))throw Error('解析路径不合法');
const a=await json(entry.path);$('analysis-title').textContent=a.title;document.title=a.title+' · 研究解析';
const when=new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',dateStyle:'medium',timeStyle:'short',hour12:false}).format(new Date(a.generated_at));
$('analysis-meta').append(el('span','',a.status==='ready'?'全文导读':'部分解析 · 存在待核实内容'),el('span','',a.model),el('span','',when+' 北京时间'),el('span','','材料版本 '+a.version));
$('overview').append(el('p','eyebrow','ONE MINUTE / 一分钟判断'),el('h2','',a.verdict),el('p','',a.overview),link('阅读原始材料 ↗',a.url));
const sourceMap=Object.fromEntries(a.sources.map(s=>[s.id,s]));
a.sections.forEach((s,i)=>{const section=el('section','analysis-section');section.id='part-'+i;const nav=el('a','',String(i+1).padStart(2,'0')+' '+s.title);nav.href='#'+section.id;$('toc').append(nav);section.append(el('p','section-kicker',String(i+1).padStart(2,'0')+' / '+(s.stance||'材料解读')),el('h2','',s.title));(s.paragraphs||[]).forEach(v=>section.append(el('p','',v)));if(s.bullets)list(section,s.bullets);
if(s.diagram){const d=el('ol','method-flow');s.diagram.forEach(v=>d.append(el('li','',v)));section.append(d);}
if(s.table){const wrap=el('div','table-wrap'),table=el('table'),head=el('tr');s.table.headers.forEach(v=>head.append(el('th','',v)));const th=el('thead');th.append(head);table.append(th);const body=el('tbody');s.table.rows.forEach(row=>{const tr=el('tr');row.forEach(v=>tr.append(el('td','',v)));body.append(tr);});table.append(body);wrap.append(table);section.append(wrap);}
(s.qa||[]).forEach(q=>{const d=el('details','quiz');d.append(el('summary','',q.question),el('p','',q.answer));section.append(d);});
const refs=el('div','reference-line');(s.refs||[]).forEach(r=>{const src=sourceMap[r.source];if(src)refs.append(link('依据：'+src.label+' · '+r.locator,src.url));});section.append(refs);$('sections').append(section);});
panel('limitations','仍需核实与阅读限制',a.limitations);panel('checks','本次实际核查范围',a.checks);$('sources').append(el('h2','','原始材料'));a.sources.forEach(s=>{const p=el('p');p.append(link(s.id+' · '+s.label,s.url));$('sources').append(p);});
}
start().catch(e=>{$('analysis-title').textContent='解析暂时无法读取';$('overview').append(el('p','','请返回日报查看最新状态。'+(e.message==='无效的解析地址'?e.message:'')));});
})();