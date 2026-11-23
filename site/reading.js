(function(root,factory){const api=factory();if(typeof module==='object'&&module.exports)module.exports=api;else root.Reading=api;})(globalThis,function(){
'use strict';
const KEY='ai-security-reading-v1',STATUSES=new Set(['later','read','ignored']);
const version=r=>r.version||r.updated_at||r.published_at||r.url;
const key=r=>r.record_key||r.id+':'+version(r);
function createStore(storage){
 let values={},persistent=true;
 try{const raw=JSON.parse(storage.getItem(KEY)||'{}');for(const [k,v]of Object.entries(raw))if(/^item_[a-f0-9]{16}:/.test(k)&&STATUSES.has(v))values[k]=v;}catch{persistent=false;}
 return {get:r=>values[key(r)]||'unread',set(r,status){if(STATUSES.has(status))values[key(r)]=status;else delete values[key(r)];try{storage.setItem(KEY,JSON.stringify(values));persistent=true;}catch{persistent=false;}return persistent;},get persistent(){return persistent;}};
}
function latest(items){const m=new Map();for(const r of items){const p=m.get(r.id);const n=Number((r.version||'').replace(/^v/,'')),o=Number((p?.version||'').replace(/^v/,''));if(!p||(r.kind==='paper'&&n&&o?n>o:(r.updated_at||r.published_at||'')>(p.updated_at||p.published_at||'')))m.set(r.id,r);}return [...m.values()];}
function match(r,f={},now=Date.now()){
 if(f.kind&&f.kind!=='all'&&r.kind!==f.kind)return false;
 if(f.theme&&f.theme!=='all'&&!(r.themes||[]).includes(f.theme))return false;
 if(f.guide==='yes'&&!r.analysis)return false;if(f.guide==='no'&&r.analysis)return false;
 if(f.days&&f.days!=='all'){const t=Date.parse(r.updated_at||r.published_at||'');if(!Number.isFinite(t)||t>now||now-t>Number(f.days)*86400000)return false;}
 const a=r.analysis||{},n=a.recommendation||{};
 return !f.query||[r.title,r.summary,r.source,r.version,...(r.themes||[]),n.headline,n.why_read,n.read_next,a.verdict,a.overview].join(' ').toLocaleLowerCase().includes(f.query.toLocaleLowerCase());
}
function home(catalog,date){const dates=Object.keys(catalog.editions||{}).filter(d=>d<=date&&Object.values(catalog.editions[d].items).some(v=>v.length)).sort().reverse();const day=dates[0];const byKey=new Map((catalog.items||[]).map(r=>[key(r),r]));return {date:day||null,note:day?catalog.editions[day].note:'',items:day?Object.values(catalog.editions[day].items).flat().map(k=>byKey.get(k)).filter(Boolean):[]};}
return {version,key,createStore,latest,match,home};
});
