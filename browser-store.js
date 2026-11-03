'use strict';
const PagesStore=(()=>{
  const urls=new Map(), pending=new Map();let serial=0,worker,active=0;
  const req=r=>new Promise((resolve,reject)=>{r.onsuccess=()=>resolve(r.result);r.onerror=()=>reject(r.error)});
  const done=t=>new Promise((resolve,reject)=>{t.oncomplete=resolve;t.onabort=()=>reject(t.error||Error('Storage transaction cancelled.'));t.onerror=()=>{}});
  function decode(s,type='application/octet-stream'){const raw=atob(s),a=new Uint8Array(raw.length);for(let i=0;i<a.length;i++)a[i]=raw.charCodeAt(i);return new Blob([a],{type})}
  function expose(name,value){if(urls.has(name))URL.revokeObjectURL(urls.get(name));urls.set(name,URL.createObjectURL(decode(value,name.endsWith('.png')?'image/png':'application/octet-stream')))}
  const database=(async()=>{
    if(location.protocol==='file:')throw Error('Open this website through GitHub Pages or a local HTTP server.');
    const r=indexedDB.open('fibrosis-study:'+new URL('.',location.href).pathname,1);
    r.onupgradeneeded=()=>{const db=r.result;db.createObjectStore('participants',{keyPath:'id'});db.createObjectStore('assets',{keyPath:'name'});db.createObjectStore('audit',{autoIncrement:true})};
    const db=await req(r);db.onversionchange=()=>db.close();
    const t=db.transaction('assets');for(const a of await req(t.objectStore('assets').getAll()))expose(a.name,a.value);
    return db;
  })();
  async function snapshot(){const db=await database,t=db.transaction(['participants','assets','audit']);const [participants,assets,audit]=await Promise.all(['participants','assets','audit'].map(s=>req(t.objectStore(s).getAll())));return {participants,assets:Object.fromEntries(assets.map(a=>[a.name,a.value])),audit,created:new Date().toISOString()}}
  function status(message){let el=document.getElementById('engine-status');if(!el){el=document.createElement('div');el.id='engine-status';el.setAttribute('role','status');el.style.cssText='position:fixed;bottom:20px;left:24px;z-index:9999;max-width:440px;padding:14px 20px;background:#153d38;color:white;border-radius:10px;box-shadow:0 3px 20px #0003';document.body.append(el)}el.textContent=message;el.hidden=!message}
  function compute(op,body){
    if(!worker){worker=new Worker(new URL('compute-worker.js',document.baseURI),{type:'module'});worker.onmessage=({data})=>{if(data.status){status(data.status);return}const p=pending.get(data.id);if(!p)return;pending.delete(data.id);active--;status(active?'Calculating on this device…':'');data.error?p.reject(Error(data.error)):p.resolve(data.result)};worker.onerror=()=>{for(const p of pending.values())p.reject(Error('Calculation engine failed. Check your internet connection and try again.'));pending.clear();active=0;status('');worker.terminate();worker=null}}
    active++;status('Preparing calculation…');return new Promise((resolve,reject)=>{const id=++serial;pending.set(id,{resolve,reject});worker.postMessage({id,op,body})});
  }
  async function request(path,body){
    const db=await database;
    if(path==='participants'&&body===undefined)return req(db.transaction('participants').objectStore('participants').getAll());
    if(path==='audit')return (await req(db.transaction('audit').objectStore('audit').getAll())).reverse().slice(0,100);
    if(path==='participants'){
      const assets={};for(const m of body.measurements||[])if(m.source==='image')for(const suffix of ['.json','.original','.png','.mask.png','.overlay.png']){const a=await req(db.transaction('assets').objectStore('assets').get(m.asset+suffix));if(a)assets[a.name]=a.value}
      const p=await compute('validate',{participant:body,assets});
      const t=db.transaction(['participants','audit'],'readwrite'),finished=done(t),store=t.objectStore('participants');
      const previous=await req(store.get(p.id));
      if(previous&&previous.updated!==p.updated){t.abort();await finished.catch(()=>{});throw Error('This record changed in another window. Reload before editing.')}
      p.updated=new Date().toISOString();store.put(p);t.objectStore('audit').add({date:p.updated,action:'save',participant:p.id,body:JSON.stringify(p)});await finished;
      navigator.storage?.persist?.().catch(()=>{});return p;
    }
    if(path==='measure'){
      const result=await compute(path,body),t=db.transaction('assets','readwrite'),finished=done(t);
      for(const [name,value]of Object.entries(result.assets))t.objectStore('assets').put({name,value});await finished;
      for(const [name,value]of Object.entries(result.assets))expose(name,value);return result.measurement;
    }
    if(path==='restore'){
      const restored=await compute(path,body),t=db.transaction(['participants','assets','audit'],'readwrite'),finished=done(t);
      if(await req(t.objectStore('participants').count())){t.abort();await finished.catch(()=>{});throw Error('Restore requires an empty study. Existing records are unchanged.')}
      t.objectStore('assets').clear();t.objectStore('audit').clear();
      for(const p of restored.participants)t.objectStore('participants').put(p);
      for(const [name,value]of Object.entries(restored.assets))t.objectStore('assets').put({name,value});
      for(const a of restored.audit)t.objectStore('audit').add(a);
      t.objectStore('audit').add({date:new Date().toISOString(),action:'restore',participant:'',body:JSON.stringify({participants:restored.participants.length})});await finished;
      for(const url of urls.values())URL.revokeObjectURL(url);urls.clear();for(const [name,value]of Object.entries(restored.assets))expose(name,value);
      return {count:restored.participants.length};
    }
    if(path==='analysis')return compute(path,{participants:await request('participants'),options:body});
    if(path==='score/pbac'||path==='score/ufs')return compute(path,body);
    throw Error('Unknown operation.');
  }
  async function exportFile(path){
    const data=await snapshot(),result=await compute(path,data);
    const blob=path==='backup'?decode(result,'application/zip'):new Blob([result],{type:'text/csv;charset=utf-8'});
    const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=path==='backup'?'fibrosis-study-backup-'+new Date().toISOString().slice(0,10)+'.zip':path;a.click();setTimeout(()=>URL.revokeObjectURL(url),60000);return blob;
  }
  return {request,exportFile,assetURL:name=>urls.get(name)||'',ready:()=>database};
})();

