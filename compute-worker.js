'use strict';
// Pinned browser Python runtime; computations and study data remain on this device.
const runtimeURL='https://cdn.jsdelivr.net/pyodide/v314.0.7/full/';
let engine, queue=Promise.resolve();
async function ready(){
  if(!engine)engine=(async()=>{
    self.postMessage({status:'Downloading calculation engine — internet required; first use may take a minute…'});
    const {loadPyodide}=await import(runtimeURL+'pyodide.mjs');
    const py=await loadPyodide({indexURL:runtimeURL});
    await py.loadPackage(['numpy','scipy','statsmodels','pillow']);
    py.FS.mkdir('/study');
    for(const name of ['research.py','imaging.py','bridge.py']){
      const r=await fetch(new URL('python/'+name,self.location.href));
      if(!r.ok)throw Error('Cannot load calculation file '+name);
      py.FS.writeFile('/study/'+name,await r.text());
    }
    await py.runPythonAsync("import sys; sys.path.insert(0, '/study'); from bridge import dispatch_json");
    return py;
  })().catch(e=>{engine=null;throw Error('Could not load the calculation engine. Check your internet connection and allow cdn.jsdelivr.net, then try again. '+e.message)});
  return engine;
}
self.onmessage=({data})=>{
  queue=queue.then(async()=>{
    try{
      const py=await ready();
      self.postMessage({status:'Calculating on this device…'});
      py.globals.set('request_json',JSON.stringify(data));
      const result=JSON.parse(await py.runPythonAsync('dispatch_json(request_json)'));
      self.postMessage({id:data.id,result});
    }catch(e){self.postMessage({id:data.id,error:String(e.message||e)});}
  });
};
