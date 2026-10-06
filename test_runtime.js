// Exercise the Zotero startup path: fresh XPI, cached runtime, updates and retry.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path').win32;
const meta = {version:'0.27.0',platform:'win-x64',runtime_sha256:'a'.repeat(64),backend_sha256:'b'.repeat(64)};
const root = 'C:\\Users\\Test\\.zitatlotse';
function harness(options={}) {
    let live=options.live || false, launches=[], files=new Map(), fail=options.fail;
    const marker={...meta,executable:path.join(root,'runtime',meta.runtime_sha256.slice(0,16),'pythonw.exe'),
        launcher:path.join(root,'backend','launcher.py')};
    if(options.cached) files.set(path.join(root,'installation.json'),marker);
    const context=vm.createContext({
        setTimeout: callback => callback(), PathUtils:{join:path.join},
        IOUtils:{makeDirectory:async()=>{},exists:async()=>true,readJSON:async file=>{
            if(!files.has(file)) throw new Error('missing'); return files.get(file);
        },writeJSON:async(file,data)=>files.set(file,data),writeUTF8:async()=>{}},
        Services:{io:{newURI:()=>({scheme:'jar',QueryInterface:()=>({JARFile:{QueryInterface:()=>({file:{path:'C:\\release.xpi'}})}})})}},
        Zotero:{isWin:true,locale:'en-US',File:{getContentsAsync:async url=>url.endsWith('manifest.json')?JSON.stringify(meta):'setup script'},
            HTTP:{request:async(_method,url)=>{
                if(url.startsWith('jar:'))return {responseText:url.endsWith('manifest.json')?JSON.stringify(meta):'setup script'};
                if(!live){const error=new Error('connection refused'); error.status=0; throw error;}
                return {responseText:JSON.stringify({ok:true,service:options.foreign?'other-app':'zitatlotse',version:live==='old'?'0.26.3':'0.27.0'})};}}},
        Components:{interfaces:{},classes:{
            '@mozilla.org/process/environment;1':{getService:()=>({get:name=>({USERPROFILE:'C:\\Users\\Test',SystemRoot:'C:\\Windows'})[name]||''})},
            '@mozilla.org/file/local;1':{createInstance:()=>({initWithPath(file){this.path=file;},exists:()=>true})},
            '@mozilla.org/process/util;1':{createInstance:()=>({init(file){this.executable=file.path;},
                runwAsync(args, _length, observer){
                    launches.push({executable:this.executable,args});
                    if(this.executable.endsWith('powershell.exe')) {
                        const status=args[args.indexOf('-StatusPath')+1];
                        files.set(status,{phase:fail?'failed':'ready',percent:fail?0:100,error:fail?'disk full':''});
                        if(!fail)files.set(path.join(root,'installation.json'),marker);
                    }
                    live=!fail; observer.observe({exitValue:fail?1:0},'process-finished');
                }})}
        }}
    });
    vm.runInContext(fs.readFileSync('plugin/bootstrap.js','utf8'),context);
    vm.runInContext('pluginRoot="jar:file:///C:/release.xpi!/"',context);
    return {context,launches,files,setFail(value){fail=value;},stop(){live=false;},run:()=>vm.runInContext('ensureLocalService()',context)};
}
(async()=>{
    let test=harness();
    await Promise.all([test.run(),test.run(),test.run()]);
    assert.equal(test.launches.length,1,'One first-install process for concurrent requests');
    assert.ok(test.launches[0].executable.endsWith('powershell.exe'));
    assert.equal(test.launches[0].args[test.launches[0].args.indexOf('-WindowStyle')+1],'Hidden');
    assert.ok(test.launches[0].args.includes('C:\\release.xpi'));
    assert.equal(vm.runInContext('runtimeState.phase',test.context),'ready');
    await test.run(); assert.equal(test.launches.length,1,'A ready service is reused');
    test.stop(); await test.run();
    assert.equal(test.launches.length,2);
    assert.ok(test.launches[1].executable.endsWith('pythonw.exe'),'Reboot/cold start uses bundled Python directly');
    assert.ok(!test.launches[1].executable.includes('.venv'),'No external Python environment');
    test=harness({cached:true}); await test.run();
    assert.equal(test.launches.length,1); assert.ok(test.launches[0].executable.endsWith('pythonw.exe'));
    test=harness({live:'old'}); await test.run();
    assert.equal(test.launches.length,1,'Older running backend is upgraded before use');
    test=harness({fail:true}); await assert.rejects(test.run(),/disk full/);
    assert.equal(vm.runInContext('runtimeState.phase',test.context),'failed');
    test.setFail(false); await test.run(); assert.equal(test.launches.length,2,'Failed setup can be retried');
    test=harness({live:true,foreign:true}); await assert.rejects(test.run(),/another application/);
    assert.equal(test.launches.length,0,'Do not replace an unrelated service on the port');
    console.log('XPI setup, bundled runtime, updates, reboot path, single launch, retry and port conflict: OK');
})().catch(error=>{console.error(error);process.exitCode=1;});
