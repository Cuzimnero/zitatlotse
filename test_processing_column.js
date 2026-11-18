// Real column callbacks with batched service/file doubles. No Zotero installation.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

(async () => {
    const timers = [], requests = [], errors = [], columns = [], removed = [];
    let refreshes = 0, fail = false, hold = null, indexHold = null, failIndex = false;
    const alerts = [], indexRequests = [];
    const pdf = (libraryID, key) => ({libraryID, key, parentID:1, deleted:false,
        attachmentContentType:"application/pdf", attachmentFilename:key+".pdf",
        isAttachment:()=>true,isRegularItem:()=>false,getFilePathAsync:async()=>"/"+key+".pdf"});
    const a = pdf(1,"A"), b = pdf(1,"B"), foreign = pdf(2,"A"), moved = pdf(1,"MOVED"), empty = pdf(1,"EMPTY");
    const items = {11:a,12:b,13:moved,14:empty};
    const parent = {libraryID:1,key:"PARENT",isAttachment:()=>false,isRegularItem:()=>true,getAttachments:()=>[11],
        getCollections:()=>[],getCreators:()=>[],getField:()=>"Synthetic paper"};
    for(const item of [a,b,foreign,moved,empty])item.getField=()=>"Synthetic PDF";
    const serverRecords = {A:{attachment_key:"A",chunks:12,file_size:100,file_mtime:1000},
        MOVED:{attachment_key:"MOVED",chunks:3,file_size:100,file_mtime:1000},
        EMPTY:{attachment_key:"EMPTY",chunks:0,file_size:100,file_mtime:1000}};
    const context = vm.createContext({
        setTimeout:cb=>{timers.push(cb);return timers.length;},clearTimeout(){},clearInterval(){},
        IOUtils:{stat:async path=>({size:path.includes("MOVED")?101:100,lastModified:1000000})},
        Zotero:{locale:"en-US",Prefs:{get(){}},logError:e=>errors.push(e.message),
            Items:{get:id=>items[id],getByLibraryAndKey:(lib,key)=>[parent,...Object.values(items),foreign].find(item=>item.libraryID===lib&&item.key===key)},
            getMainWindows:()=>[],getMainWindow:()=>({}),alert:(_win,_title,message)=>alerts.push(message),
            URI:{getItemURI:item=>"zotero://"+item.key},
            ItemTreeManager:{registerColumn:option=>{columns.push(option);return "plugin-column";},
                unregisterColumn:key=>removed.push(key),refreshColumns:()=>refreshes++},
            HTTP:{request:async (_method,url,options)=>{
                const payload=JSON.parse(options.body);requests.push(payload);
                if(url.endsWith("/index")){
                    indexRequests.push(payload);if(indexHold)await indexHold;
                    if(failIndex)throw {status:500,message:"Synthetic indexing failure"};
                    serverRecords[payload.attachment_key]={attachment_key:payload.attachment_key,chunks:5,file_size:100,file_mtime:1000};
                    return {responseText:JSON.stringify({status:"indexed",chunks:5})};
                }
                assert.ok(url.endsWith("/processing/status"));
                if(hold) await hold;
                if(fail) throw {status:500,message:"offline"};
                return {responseText:JSON.stringify({library_id:payload.library_id,documents:payload.library_id===1
                    ?payload.attachment_keys.map(key=>serverRecords[key]).filter(Boolean):[]})};
            }},
        },
    });
    vm.runInContext(fs.readFileSync("plugin/bootstrap.js","utf8"),context);
    context.collectNotice = message => alerts.push(message);
    vm.runInContext('showZitatlotseNotice = async (_win,message) => collectNotice(message)', context);
    await vm.runInContext("registerProcessingColumn()",context);
    assert.equal(columns.length,1);
    const column = columns[0];
    assert.equal(column.width,"42");
    assert.deepEqual(Array.from(column.defaultIn),["*"]);
    assert.deepEqual(Array.from(column.enabledTreeIDs),["main"]);
    const data = item => JSON.parse(column.dataProvider(item));
    const settle = async()=>{for(let i=0;i<30;i++){while(timers.length)timers.shift()();await Promise.resolve();}};
    assert.equal(data(a).state,"checking");
    data(a);data(parent);data(b);data(foreign);data(moved);data(empty);
    await settle();
    assert.equal(requests.length,2,"Visible attachments are batched per library, not requested once per row");
    assert.equal(data(a).state,"processed");
    assert.equal(data(parent).state,"processed");
    assert.equal(data(b).state,"unprocessed");
    assert.equal(data(foreign).state,"unprocessed","Matching keys from another library cannot inherit a green check");
    assert.equal(data(moved).state,"outdated");
    assert.equal(data(empty).state,"no_text","An empty index row is explained, never marked processed");
    assert.equal(data({...parent,getAttachments:()=>[11,12]}).state,"partial");
    assert.equal(data({...parent,getAttachments:()=>[]}).state,"no_pdf");
    assert.equal(column.dataProvider({isAttachment:()=>false,isRegularItem:()=>false}),"");
    const doc = {createElementNS:()=>({style:{},children:[],handlers:{},setAttribute(name,value){this[name]=value;},
        appendChild(child){this.children.push(child);},addEventListener(name,handler){this.handlers[name]=handler;}})};
    const green = column.renderCell(0,column.dataProvider(a),{className:"status"},false,doc);
    assert.equal(green.children[0].textContent,"✓");assert.match(green.style.cssText,/#15803d/);
    assert.match(green.title,/Processed/);assert.equal(green["aria-label"],green.title);
    context.Zotero.locale="de-DE";
    const red=column.renderCell(0,column.dataProvider(b),{},false,doc);
    assert.equal(red.children[0].textContent,"✕");assert.match(red.title,/Noch nicht verarbeitet/);
    assert.match(red.style.cssText,/align-items:center;justify-content:center/);
    // Clicking the row action processes that row, independent of the selected item.
    context.Zotero.locale="en-US";
    const clickEvent={preventDefault(){},stopPropagation(){}};
    parent.getAttachments=()=>[12];
    const clickable=column.renderCell(0,column.dataProvider(parent),{},false,doc).children[0];
    let finishIndex;indexHold=new Promise(resolve=>finishIndex=resolve);
    const firstClick=clickable.handlers.click(clickEvent);await settle();
    assert.equal(data(parent).state,"processing");
    const duplicateClick=clickable.handlers.click(clickEvent);await settle();
    assert.equal(indexRequests.length,1,"Repeated clicks cannot index the file twice");
    assert.equal(indexRequests[0].attachment_key,"B");
    assert.equal(indexRequests[0].item_key,"PARENT");
    finishIndex();indexHold=null;await firstClick;await duplicateClick;await settle();
    data(parent);await settle();assert.equal(data(parent).state,"processed");
    parent.getAttachments=()=>[11];
    const beforeMissing=indexRequests.length;
    const noPDF={...parent,key:"NO_PDF",getAttachments:()=>[]};items[20]=noPDF;
    await column.renderCell(0,column.dataProvider(noPDF),{},false,doc).children[0].handlers.click(clickEvent);
    assert.match(alerts.at(-1),/no PDF attachment/);
    assert.equal(column.renderCell(0,column.dataProvider(noPDF),{},false,doc).children[0].textContent,"?");
    assert.match(alerts.at(-1),/^No usable document available/);
    const web={libraryID:1,key:"WEB",attachmentContentType:"text/html",isAttachment:()=>true,isRegularItem:()=>false};items[21]=web;
    const webParent={...parent,key:"WEB_PARENT",getAttachments:()=>[21]};items[22]=webParent;
    assert.equal(data(webParent).state,"web_only");
    await column.renderCell(0,column.dataProvider(webParent),{},false,doc).children[0].handlers.click(clickEvent);
    assert.match(alerts.at(-1),/publisher or DOI landing page/);
    assert.equal(indexRequests.length,beforeMissing,"Metadata and landing pages must never be sent as PDFs");
    context.Zotero.locale="de-DE";
    const webButton=column.renderCell(0,column.dataProvider(webParent),{},false,doc).children[0];
    assert.equal(webButton.textContent,"?");
    assert.match(webButton.title,/Kein verwertbares Dokument verfügbar/);
    await webButton.handlers.click(clickEvent);
    assert.match(alerts.at(-1),/^Kein verwertbares Dokument verfügbar/);
    await column.renderCell(0,column.dataProvider(empty),{},false,doc).children[0].handlers.click(clickEvent);
    assert.match(alerts.at(-1),/OCR/);
    assert.equal(indexRequests.length,beforeMissing,"Unchanged PDFs without text should explain OCR instead of repeatedly indexing");
    const missing=pdf(1,"LOCAL_MISSING");missing.getFilePathAsync=async()=>null;items[23]=missing;
    data(missing);await settle();assert.equal(data(missing).state,"unavailable");
    const missingButton=column.renderCell(0,column.dataProvider(missing),{},false,doc).children[0];
    assert.equal(missingButton.textContent,"?");await missingButton.handlers.click(clickEvent);
    assert.match(alerts.at(-1),/^Kein verwertbares Dokument verfügbar/);
    assert.equal(indexRequests.length,beforeMissing);
    failIndex=true;
    await column.renderCell(0,column.dataProvider(parent),{},false,doc).children[0].handlers.click(clickEvent);
    assert.equal(data(parent).state,"error");
    assert.match(alerts.at(-1),/Verarbeitung fehlgeschlagen/);
    failIndex=false;
    vm.runInContext('processingErrors.clear()',context);
    context.a=a;
    vm.runInContext('processingBusy.add(processingKey(a))',context);
    assert.equal(data(parent).state,"processing");
    vm.runInContext('processingBusy.clear();processingErrors.add(processingKey(a))',context);
    assert.equal(data(a).state,"error");
    vm.runInContext('processingErrors.clear()',context);
    // Failed requests are unknown, never a false red/green processing claim.
    fail=true;
    const unseen=pdf(3,"C");data(unseen);await settle();
    assert.equal(data(unseen).state,"unknown");
    assert.ok(errors.length);
    fail=false;
    // Invalidation during a pending request cannot apply stale responses.
    let release;hold=new Promise(resolve=>release=resolve);
    context.pendingPDF=pdf(4,"D");data(context.pendingPDF);await settle();
    vm.runInContext('processingRecords.delete(processingKey(pendingPDF))',context);
    release();hold=null;await settle();
    assert.equal(data(context.pendingPDF).state,"checking");await settle();
    await vm.runInContext('shutdown()',context);
    assert.deepEqual(removed,["plugin-column"]);
    assert.ok(refreshes>0);
    console.log("Processing column: scope, batching, actual chunks, freshness, parent/PDF states, icons and shutdown: OK");
})().catch(error=>{console.error(error);process.exitCode=1;});
