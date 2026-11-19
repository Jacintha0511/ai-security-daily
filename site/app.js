/* All external source strings are inserted with textContent, never innerHTML. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const state = {manifest:null, report:null, kind:'all', view:'daily', query:'',analyses:{items:{}}};
  const dateInBeijing = date => new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(date);
  const today = () => dateInBeijing(new Date());
  const timeLabel = value => value ? new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}).format(new Date(value)) : '未知';
  function el(tag, className, content) { const node=document.createElement(tag); if(className)node.className=className; if(content!==undefined)node.textContent=String(content); return node; }
  function link(label,url,className) {const node=el('a',className,label); try {const u=new URL(url,location.href);if(!['https:','http:'].includes(u.protocol))throw Error('scheme');node.href=u.href;node.target='_blank';node.rel='noopener noreferrer';} catch {node.removeAttribute('href');} return node;}
  function empty(container,message) {container.append(el('div','empty-state',message));}
  async function getJSON(path) {const response=await fetch(new URL(path,document.baseURI),{cache:'no-store'});if(!response.ok)throw Error('HTTP '+response.status);return response.json();}
  function statusLabel(status) {return ({ok:'已采集',partial:'部分完成',failed:'采集失败',not_connected:'待接入',complete:'已生成'})[status]||status;}
  function displayHealth() {
    const manifest=state.manifest, latest=manifest.latest, attempt=manifest.latest_attempt;
    const panel=document.querySelector('.health-panel');panel.classList.remove('good','bad');
    let title,detail,tag;
    if(!latest || latest.date!==today()) {title='今天尚未产出日报';detail=latest ? `最近一期为 ${latest.date}。${attempt?.status==='failed'?'最近一次采集失败，请查看运行记录。':'请结合运行记录查看调度或补跑情况。'}` : '尚无可用日报，等待首次云端采集。';tag='等待更新';}
    else if(attempt?.status==='failed' && attempt.date===today()) {panel.classList.add('bad');title='今天已有日报，最近一次更新失败';detail='保留上一次有效内容。以下为最近可用结果，失败不等于没有新动态。';tag='更新失败';}
    else if(latest.status==='partial') {title='今天的日报已产出 · 来源尚未全部覆盖';detail=`实际生成于 ${timeLabel(latest.generated_at)}。未接入或失败的来源已在右侧列明。`;tag='部分完成';}
    else {panel.classList.add('good');title='今天的日报已产出';detail=`实际生成于 ${timeLabel(latest.generated_at)}。规则预筛，无模型调用。`;tag='已更新';}
    $('health-title').textContent=title;$('health-detail').textContent=detail;$('health-tag').textContent=tag;
    $('last-published').textContent='站点数据更新于 '+timeLabel(manifest.updated_at)+' · 北京时间';
  }
  function analysisButton(item) {
    const entries=Object.values(state.analyses.items||{}).filter(x=>x.item_id===item.id);
    const requested=item.version||item.updated_at||item.published_at||item.url;
    const entry=entries.filter(x=>x.requested_version===requested).sort((a,b)=>b.updated_at.localeCompare(a.updated_at))[0];
    const ready=entry&&['ready','partial'].includes(entry.status);
    const labels={paper:'查看论文解析',repo:'查看项目分析',news:'查看研究点评'};
    const a=el('a','analysis-link',labels[item.kind]+(ready?(entry.status==='partial'?' · 部分解析':' →'):' · 待解析'));
    a.href='analysis.html?id='+encodeURIComponent(item.id)+(entry?'&v='+encodeURIComponent(entry.fingerprint):'');
    return a;
  }
  function paperCard(item,index) {
    const card=el('article','paper-card'+(index===0?' lead':''));
    const meta=el('div','item-meta');meta.append(el('span','source-label',item.source),el('span','',item.version||'预印本 / 状态待核'),el('span','priority-label',item.priority||'快速浏览'));
    const h=el('h3');h.append(link(item.title,item.url));card.append(meta,h,el('p','summary',item.summary||'暂无公开摘要。'));
    const bottom=el('div','item-bottom');bottom.append(link('阅读原文 ↗',item.url,'read-link'),el('span','item-date','更新 '+(item.updated_at||item.published_at||'日期未知').slice(0,10)));bottom.append(analysisButton(item));card.append(bottom);
    const details=el('details','evidence-detail');details.append(el('summary','', '为什么推荐 / 来源信息'),el('p','',item.reason||'主题规则匹配'),el('p','',item.selection_basis||'规则预筛'),el('p','',`首次发表：${item.published_at||'未知'}；首次发现：${item.first_seen||'未知'}。获取摘要不等于精读全文。`));card.append(details);return card;
  }
  function repoRow(item,index) {
    const row=el('article','repo-row');const body=el('div');body.append(link(item.title,item.url,'repo-name'),el('p','summary',item.summary||'暂无公开描述。'));
    const bottom=el('div','item-bottom');bottom.append(el('span','item-date',item.reason||'已跟踪安全研究项目'),link('仓库 ↗',item.url,'read-link'));if(index===0)bottom.append(analysisButton(item));body.append(bottom);
    row.append(el('span','rank-number',String(index+1).padStart(2,'0')),body,el('span','stars','☆ '+new Intl.NumberFormat('en',{notation:'compact',maximumFractionDigits:1}).format(item.stars||0)));return row;
  }
  function newsRow(item,index) {const row=el('article','news-row');const h=el('h3');h.append(link(item.title,item.url));row.append(el('span','source-label',item.source),h,el('p','summary',item.summary),el('p','item-date',item.reason));row.append(link('阅读原文 ↗',item.url,'read-link'));if(index<2)row.append(analysisButton(item));return row;}
  function renderSources() {
    const list=$('source-list');list.replaceChildren();const attempt=state.manifest?.latest_attempt; const sources=attempt?.status==='failed'&&state.view==='daily'?attempt.sources:(state.report?.sources||attempt?.sources||[]);
    $('source-count').textContent=`${sources.filter(s=>s.status==='ok').length}/${sources.length} 已接通`;
    sources.forEach(source=>{const row=el('div','source-row');row.dataset.status=source.status;row.append(el('span','status-dot'),el('span','',source.name),el('span','',statusLabel(source.status)));row.title=source.detail||'';list.append(row);});
    if(!sources.length)empty(list,'尚无来源运行记录。');
  }
  function growthLabel(value) {if(!value || value.delta===null)return '观察期不足';const number=(value.delta>0?'+':'')+value.delta;return value.status==='complete'?number:`${number} / ${value.days}天`;}
  function renderGrowth() {const container=$('growth-list');container.replaceChildren();(state.report?.repo_growth||[]).slice(0,5).forEach(item=>{const row=el('div','growth-row');const nums=el('div','growth-numbers');nums.append(el('span','',growthLabel(item.day_growth)),el('span','',growthLabel(item.week_growth)));row.append(link(item.title.split('/').pop(),item.url,'growth-name'),nums);container.append(row);});if(!container.children.length)empty(container,'等待项目快照；不估算缺失历史。');}
  function matches(item) {return !state.query || `${item.title} ${item.summary} ${item.source} ${item.reason}`.toLocaleLowerCase().includes(state.query);}
  function render() {
    let total=0;
    for(const kind of ['paper','repo','news']) {const all=state.report?.items?.[kind]||[],items=all.filter(matches),list=$(kind+'-list');list.replaceChildren();$(kind+'-count').textContent=all.length;$(kind+'-total').textContent=items.length;
      const section=document.querySelector(`[data-section="${kind}"]`);section.hidden=state.kind!=='all'&&state.kind!==kind;
      items.forEach((item,index)=>list.append(kind==='paper'?paperCard(item,index):kind==='repo'?repoRow(item,index):newsRow(item,index)));
      if(!items.length)empty(list,all.length?'没有匹配当前搜索的条目。':kind==='news'?'本期没有可推荐报道。公众号由本机订阅服务同步，接入及最近采集状态见右侧；采集缺失不代表没有更新。':'本次没有可推荐条目，请结合来源状态判断。');
      if(!section.hidden)total+=items.length;
    }
    $('no-results').hidden=total>0||!state.query;renderSources();renderGrowth();if($('analysis-updated'))$('analysis-updated').textContent=state.analyses.updated_at?'解析更新于 '+timeLabel(state.analyses.updated_at)+' · Codex 账号额度':'本机 Codex 每天 02:00 解析，03:45 补跑';if($('news-updated'))$('news-updated').textContent=state.report?.news_updated_at?'公众号采集于 '+timeLabel(state.report.news_updated_at):'公众号尚未完成本机同步';
  }
  async function selectDate(date) {
    const record=(state.view==='weekly'?state.manifest.weekly:state.manifest.archive).find(r=>r.date===date);if(!record)return;
    try {state.report=await getJSON(record.path);$('date-select').value=date;$('heading-detail').textContent=state.view==='weekly'?`${state.report.start} — ${date} · ${state.report.days_with_reports} 天有公开日报`:`${date} · 公开来源 · 规则预筛 · 保留证据边界`;render();}
    catch {$('health-title').textContent='该期报告暂时无法读取';$('health-detail').textContent='请稍后刷新，或在 GitHub Actions 查看部署记录。';}
  }
  function setView(view) {
    state.view=view;document.querySelectorAll('[data-view]').forEach(b=>b.classList.toggle('active',b.dataset.view===view));
    $('page-title').textContent=({daily:'今日研究动态',archive:'历史研究日报',weekly:'每周动态回顾'})[view];$('edition').textContent=view==='weekly'?'WEEKLY REVIEW':view==='archive'?'DAILY ARCHIVE':'DAILY BRIEFING';
    const archive=view==='weekly'?state.manifest.weekly:state.manifest.archive;$('date-select').replaceChildren();
    archive.forEach(record=>{const option=el('option','',record.date);option.value=record.date;$('date-select').append(option);});
    if(!archive.length){$('date-select').append(el('option','','暂无记录'));state.report=null;render();$('heading-detail').textContent='尚无该类型报告，等待云端生成。';}
    else selectDate(archive[0].date);
    $('archive-panel').hidden=view!=='archive';const list=$('archive-list');list.replaceChildren();
    if(view==='archive')archive.forEach(record=>{const button=el('button','archive-row');button.append(el('strong','',record.date),el('span','',`${record.count} 条推荐 · ${statusLabel(record.status)}  →`));button.addEventListener('click',()=>selectDate(record.date));list.append(button);});
  }
  document.querySelectorAll('[data-kind]').forEach(button=>button.addEventListener('click',()=>{state.kind=button.dataset.kind;document.querySelectorAll('[data-kind]').forEach(b=>b.classList.toggle('selected',b===button));render();}));
  document.querySelectorAll('[data-view]').forEach(button=>button.addEventListener('click',()=>{if(state.manifest)setView(button.dataset.view);}));
  $('search').addEventListener('input',event=>{state.query=event.target.value.trim().toLocaleLowerCase();render();});$('date-select').addEventListener('change',event=>selectDate(event.target.value));
  const now=new Date();$('calendar-date').textContent=new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',month:'long',day:'numeric'}).format(now);$('calendar-day').textContent=new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',weekday:'long'}).format(now)+' · 北京时间';
  Promise.all([getJSON('./data/manifest.json'),getJSON('./data/analyses/index.json').catch(()=>({items:{}}))]).then(([manifest,analyses])=>{state.analyses=analyses;return manifest;}).then(manifest=>{state.manifest=manifest;displayHealth();setView('daily');}).catch(()=>{$('health-title').textContent='公开日报数据暂时不可用';$('health-detail').textContent='请检查网络或查看 GitHub Actions。此时不能判断今天是否成功产出。';$('health-tag').textContent='待核实';document.querySelector('.health-panel').classList.add('bad');});
})();

