const assert=require('node:assert/strict');
const test=require('node:test');
const vm=require('node:vm');
const fs=require('node:fs');
const path=require('node:path');
class Node {
 constructor(tag='div'){this.tagName=tag;this.children=[];this.dataset={};this.attrs={};this.events={};this.value='';this.hidden=false;this.className='';this.ownText='';this.classList={toggle:(c,on)=>{const v=new Set(this.className.split(' ').filter(Boolean));if(on===undefined?!v.has(c):on)v.add(c);else v.delete(c);this.className=[...v].join(' ');},add:c=>this.classList.toggle(c,true),remove:(...cs)=>cs.forEach(c=>this.classList.toggle(c,false))};}
 set textContent(v){this.ownText=String(v);this.children=[];} get textContent(){return this.ownText+this.children.map(c=>c.textContent).join('');}
 append(...nodes){this.children.push(...nodes);} replaceChildren(...nodes){this.children=nodes;this.ownText='';}
 addEventListener(t,fn){this.events[t]=fn;} setAttribute(k,v){this.attrs[k]=v;} removeAttribute(k){delete this.attrs[k];}
 scrollIntoView(){} focus(){} async click(){return this.events.click?.({preventDefault(){}});}
}
const tick=async()=>{for(let i=0;i<5;i++)await new Promise(r=>setImmediate(r));};
function boot(search='?view=daily',fetchReport){
 const ids={};for(const id of ['health-title','health-detail','health-tag','last-published','source-count','source-list','growth-list','no-results','analysis-updated','news-updated','date-select','heading-detail','page-title','edition','archive-panel','archive-list','search','calendar-date','calendar-day','report-context','report-title','report-note','report-file'])ids[id]=new Node();
 for(const k of ['paper','repo','news'])for(const suffix of ['list','count','total'])ids[k+'-'+suffix]=new Node();
 const kinds=['all','paper','repo','news'].map(k=>Object.assign(new Node('button'),{dataset:{kind:k}}));
 const views=['daily','archive','weekly'].map(v=>Object.assign(new Node('button'),{dataset:{view:v}}));
 const sections=Object.fromEntries(['paper','repo','news'].map(k=>[k,new Node('section')]));const health=new Node();
 const fixture=date=>({date,generated_at:date+'T01:00:00Z',status:'partial',sources:[{name:'source-'+date,status:'ok',count:1}],repo_growth:[],items:{paper:[{id:'item_1111111111111111',kind:'paper',title:'paper-'+date,summary:'content-'+date,url:'https://arxiv.org/abs/2601.11111',source:'arXiv',version:'v1'}],repo:[],news:[]}});
 const manifest={latest:{date:'2026-11-22',status:'partial',generated_at:'2026-11-22T01:00:00Z'},archive:['2026-11-22','2026-11-21','2026-11-18'].map(date=>({date,count:1,status:'partial',path:'data/reports/'+date+'.json'})),weekly:[]};
 const location=new URL('https://example.test/ai-security-daily/'+search),events={};
 const context={console,URL,URLSearchParams,Intl,Date,encodeURIComponent,location,document:{baseURI:'https://example.test/ai-security-daily/',getElementById:id=>ids[id],createElement:tag=>new Node(tag),querySelector:q=>q==='.health-panel'?health:sections[q.match(/data-section="(.+)"/)?.[1]],querySelectorAll:q=>q==='[data-kind]'?kinds:q==='[data-view]'?views:q==='[data-report-date]'?ids['archive-list'].children:[]},window:{addEventListener:(t,fn)=>events[t]=fn},history:{pushState:(a,b,url)=>location.href=String(url),replaceState:(a,b,url)=>location.href=String(url)},fetch:async url=>{
  const name=new URL(url,location).pathname;
  if(name.endsWith('/manifest.json'))return{ok:true,json:async()=>manifest};
  if(name.endsWith('/index.json'))return{ok:true,json:async()=>({items:{}})};
  const date=name.match(/(\d{4}-\d{2}-\d{2})\.json$/)?.[1];if(!date)return{ok:false,status:404};
  const value=fetchReport?await fetchReport(date,fixture):fixture(date);return{ok:true,json:async()=>value};
 }};
 vm.runInNewContext(fs.readFileSync(path.join(__dirname,'site/app.js'),'utf8'),context);
 return{ids,kinds,views,location,events,fixture};
}
test('archive deep link loads that date and its own sources',async()=>{const a=boot('?view=archive&date=2026-11-18');await tick();assert.match(a.ids['paper-list'].textContent,/paper-2026-11-18/);assert.match(a.ids['calendar-date'].textContent,/18/);assert.match(a.ids['source-list'].textContent,/source-2026-11-18/);assert.equal(a.ids['report-file'].href,'data/reports/2026-11-18.json');assert.equal(a.ids['archive-list'].children[2].attrs['aria-current'],'date');});
test('changing archive date clears old search and category filters',async()=>{const a=boot('?view=archive');await tick();a.ids.search.value='not-found';a.ids.search.events.input({target:a.ids.search});await a.kinds[2].click();await a.ids['archive-list'].children[2].click();await tick();assert.equal(a.ids.search.value,'');assert.match(a.ids['paper-list'].textContent,/paper-2026-11-18/);assert.equal(a.location.searchParams.get('date'),'2026-11-18');assert.match(a.kinds[0].className,/selected/);});
test('older response cannot overwrite a newer date selection',async()=>{const pending={};const a=boot('?view=archive',(date,fixture)=>date==='2026-11-22'?fixture(date):new Promise(resolve=>pending[date]=()=>resolve(fixture(date))));await tick();a.ids['archive-list'].children[2].click();await tick();a.ids['archive-list'].children[1].click();await tick();pending['2026-11-21']();await tick();pending['2026-11-18']();await tick();assert.match(a.ids['paper-list'].textContent,/paper-2026-11-21/);assert.equal(a.ids['date-select'].value,'2026-11-21');});
test('a failed date fetch does not show the previous report as that date',async()=>{const a=boot('?view=archive',(date,fixture)=>{if(date==='2026-11-18')throw Error('offline');return fixture(date);});await tick();a.ids['archive-list'].children[2].click();await tick();assert.doesNotMatch(a.ids['paper-list'].textContent,/paper-2026-11-22/);assert.match(a.ids['report-title'].textContent,/2026-11-18.*无法读取/);assert.equal(a.ids['report-file'].hidden,true);assert.doesNotMatch(a.ids['source-list'].textContent,/source-2026-11-22/);});
test('browser back restores the archived report',async()=>{const a=boot();await tick();a.location.href='https://example.test/ai-security-daily/?view=archive&date=2026-11-18';a.events.popstate();await tick();assert.match(a.ids['paper-list'].textContent,/paper-2026-11-18/);});
test('analysis link preserves the selected report for return navigation',async()=>{const a=boot('?view=archive&date=2026-11-18');await tick();const bottom=a.ids['paper-list'].children[0].children[3];const link=bottom.children.find(c=>c.className==='analysis-link');assert.match(decodeURIComponent(link.href),/back=\/ai-security-daily\/\?view=archive&date=2026-11-18/);});
