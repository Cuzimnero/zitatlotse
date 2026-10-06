// Exercise the real window handlers without Zotero or a running AI provider.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

class Node {
    constructor(doc, tag) {
        this.ownerDocument = doc;
        this.tag = tag;
        this.localName = tag;
        this.children = [];
        this.attributes = {};
        this.handlers = {};
        this.value = "";
        this.style = {setProperty(name, value) {this[name] = value;}};
        Object.defineProperty(this.style, "cssText", {set(value) {
            for (const part of value.split(";")) {
                const [key, ...rest] = part.split(":");
                if (key.trim()) this[key.trim()] = rest.join(":").trim();
            }
        }});
        const classes = new Set();
        this.classList = {add: name => classes.add(name), remove: name => classes.delete(name),
            toggle: (name, enabled) => enabled ? classes.add(name) : classes.delete(name)};
    }
    get textContent() {return (this.text || "") + this.children.map(n => n.textContent).join("");}
    set textContent(value) {this.replaceChildren(); this.text = value;}
    get options() {return this.children;}
    setAttribute(name, value) {this.attributes[name] = value;}
    removeAttribute(name) {delete this.attributes[name];}
    remove() {
        if (this.parentElement) this.parentElement.children = this.parentElement.children.filter(n => n !== this);
        this.parentElement = null;
    }
    append(...nodes) {for (const node of nodes) {node.remove(); node.parentElement = this; this.children.push(node);}}
    replaceChildren(...nodes) {for (const node of [...this.children]) node.remove(); this.append(...nodes);}
    after(...nodes) {
        const parent = this.parentElement;
        for (const node of nodes) node.remove();
        parent.children.splice(parent.children.indexOf(this) + 1, 0, ...nodes);
        for (const node of nodes) node.parentElement = parent;
    }
    addEventListener(type, handler) {(this.handlers[type] ||= []).push(handler);}
    async fire(type, data = {}) {
        await Promise.all((this.handlers[type] || []).map(handler => handler({
            target: this, preventDefault() {}, stopPropagation() {}, stopImmediatePropagation() {}, ...data,
        })));
    }
    click() {return this.fire("click");}
    contains(node) {return this === node || this.children.some(child => child.contains(node));}
    focus() {this.ownerDocument.activeElement = this;}
    scrollIntoView(options) {this.scrollRequest = options;}
    getBoundingClientRect() {return {left: 100, top: 50, width: 850, height: 700};}
}

function setup(libraryIDs = [7, 8]) {
    const doc = {
        createElementNS(_ns, tag) {return new Node(doc, tag);},
        getElementById(id) {
            const find = node => node.id === id ? node : node.children.map(find).find(Boolean);
            return find(doc.documentElement) || null;
        },
        handlers: {},
        addEventListener: Node.prototype.addEventListener,
        removeEventListener(type, handler) {
            this.handlers[type] = (this.handlers[type] || []).filter(entry => entry !== handler);
        },
        fire: Node.prototype.fire,
        querySelectorAll: () => [], querySelector: () => null,
    };
    doc.documentElement = new Node(doc, "html");
    const win = {document: doc, requestAnimationFrame: callback => callback(),
        getComputedStyle: () => ({opacity: "1"})};
    doc.defaultView = win;
    const pending = [];
    const errors = [];
    const prefWrites = [];
    const settingsWrites = [];
    const embeddingWrites = [], confirmations = [], evidenceWrites = [], evidenceReplies = [], openedURLs = [];
    const modelRequests = [], modelReplies = [], relevanceRequests = [], relevanceReplies = [];
    let holdRelevance = false;
    const chatJobs = new Map(), chatReplies = [];
    let savedSettings = {provider:"none", model:"", has_key:false, agentic_enabled:true, agentic_max_steps:3, show_ai_activity:true};
    const positionRequests = [], readerOpens = [], readerNavigation = [];
    let confirmAnswer = false;
    const embedding = {models:[{id:"intfloat/multilingual-e5-small",label:"E5 Small",de:"100 Sprachen",en:"100 languages"},
        {id:"sentence-transformers/all-MiniLM-L6-v2",label:"English MiniLM",de:"Englisch, wenig Rechenbedarf",en:"English, low computation",
         dimensions:384,url:"https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2"}],
        active_model:"intfloat/multilingual-e5-small",job:{state:"idle"}};
    win.confirm = message => { confirmations.push(message); return confirmAnswer; };
    const libraries = libraryIDs.map(libraryID => ({libraryID, name: "Library " + libraryID}));
    const pdfItem = key => ({id:key === "PDF" ? 99 : 100,key,libraryID:7,isAttachment:()=>true,isRegularItem:()=>false,
        attachmentContentType:"application/pdf"});
    const collectionItems = new Map([[99,pdfItem("PDF")],[100,pdfItem("CHILD")]]);
    const parent = {libraryID:7,isAttachment:()=>false,isRegularItem:()=>true,getAttachments:()=>[99]};
    const collections = [{id:10,libraryID:7,name:"ML",level:0,getChildItems:()=>[parent]},
        {id:11,libraryID:7,name:"Vision",level:1,getChildItems:()=>[collectionItems.get(100)]},
        {id:12,libraryID:7,name:"Empty",level:0,getChildItems:()=>[]},
        {id:20,libraryID:8,name:"Other library",level:0,getChildItems:()=>[]}];
    const context = vm.createContext({setTimeout: callback => callback(), clearTimeout() {}, Zotero: {
        locale: "de-DE", getMainWindow: () => win, getMainWindows: () => [win], getActiveZoteroPane: () => null,
        Libraries: {userLibraryID: 7, getAll: () => libraries, get: id => libraries.find(l => l.libraryID === id)},
        Collections: {getByLibrary:id=>collections.filter(c=>c.libraryID===id),
            getByParent:id=>id===10 ? [collections[1]] : [],get:id=>collections.find(c=>c.id===id)},
        Styles: {getVisible: () => []}, Prefs: {get() {}, set: (...args) => prefWrites.push(args)},
        logError: error => errors.push(error),
        launchURL: url => openedURLs.push(url),
        Items: {get:id=>collectionItems.get(id),getAll:async id=>[...collectionItems.values()].filter(item=>item.libraryID===id),
            getByLibraryAndKey: (_library, key) => [...collectionItems.values()].find(item=>item.key===key) || null},
        Reader: {open:async (id, location) => {
            readerOpens.push({id,location});
            return {_initPromise:Promise.resolve(),navigate:async destination => readerNavigation.push(destination)};
        }},
        HTTP: {request: async (_method, url, options) => {
            if (url.endsWith("/document-relevance")) {
                let data = JSON.parse(options.body);
                let documents = data.attachment_keys.map((key,i)=>({library_id:data.library_id,attachment_key:key,
                    title:"Document " + key,similarity:1 - i * .5,category:i ? "lowest" : "highest",page:i + 1}));
                let result = relevanceReplies.shift() || {query:data.query,documents,total_documents:documents.length,
                    scored_documents:documents.length,categories:[{id:"highest",count:documents.length ? 1 : 0,percentage:documents.length ? 100/documents.length : 0},
                        {id:"lowest",count:Math.max(0,documents.length-1),percentage:documents.length > 1 ? 50 : 0}]};
                let record = {data};
                relevanceRequests.push(record);
                if (holdRelevance) return new Promise((resolve,reject)=>{record.resolve=value=>resolve({responseText:JSON.stringify(value || result)});record.reject=reject;});
                return {responseText:JSON.stringify(result)};
            }
            if (url.endsWith("/quote-position")) return new Promise(resolve => {
                positionRequests.push({data:JSON.parse(options.body),
                    resolve:value => resolve({responseText:JSON.stringify(value)})});
            });
            if (url.endsWith("/models")) {
                const data = JSON.parse(options.body);
                modelRequests.push(data);
                const listing = modelReplies.shift() || (data.provider === "ollama"
                    ? {source:"installed", models:[{id:"gemma3:4b",label:"gemma3:4b"}]}
                    : data.provider === "openai" ? {source:"suggestions",reason:"no_key",models:[{id:"gpt-4.1-mini",label:"GPT-4.1 Mini"},{id:"gpt-4.1",label:"GPT-4.1"}]}
                    : data.provider === "anthropic" ? {source:"suggestions",reason:"no_key",models:[{id:"claude-sonnet-5-5",label:"Claude Sonnet 5.5"},{id:"claude-opus-5-5",label:"Claude Opus 5.5"}]}
                    : {source:"provider", models:[{id:"deepseek-flash",label:"DeepSeek Flash (deepseek-flash)"},
                        {id:"deepseek-v4-pro",label:"DeepSeek V4 Pro (deepseek-v4-pro)"}]});
                return {responseText:JSON.stringify(listing)};
            }
            if (url.endsWith("/embedding-models")) return {responseText:JSON.stringify(embedding)};
            if (url.endsWith("/embedding/rebuild")) {
                let data = JSON.parse(options.body);
                embeddingWrites.push(data);
                if (data.custom_model) {
                    let id = data.custom_model.id.replace("https://huggingface.co/", "").replace(/\/$/, "");
                    embedding.models.push({...data.custom_model,id,custom:true,label:id,dimensions:384,
                        de:"Eigenes Hugging-Face-Modell",en:"Custom Hugging Face model",url:"https://huggingface.co/"+id});
                    embedding.active_model = id;
                    embedding.active_signature = id + ":" + data.custom_model.input_format;
                } else embedding.active_model = data.model;
                embedding.job = {state:"complete",model:embedding.active_model,completed:2,total:2};
                return {responseText:JSON.stringify(embedding)};
            }
            if (url.endsWith("/evidence/start")) {
                evidenceWrites.push(JSON.parse(options.body));
                return {responseText:'{"job_id":"test-job"}'};
            }
            if (url.endsWith("/evidence/status")) return {responseText:JSON.stringify(evidenceReplies.shift())};
            if (url.endsWith("/evidence/cancel")) return {responseText:'{"state":"cancelled"}'};
            if (url.endsWith("/chat/start")) {
                let id = "chat-" + chatJobs.size;
                let finish;
                let ready = new Promise(resolve => {finish = resolve;});
                chatJobs.set(id, {ready});
                pending.push({url, data:JSON.parse(options.body),
                    resolve:result => finish({state:"complete",activity:result.activity || [],result}),
                    reject:error => finish({state:"failed",error:error.message})});
                return {responseText:JSON.stringify({job_id:id})};
            }
            if (url.endsWith("/chat/status")) {
                let job = chatReplies.length ? chatReplies.shift() : await chatJobs.get(JSON.parse(options.body).job_id).ready;
                return {responseText:JSON.stringify(job)};
            }
            if (url.endsWith("/chat/cancel")) return {responseText:'{"state":"cancelled"}'};
            if (url.endsWith("/chat-search") || url.endsWith("/search")) return new Promise((resolve, reject) => {
                pending.push({url, data: JSON.parse(options.body),
                    resolve: result => resolve({responseText: JSON.stringify(result)}), reject});
            });
            if (url.endsWith("/settings")) {
                if (_method === "POST") {
                    let changes = JSON.parse(options.body);
                    settingsWrites.push(changes);
                    savedSettings = {...savedSettings,...changes};
                }
                return {responseText: JSON.stringify(savedSettings)};
            }
            return {responseText: JSON.stringify(url.endsWith("/health") ? {ok: true, models_cached: true}
                : url.includes("/status") ? {documents: 1, chunks: 2, topic_documents: 1} : {results: []})};
        }},
    }});
    vm.runInContext(fs.readFileSync("plugin/bootstrap.js", "utf8"), context);
    return {doc, context, pending, chatReplies, errors, prefWrites, settingsWrites, embeddingWrites, confirmations, evidenceWrites, evidenceReplies, openedURLs, modelRequests, modelReplies,
        positionRequests, readerOpens, readerNavigation, relevanceRequests, relevanceReplies, embedding,
        holdRelevance: value => {holdRelevance = value;},
        confirm: value => {confirmAnswer = value;},
        open: (id = 7, tab = "chat") => vm.runInContext(`openSearchWindow(${id}, "${tab}")`, context),
        node: id => doc.getElementById("zqs-" + id),
    };
}

const hit = (quote, library = 7) => ({library_id: library, quote, title: "Paper", page: 2,
    item_key: "PARENT", attachment_key: "PDF"});
const response = (quote, extra = {}) => ({reply: "Antwort mit Beleg [1]", used_ai: true,
    queries: {en: "evidence of overfitting"}, results: [hit(quote)], search_id: "search-1",
    next_offset: 1, has_more: true, ...extra});
const flush = async () => {for (let i = 0; i < 8; i++) await Promise.resolve();};

function previewHTML(doc) {
    const escape = text => String(text ?? "").replace(/[&<>\"]/g, c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"})[c]);
    const serialize = node => {
        const attrs = {...node.attributes};
        if (node.id) attrs.id = node.id;
        const styles = Object.entries(node.style).filter(([,v])=>typeof v!=="function")
            .map(([k,v])=>k.replace(/[A-Z]/g,c=>"-"+c.toLowerCase())+":"+v).join(";");
        if (styles) attrs.style = styles;
        if (node.disabled) attrs.disabled = "disabled";
        if (node.tag === "input") attrs.value = node.value;
        if (node.tag === "details" && node.open) attrs.open = "open";
        const content = escape(node.tag === "textarea" ? node.value : node.text) + node.children.map(serialize).join("");
        return `<${node.tag} ${Object.entries(attrs).map(([k,v])=>k+'="'+escape(v)+'"').join(" ")}>${content}</${node.tag}>`;
    };
    return '<!doctype html><html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Zitatlotse – Darstellungsprüfung</title></head><body style="margin:0;background:#e8e8ed">'+doc.documentElement.children.map(serialize).join("")+'</body></html>';
}

(async () => {
    const app = setup();
    app.open();
    app.node("chat-input").value = "Belege für Overfitting?";
    await app.node("chat-input").fire("input");
    let job = app.node("chat-send").click();
    await flush();
    app.pending.shift().resolve(response("Erster Beleg"));
    await job;
    assert.match(app.node("chat-history").textContent, /Belege für Overfitting.*Antwort mit Beleg/s);
    job = app.node("chat-next").click();
    await flush();
    assert.equal(app.pending[0].data.offset, 1);
    app.pending.shift().resolve(response("Zweiter Beleg", {next_offset: 2, has_more: false}));
    await job;
    app.node("chat-input").value = "Noch nicht gesendete Frage";
    await app.node("chat-input").fire("input");
    const oldPanel = app.node("panel");
    await app.node("close").click();
    assert.equal(app.node("overlay"), null);
    app.open();
    assert.notEqual(app.node("panel"), oldPanel, "A recreated window must restore the session");
    assert.match(app.node("chat-history").textContent, /Antwort mit Beleg/);
    assert.match(app.node("chat-results").textContent, /Zweiter Beleg/);
    assert.doesNotMatch(app.node("chat-results").textContent, /Erster Beleg/);
    assert.equal(app.node("chat-input").value, "Noch nicht gesendete Frage");
    assert.equal(app.node("chat-page-2").attributes["aria-current"], "page");
    await app.node("chat-page-1").click();
    assert.match(app.node("chat-results").textContent, /Erster Beleg/);

    // Closing while AI is running must preserve its eventual reply and progress.
    job = app.node("chat-send").click();
    await flush();
    const waitingChat = app.pending.shift();
    assert.equal(waitingChat.data.history.length, 2, "The follow-up receives the preserved conversation");
    await app.node("chat-input").fire("keydown", {key: "Enter"});
    assert.equal(app.pending.length, 0, "Enter cannot start a duplicate request while busy");
    await app.node("close").click();
    app.open();
    assert.equal(app.node("chat-send").disabled, true);
    waitingChat.resolve(response("Später eingetroffener Beleg"));
    await job;
    assert.match(app.node("chat-results").textContent, /Später eingetroffener Beleg/);
    assert.equal(app.node("chat-send").disabled, false);

    // Each library owns its own drafts, conversation and results.
    app.open(8);
    assert.equal(app.node("chat-history").textContent, "");
    assert.doesNotMatch(app.node("chat-results").textContent, /Beleg/);
    app.node("chat-input").value = "Frage in Bibliothek 8";
    await app.node("chat-input").fire("input");
    job = app.node("chat-send").click();
    await flush();
    const libraryEightChat = app.pending.shift();
    assert.equal(libraryEightChat.data.library_id, 8);
    app.open(7);
    libraryEightChat.resolve(response("Beleg aus Bibliothek 8", {results: [hit("Beleg aus Bibliothek 8", 8)]}));
    await job;
    assert.doesNotMatch(app.node("chat-results").textContent, /Bibliothek 8/);
    app.open(8);
    assert.match(app.node("chat-results").textContent, /Beleg aus Bibliothek 8/);
    app.open(7, "search");

    app.node("search-input").value = "MAE";
    await app.node("search-input").fire("input");
    job = app.node("search-send").click();
    await flush();
    app.pending.shift().resolve(response("MAE Fundstelle"));
    await job;
    await app.node("close").click();
    app.open(7, "search");
    assert.equal(app.node("search-input").value, "MAE");
    assert.match(app.node("search-results").textContent, /MAE Fundstelle/);
    assert.equal(app.node("direct-next").disabled, false);
    job = app.node("direct-next").click();
    await flush();
    app.pending.shift().resolve(response("Zweite MAE Fundstelle", {next_offset: 2, has_more: false}));
    await job;
    await app.node("close").click();
    app.open(7, "search");
    assert.match(app.node("search-results").textContent, /Zweite MAE Fundstelle/);
    await app.node("direct-page-1").click();
    assert.doesNotMatch(app.node("search-results").textContent, /Zweite MAE Fundstelle/);
    app.open(8, "search");
    assert.equal(app.node("search-input").value, "");
    assert.doesNotMatch(app.node("search-results").textContent, /MAE Fundstelle/);
    app.open(7, "search");

    // Reset while a request is running must not let the old result reappear.
    job = app.node("search-send").click();
    await flush();
    const oldDirect = app.pending.shift();
    await app.node("search-reset").click();
    assert.equal(app.node("search-input").value, "");
    assert.equal(app.node("search-send").disabled, false);
    oldDirect.resolve(response("Veralteter direkter Treffer"));
    await job;
    assert.doesNotMatch(app.node("search-results").textContent, /Veralteter|MAE Fundstelle/);
    await app.node("close").click();
    app.open(7, "search");
    assert.equal(app.node("search-input").value, "");
    app.open(7, "chat");
    assert.match(app.node("chat-history").textContent, /Belege für Overfitting/,
        "Resetting direct search leaves the AI chat intact");
    app.node("chat-input").value = "Neue Anfrage";
    job = app.node("chat-send").click();
    await flush();
    const oldChat = app.pending.shift();
    await app.node("chat-reset").click();
    app.node("chat-input").value = "Nach dem Reset";
    const newJob = app.node("chat-send").click();
    await flush();
    const newChat = app.pending.shift();
    assert.equal(newChat.data.history.length, 0, "Reset clears the history sent to AI");
    oldChat.resolve(response("Veraltete Antwort"));
    await job;
    assert.equal(app.node("chat-send").disabled, true, "Old replies cannot end a newer search's progress");
    newChat.resolve(response("Aktueller Beleg"));
    await newJob;
    assert.doesNotMatch(app.node("chat-results").textContent, /Veraltete/);
    assert.match(app.node("chat-history").textContent, /Nach dem Reset/);
    assert.doesNotMatch(app.node("chat-history").textContent, /Belege für Overfitting/);
    await app.node("chat-reset").click();
    await app.node("close").click();
    app.open();
    assert.equal(app.node("chat-history").textContent, "");
    app.open(8);
    assert.match(app.node("chat-history").textContent, /Frage in Bibliothek 8/,
        "Resetting one library leaves the other library intact");
    app.open(8, "search");
    app.node("search-input").value = "Noch vorhandene direkte Suche";
    await app.node("search-input").fire("input");
    job = app.node("search-send").click();
    await flush();
    app.pending.shift().resolve(response("Direkter Beleg aus Bibliothek 8", {
        results: [hit("Direkter Beleg aus Bibliothek 8", 8)]}));
    await job;

    // Zotero shutdown releases all library sessions; no history is persisted in prefs.
    vm.runInContext("shutdown()", app.context);
    app.open(8);
    assert.equal(app.node("chat-history").textContent, "");
    assert.equal(app.node("chat-input").value, "");
    app.open(8, "search");
    assert.equal(app.node("search-input").value, "");
    assert.doesNotMatch(app.node("search-results").textContent, /Direkter Beleg aus Bibliothek 8/);
    assert.equal(app.prefWrites.length, 0);
    assert.equal(app.errors.length, 0);
    // Default AI selection, all-results checkbox, numbered pages and cached navigation.
    app.open(7);
    app.node("chat-input").value = "Vergleiche die Studien";
    job = app.node("chat-send").click();
    await flush();
    const firstHits = Array.from({length:20}, (_, index) => ({...hit("Quelle " + (index + 1)),
        recommended:index === 1 || index === 4, reference_number:index + 1}));
    app.pending.shift().resolve(response("", {results:firstHits, reviewed:true, total_results:47, next_offset:20}));
    await job;
    assert.match(app.node("chat-results").textContent, /„Quelle 2“/);
    assert.match(app.node("chat-results").textContent, /„Quelle 5“/);
    assert.doesNotMatch(app.node("chat-results").textContent, /„Quelle 1“/);
    assert.equal(app.node("chat-show-all").checked, false);
    assert.equal(app.node("chat-pagination").style.display, "none");
    app.node("chat-show-all").checked = true;
    await app.node("chat-show-all").fire("change");
    assert.match(app.node("chat-results").textContent, /„Quelle 1“/);
    assert.ok(app.node("chat-page-3"), "Known result totals expose every page immediately");
    job = app.node("chat-page-3").click();
    await flush();
    assert.equal(app.pending[0].data.offset, 40);
    app.pending.shift().resolve(response("", {results:Array.from({length:7}, (_, index) => hit("Quelle " + (41 + index))),
        total_results:47, next_offset:47, has_more:false}));
    await job;
    assert.match(app.node("chat-results").textContent, /Quelle 47/);
    assert.equal(app.node("chat-next").disabled, true);
    await app.node("close").click();
    app.open();
    assert.equal(app.node("chat-show-all").checked, true);
    assert.equal(app.node("chat-page-3").attributes["aria-current"], "page");
    await app.node("chat-page-1").click();
    assert.equal(app.pending.length, 0, "Cached pages need no network request");
    app.node("chat-show-all").checked = false;
    await app.node("chat-show-all").fire("change");
    assert.doesNotMatch(app.node("chat-results").textContent, /„Quelle 1“|Quelle 47/);
    assert.match(app.node("chat-results").textContent, /„Quelle 2“/);
    // More than one page of selected sources from several agent search calls.
    app.node("chat-input").value = "Mehrere Aspekte";
    job = app.node("chat-send").click();
    await flush();
    const selected = Array.from({length:25}, (_, index) => ({...hit("Auswahl " + (index + 1)), recommended:true}));
    app.pending.shift().resolve(response("", {results:selected.slice(0,20), selected_results:selected,
        total_results:60, next_offset:20, reviewed:true}));
    await job;
    await app.node("chat-page-2").click();
    assert.match(app.node("chat-results").textContent, /Auswahl 25/);
    assert.doesNotMatch(app.node("chat-results").textContent, /„Auswahl 1“/);
    assert.equal(app.pending.length, 0, "Selected source pagination is local");
    // The preferences toggle saves only agent options, preserving provider credentials.
    app.open(7, "preferences");
    await flush();
    assert.equal(app.node("agent-enabled").checked, true);
    app.node("agent-enabled").checked = false;
    await app.node("agent-enabled").fire("change");
    assert.equal(app.node("agent-steps").disabled, true);
    await app.node("agent-save").click();
    assert.deepEqual(app.settingsWrites.at(-1), {agentic_enabled:false, agentic_max_steps:3});
    // Choosing a new embedding model must ask before any mutation, and cancel restores selection.
    assert.match(app.node("embedding-description").textContent, /100 Sprachen/);
    assert.match(app.node("embedding-language-hint").textContent,/alle Sprachen der durchsuchten Dokumente/);
    app.node("embedding-model").value = "sentence-transformers/all-MiniLM-L6-v2";
    await app.node("embedding-model").fire("change");
    assert.equal(app.embeddingWrites.length, 0);
    assert.equal(app.node("embedding-model").value, "intfloat/multilingual-e5-small");
    app.confirm(true);
    app.node("embedding-model").value = "sentence-transformers/all-MiniLM-L6-v2";
    await app.node("embedding-model").fire("change");
    assert.deepEqual(app.embeddingWrites.at(-1), {model:"sentence-transformers/all-MiniLM-L6-v2",confirmed:true});
    assert.match(app.node("embedding-description").textContent, /Englisch/);
    assert.match(app.node("embedding-description").textContent, /384 Dimensionen/);
    await app.node("embedding-details").click();
    assert.equal(app.openedURLs.at(-1), "https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2");
    assert.match(app.confirmations[0], /alle.*Bibliotheken/s);
    app.node("custom-repo").value = "https://huggingface.co/acme/text-encoder";
    app.node("custom-profile").value = "custom";
    await app.node("custom-profile").fire("change");
    app.node("custom-query-prefix").value = "Question: ";
    app.node("custom-passage-prefix").value = "Passage: ";
    app.node("custom-revision").value = "main";
    app.node("custom-batch").value = "4";
    const oldWrites = app.embeddingWrites.length;
    app.confirm(false);
    await app.node("custom-load").click();
    assert.equal(app.embeddingWrites.length, oldWrites, "Cancelling never changes the database or starts downloads");
    app.confirm(true);
    await app.node("custom-load").click();
    assert.deepEqual(app.embeddingWrites.at(-1), {confirmed:true,custom_model:{id:"https://huggingface.co/acme/text-encoder",
        input_format:"custom",revision:"main",batch_size:4,query_prefix:"Question: ",passage_prefix:"Passage: "}});
    assert.equal(app.node("embedding-model").value, "acme/text-encoder");
    assert.match(app.node("embedding-description").textContent, /Eigenes Hugging-Face/);
    assert.equal(app.node("custom-load").disabled, false);
    await app.node("custom-edit").click();
    assert.equal(app.node("custom-repo").value, "acme/text-encoder");
    assert.equal(app.node("custom-query-prefix").value, "Question: ");
    assert.equal(app.node("custom-embedding").open, true);
    // Evidence mode, grouped original quotes, balance and retained window state.
    app.open(7, "chat");
    app.node("chat-mode").value = "evidence";
    await app.node("chat-mode").fire("change");
    app.node("chat-input").value = "Das Modell overfittet.";
    const assessed = Array.from({length:11}, (_, i) => ({...hit("Original " + (i + 1)),
        stance:i < 6 ? "pro" : i < 10 ? "contra" : "neutral",recommended:i < 10,point:"Bewertung",reason:"Begründung"}));
    app.evidenceReplies.push({state:"running",phase:"reviewing",completed:8,total:11}, {state:"complete",result:response("", {
        results:assessed,selected_results:assessed.slice(0,10),reviewed:true,total_results:11,has_more:false,
        evidence:{pro:6,contra:4,neutral:1,total:11,pro_percent:60,contra_percent:40}})});
    await app.node("chat-send").click();
    assert.equal(app.evidenceWrites.at(-1).mode, "evidence");
    assert.match(app.node("evidence-pro").textContent, /Original 1/);
    assert.match(app.node("evidence-contra").textContent, /Original 10/);
    assert.equal(app.node("evidence-neutral"), null);
    assert.equal(app.node("evidence-bar").children[0].style.width, "60%");
    assert.equal(app.node("evidence-bar").children[1].style.width, "40%");
    await app.node("close").click();
    app.open(7);
    assert.equal(app.node("chat-mode").value, "evidence");
    assert.match(app.node("evidence-balance").textContent, /60%.*40%/s);
    app.node("chat-show-all").checked = true;
    await app.node("chat-show-all").fire("change");
    assert.match(app.node("evidence-neutral").textContent, /Original 11/);
    await app.node("chat-reset").click();
    assert.equal(app.node("evidence-bar"), null);
    app.context.Zotero.locale = "en-US";
    await app.node("close").click();
    app.open(7, "preferences");
    await flush();
    assert.match(app.node("panel").textContent, /AI search/);
    assert.doesNotMatch(app.node("panel").textContent, /Open AI search/);
    assert.match(app.node("embedding-description").textContent, /Custom Hugging Face model/);
    const modelApp = setup();
    modelApp.open(7, "connections");
    await flush();
    modelApp.node("provider").value = "deepseek";
    await modelApp.node("provider").fire("change");
    await flush();
    assert.match(modelApp.node("llm-model-options").textContent, /DeepSeek V4 Pro/);
    modelApp.node("llm-model-options").value = "deepseek-v4-pro";
    await modelApp.node("llm-model-options").fire("change");
    assert.equal(modelApp.node("llm-model").value, "deepseek-v4-pro");
    const requestsBeforeKey = modelApp.modelRequests.length;
    modelApp.node("api-key").value = "dummy-new-key";
    await modelApp.node("api-key").fire("change");
    await flush();
    assert.equal(modelApp.modelRequests.length, requestsBeforeKey + 1, "A newly inserted key reloads the live model list");
    assert.equal(modelApp.modelRequests.at(-1).api_key, "dummy-new-key");
    await modelApp.node("model-refresh").click();
    assert.equal(modelApp.modelRequests.length, requestsBeforeKey + 2);
    modelApp.node("provider").value = "ollama";
    await modelApp.node("provider").fire("change");
    await flush();
    assert.match(modelApp.node("llm-model-options").textContent, /gemma3:4b/);
    assert.doesNotMatch(modelApp.node("llm-model-options").textContent, /DeepSeek/);
    assert.match(modelApp.node("llm-model-info").textContent, /lokal installiertes Modell/);
    for (const [provider, id, label] of [["openai","gpt-4.1-mini","GPT-4.1 Mini"], ["anthropic","claude-sonnet-5-5","Claude Sonnet 5.5"]]) {
        modelApp.node("provider").value = provider;
        await modelApp.node("provider").fire("change");
        await flush();
        assert.match(modelApp.node("llm-model-options").textContent, new RegExp(label));
        assert.match(modelApp.node("llm-model-info").textContent, /Modellvorschläge.*nicht geprüft/);
        modelApp.node("llm-model-options").value = id;
        await modelApp.node("llm-model-options").fire("change");
        assert.equal(modelApp.node("llm-model").value, id);
        const actual = provider + "-future-text-model";
        modelApp.modelReplies.push({source:"api",models:[{id:actual,label:"Actual API model"}]});
        modelApp.node("api-key").value = "dummy-" + provider;
        await modelApp.node("api-key").fire("change");
        await flush();
        assert.match(modelApp.node("llm-model-info").textContent, /vom Anbieter abgerufen/);
        modelApp.node("llm-model-options").value = actual;
        await modelApp.node("llm-model-options").fire("change");
        assert.equal(modelApp.node("llm-model").value, actual);
        modelApp.modelReplies.push({source:"api",models:[]});
        await modelApp.node("model-refresh").click();
        assert.match(modelApp.node("llm-model-info").textContent, /Modellvorschläge/);
        assert.ok(modelApp.node("llm-model-options").children.length >= 4);
        assert.equal(modelApp.node("llm-model").value, actual, "Refreshing suggestions retains a manual model ID");
    }
    modelApp.open(7, "chat");
    assert.equal(modelApp.node("chat-tab").style.background, "#e6dcff");
    assert.equal(modelApp.node("header").style.background, "#5b36bf");
    assert.equal(modelApp.node("chat-card").style.background, "white");
    assert.equal(modelApp.node("chat-card").style.border, "2px solid #0f766e");
    assert.equal(modelApp.node("chat-send").style.background, "#5b36bf");
    assert.equal(modelApp.node("chat-input").style.border, "1px solid #bfbaca");
    const pdfApp = setup();
    pdfApp.open(7, "search");
    pdfApp.node("search-input").value = "patch size";
    const pdfSearch = pdfApp.node("search-send").click();
    await flush();
    pdfApp.pending.shift().resolve(response("Smaller patches improve feature quality."));
    await pdfSearch;
    const findOpenButton = node => node.tag === "button" && node.textContent === "Im PDF öffnen" ? node
        : node.children.map(findOpenButton).find(Boolean);
    const pdfOpening = findOpenButton(pdfApp.node("search-results")).click();
    for (let count = 0; count < 25 && !pdfApp.positionRequests.length; count++) await Promise.resolve();
    assert.equal(pdfApp.readerOpens[0].location.pageIndex, 1);
    assert.equal(pdfApp.node("overlay"), null, "The actual Open in PDF handler closes the overlay while position lookup is still pending");
    pdfApp.positionRequests[0].resolve({position:{pageIndex:1,rects:[[10,20,30,40]]}});
    await pdfOpening;
    assert.deepEqual(JSON.parse(JSON.stringify(pdfApp.readerNavigation[0])), {position:{pageIndex:1,rects:[[10,20,30,40]]}});
    assert.equal(pdfApp.errors.length, 0);
    const averageApp = setup();
    averageApp.open(7, "search");
    averageApp.node("search-input").value = "Average";
    const averageSearch = averageApp.node("search-send").click();
    await flush();
    assert.match(averageApp.pending[0].url, /\/search$/);
    assert.equal(averageApp.pending[0].data.library_id, 7);
    assert.equal(averageApp.pending[0].data.query, "Average");
    averageApp.pending.shift().resolve(response("", {results:Array.from({length:20},(_,i)=>
        ({...hit("Average error " + i),match_type:"literal",recommended:false})),
        reviewed:true,selected_results:[],total_results:44,next_offset:20,has_more:true}));
    await averageSearch;
    assert.match(averageApp.node("search-results").textContent, /Average error 19/,
        "Direct search shows word matches regardless of the AI-selection filter");
    assert.match(averageApp.node("panel").textContent, /44 Fundstellen in dieser Bibliothek gefunden/);
    assert.ok(averageApp.node("direct-page-3"), "Every page of direct word matches remains accessible");
    // Native selects use detached Firefox/XUL popups. Their click targets may
    // become the document rather than a descendant of the HTML search shell.
    const popupApp = setup();
    popupApp.open();
    await flush();
    const dropdown = popupApp.node("chat-mode");
    dropdown.focus();
    const popupOption = new Node(popupApp.doc, "menuitem");
    await popupApp.doc.fire("pointerdown", {target:popupOption, button:0, clientX:990, clientY:60});
    await popupApp.doc.fire("click", {target:popupApp.doc.documentElement});
    assert.ok(popupApp.node("overlay"), "Opening the evidence dropdown must keep the window open");
    dropdown.value = "evidence";
    await dropdown.fire("change");
    await popupApp.doc.fire("keydown", {target:dropdown, key:"Escape"});
    assert.ok(popupApp.node("overlay"), "Escape dismisses the native dropdown without closing its window");
    assert.equal(popupApp.node("chat-mode").value, "evidence");
    popupApp.open(7, "preferences");
    await flush();
    const modelSelect = popupApp.node("embedding-model");
    modelSelect.focus();
    await popupApp.doc.fire("pointerdown", {target:popupApp.doc.documentElement, button:0});
    modelSelect.value = "sentence-transformers/all-MiniLM-L6-v2";
    popupApp.confirm(true);
    await modelSelect.fire("change");
    // Focus can change during the native confirmation, then a trailing click
    // from the original select popup arrives on the document or another node.
    popupApp.doc.activeElement = null;
    await popupApp.doc.fire("click", {target:popupOption});
    assert.ok(popupApp.node("overlay"), "Model selection and confirmation must keep the window open");
    assert.equal(popupApp.embeddingWrites.length, 1);
    await popupApp.doc.fire("pointerdown", {target:popupOption, button:0});
    assert.ok(popupApp.node("overlay"), "Detached XUL menu items cannot dismiss the window");
    const outside = new Node(popupApp.doc, "button");
    popupApp.doc.documentElement.append(outside);
    // Retargeted popup events physically inside the window are also protected.
    await popupApp.doc.fire("pointerdown", {target:outside, button:0, clientX:400, clientY:200});
    assert.ok(popupApp.node("overlay"));
    outside.focus();
    await popupApp.doc.fire("pointerdown", {target:outside, button:0, clientX:20, clientY:20});
    assert.equal(popupApp.node("overlay"), null, "An actual outside press still closes the window");
    assert.equal(popupApp.doc.handlers.pointerdown.length, 0, "Dismissal removes document pointer handlers");
    assert.equal(popupApp.doc.handlers.keydown.length, 0, "Dismissal removes Escape handlers");
    popupApp.open();
    await popupApp.node("close").fire("pointerdown");
    assert.equal(popupApp.node("overlay"), null, "Explicit X closes immediately even with a select focused");
    popupApp.open();
    await popupApp.doc.fire("keydown", {key:"Escape",target:popupApp.node("chat-input")});
    assert.equal(popupApp.node("overlay"), null, "Escape outside a native control closes the window");
    // Live activity survives window closure and its preference is persisted.
    const activityApp = setup();
    activityApp.open();
    await flush();
    const events = [{type:"started",elapsed:0}, {type:"model_call",purpose:"agent",round:1,elapsed:1},
        {type:"tool_call",tool:"search_library",step:1,query:"overfitting evidence",language:"en",elapsed:2},
        {type:"search_results",count:12,elapsed:3}, {type:"model_call",round:2,purpose:"agent",elapsed:4}];
    activityApp.chatReplies.push({state:"running",phase:"searching",activity:events});
    activityApp.node("chat-input").value = "Find overfitting evidence";
    const live = activityApp.node("chat-send").click();
    for (let i = 0; i < 5; i++) await flush();
    assert.match(activityApp.node("ai-activity-list").textContent, /Tool-Aufruf.*overfitting evidence.*Ergebnisse erhalten: 12.*Erneute KI-Anfrage/s);
    activityApp.node("ai-activity").open = false;
    await activityApp.node("ai-activity").fire("toggle");
    await activityApp.node("close").click();
    activityApp.open();
    await flush();
    assert.equal(activityApp.node("ai-activity").open, false);
    assert.match(activityApp.node("ai-activity-list").textContent, /overfitting evidence/);
    activityApp.open(7,"preferences");
    await flush();
    activityApp.node("show-ai-activity").checked = false;
    await activityApp.node("show-ai-activity").fire("change");
    assert.deepEqual(activityApp.settingsWrites.at(-1), {show_ai_activity:false});
    assert.equal(activityApp.node("ai-activity").style.display, "none");
    activityApp.pending.shift().resolve(response("Finished evidence", {activity:[...events,{type:"complete",elapsed:5}]}));
    await live;
    await activityApp.node("close").click();
    activityApp.open();
    await flush();
    assert.equal(activityApp.node("ai-activity").style.display, "none", "Saved preference survives reopening");
    activityApp.open(7,"preferences");
    await flush();
    activityApp.node("show-ai-activity").checked = true;
    await activityApp.node("show-ai-activity").fire("change");
    activityApp.open(7,"chat");
    assert.match(activityApp.node("ai-activity-list").textContent, /Suche abgeschlossen/);
    await activityApp.node("chat-reset").click();
    assert.equal(activityApp.node("ai-activity").style.display, "none");
    activityApp.context.Zotero.locale = "en-US";
    assert.equal(vm.runInContext('activityLabel({type:"model_call",round:2})', activityApp.context), "Another AI request · 2");

    // Collection membership is read live, includes child collections, and is
    // carried into direct/chat/evidence searches and every subsequent page.
    const scopeApp = setup();
    scopeApp.open(7,"search");
    await flush();
    assert.match(scopeApp.node("collection").textContent, /Gesamte Bibliothek.*ML.*Vision.*Empty/s);
    assert.doesNotMatch(scopeApp.node("collection").textContent, /Other library/);
    scopeApp.node("collection").value = "10";
    await scopeApp.node("collection").fire("change");
    scopeApp.node("search-input").value = "Average";
    let scoped = scopeApp.node("search-send").click();
    for (let i = 0; i < 4; i++) await flush();
    let searchRequest = scopeApp.pending.shift();
    assert.equal(searchRequest.data.collection_id, 10);
    assert.deepEqual(searchRequest.data.attachment_keys, ["CHILD","PDF"]);
    searchRequest.resolve(response("Collection quote"));
    await scoped;
    scoped = scopeApp.node("direct-next").click();
    await flush();
    searchRequest = scopeApp.pending.shift();
    assert.equal(searchRequest.data.collection_id, 10);
    searchRequest.resolve(response("Next scoped quote", {has_more:false}));
    await scoped;
    await scopeApp.node("close").click();
    scopeApp.open();
    assert.equal(scopeApp.node("collection").value, "10");
    scopeApp.node("chat-input").value = "Question in collection";
    scoped = scopeApp.node("chat-send").click();
    for (let i = 0; i < 4; i++) await flush();
    searchRequest = scopeApp.pending.shift();
    assert.equal(searchRequest.data.collection_id, 10);
    assert.deepEqual(searchRequest.data.attachment_keys, ["CHILD","PDF"]);
    scopeApp.node("collection").value = "12";
    await scopeApp.node("collection").fire("change");
    searchRequest.resolve(response("Old collection response"));
    await scoped;
    assert.doesNotMatch(scopeApp.node("chat-results").textContent, /Old collection/);
    assert.equal(scopeApp.node("chat-history").textContent, "");
    scopeApp.node("chat-mode").value = "evidence";
    await scopeApp.node("chat-mode").fire("change");
    scopeApp.node("chat-input").value = "Claim in empty collection";
    scopeApp.evidenceReplies.push({state:"complete",activity:[{type:"complete"}],result:response("", {
        results:[],has_more:false,total_results:0,evidence:{pro:0,contra:0,neutral:0,total:0},
        activity:[{type:"review_started",count:0},{type:"complete"}]})});
    await scopeApp.node("chat-send").click();
    assert.deepEqual(scopeApp.evidenceWrites.at(-1).attachment_keys, []);
    assert.equal(scopeApp.evidenceWrites.at(-1).collection_id, 12);
    assert.match(scopeApp.node("ai-activity-list").textContent, /Auswertung der Fundstellen gestartet: 0/);
    scopeApp.open(8);
    assert.equal(scopeApp.node("collection").value, "0");
    assert.match(scopeApp.node("collection").textContent, /Other library/);
    scopeApp.open(7);
    assert.equal(scopeApp.node("collection").value, "12");
    assert.equal(scopeApp.errors.length, 0);
    // The overview uses the current question and all PDFs in the live scope,
    // independently of quote selection. Closing retains it; reset invalidates it.
    const overviewApp = setup();
    overviewApp.open(7, "search");
    assert.equal(overviewApp.node("chat-history").style["padding-right"], "14px");
    assert.equal(overviewApp.node("chat-history").style["scrollbar-gutter"], "stable");
    overviewApp.node("search-input").value = "Average";
    let overviewJob = overviewApp.node("search-send").click();
    await flush();
    overviewApp.pending.shift().resolve(response("A quote", {has_more:false,total_results:1}));
    await overviewJob;
    for (let i=0; i<3; i++) await flush();
    assert.equal(overviewApp.relevanceRequests[0].data.query,"Average");
    assert.deepEqual(overviewApp.relevanceRequests[0].data.attachment_keys,["CHILD","PDF"]);
    assert.match(overviewApp.node("direct-relevance").textContent,/Geschätzte Dokumentrelevanz.*Average/s);
    assert.deepEqual(overviewApp.relevanceRequests[0].data.language_queries,{});
    assert.match(overviewApp.node("direct-relevance-documents").textContent,/Document CHILD.*Document PDF/s);
    await overviewApp.node("direct-relevance-lowest").click();
    assert.doesNotMatch(overviewApp.node("direct-relevance-documents").textContent,/Document CHILD/);
    assert.match(overviewApp.node("direct-relevance-documents").textContent,/Document PDF/);
    await overviewApp.node("close").click();
    overviewApp.open(7,"search");
    assert.match(overviewApp.node("direct-relevance-documents").textContent,/Document PDF/);
    const pdfButton = overviewApp.node("direct-relevance-documents").children[0].children[1].children[1];
    await pdfButton.click();
    assert.equal(overviewApp.readerOpens.at(-1).id,99);
    assert.equal(overviewApp.readerOpens.at(-1).location.pageIndex,1);
    overviewApp.open(7,"search");
    await overviewApp.node("search-reset").click();
    assert.equal(overviewApp.node("direct-relevance").style.display,"none");
    overviewApp.node("collection").value = "12";
    await overviewApp.node("collection").fire("change");
    overviewApp.node("search-input").value = "Average";
    overviewJob = overviewApp.node("search-send").click();
    for (let i=0;i<3;i++) await flush();
    overviewApp.pending.shift().resolve(response("", {results:[],has_more:false,total_results:0}));
    await overviewJob;
    for (let i=0;i<3;i++) await flush();
    assert.deepEqual(overviewApp.relevanceRequests.at(-1).data.attachment_keys,[]);
    assert.equal(overviewApp.relevanceRequests.at(-1).data.collection_id,12);
    assert.match(overviewApp.node("direct-relevance").textContent,/Keine PDFs/);

    // Identical attachment groups are rendered once in a category, even after
    // switching categories, paging and reopening the window repeatedly.
    // A classifier's inflated cosine values must not be rendered as a ranking.
    const invalidModelApp = setup();
    invalidModelApp.embedding.active_model = "ProsusAI/finbert";
    invalidModelApp.embedding.active_compatibility = {status:"incompatible",de:"FinBERT ist ein Klassifikationsmodell. Index neu berechnen.",en:"FinBERT is a classifier. Rebuild the index."};
    invalidModelApp.open(7,"search");
    invalidModelApp.relevanceReplies.push({query:"Knowledge distillation",model:"ProsusAI/finbert",
        model_compatibility:invalidModelApp.embedding.active_compatibility,total_documents:2,
        scored_documents:0,documents:[],categories:[]});
    invalidModelApp.node("search-input").value = "Knowledge distillation";
    const invalidSearch = invalidModelApp.node("search-send").click();
    await flush();
    invalidModelApp.pending.shift().resolve(response("",{results:[],has_more:false,total_results:0}));
    await invalidSearch;
    for(let i=0;i<3;i++) await flush();
    assert.match(invalidModelApp.node("direct-relevance-warning").textContent,/Klassifikationsmodell/);
    assert.equal(invalidModelApp.node("direct-relevance-highest"),null);
    const changeModel = invalidModelApp.node("direct-relevance").children.at(-1);
    await changeModel.click();
    assert.equal(invalidModelApp.node("embedding-model").value,"ProsusAI/finbert");
    assert.match(invalidModelApp.node("embedding-status").textContent,/Index neu berechnen/);
    assert.equal(invalidModelApp.embeddingWrites.length,0,"The warning never silently rebuilds the user's database");
    invalidModelApp.context.Zotero.locale = "en-US";
    await invalidModelApp.node("close").click();
    invalidModelApp.open(7,"search");
    assert.match(invalidModelApp.node("direct-relevance-warning").textContent,/FinBERT is a classifier/);
    assert.match(invalidModelApp.node("embedding-language-hint").textContent,/supports all languages/);

    // Reuse one existing AI query per language; never mix languages or send an
    // entire agent trajectory as a second relevance-maximizing query pool.
    const variants = vm.runInContext('documentLanguageQueries({agentic_used:true,languages:{en:2,de:1},agent_steps:[{language:"en",query:"temperature distillation"},{language:"en",query:"another followup"},{language:"de",query:"Distillation Temperatur"},{language:"all",query:"unrelated query"}]})',invalidModelApp.context);
    assert.deepEqual(JSON.parse(JSON.stringify(variants)),{en:"temperature distillation",de:"Distillation Temperatur"});
    assert.deepEqual(JSON.parse(JSON.stringify(vm.runInContext('documentLanguageQueries({queries:{en:"English query",default:"Original question"}})',invalidModelApp.context))),{en:"English query"});

    const groupedApp = setup();
    groupedApp.open(7,"search");
    const groupedDocuments = Array.from({length:7},(_,i)=>({library_id:7,
        attachment_key:i === 0 ? "MISSING_COPY" : "GROUP"+i,
        attachment_keys:i === 0 ? ["MISSING_COPY","PDF"] : ["GROUP"+i],
        duplicate_count:i === 0 ? 3 : 0,title:"Unique document "+i,similarity:.9-i*.01,
        category:"highest",page:2}));
    groupedApp.relevanceReplies.push({query:"Grouped documents",total_documents:7,scored_documents:7,
        total_attachments:10,duplicate_attachments:3,documents:groupedDocuments,
        categories:[{id:"highest",count:7,percentage:100}]});
    groupedApp.node("search-input").value = "Grouped documents";
    const groupedSearch = groupedApp.node("search-send").click();
    await flush();
    groupedApp.pending.shift().resolve(response("Found"));
    await groupedSearch;
    for (let i=0;i<3;i++) await flush();
    assert.match(groupedApp.node("direct-relevance-duplicates").textContent,/10 PDF-Anhänge.*3 identische Kopien/);
    assert.equal(groupedApp.node("direct-relevance-documents").children.length,5);
    for (let repeat=0;repeat<3;repeat++) {
        await groupedApp.node("direct-relevance-highest").click();
        assert.equal(groupedApp.node("direct-relevance-documents").children.length,5);
        assert.equal(groupedApp.node("direct-relevance-documents").textContent.split("Unique document 0").length-1,1);
        await groupedApp.node("direct-relevance-next").click();
        assert.equal(groupedApp.node("direct-relevance-documents").children.length,2);
        assert.doesNotMatch(groupedApp.node("direct-relevance-documents").textContent,/Unique document 0/);
        await groupedApp.node("direct-relevance-all").click();
    }
    await groupedApp.node("close").click();
    groupedApp.open(7,"search");
    assert.equal(groupedApp.node("direct-relevance-documents").children.length,5);
    const groupedPdfButton = groupedApp.node("direct-relevance-documents").children[0].children[1].children[1];
    await groupedPdfButton.click();
    assert.equal(groupedApp.readerOpens.at(-1).id,99,"Use an existing identical copy if the representative no longer exists");
    assert.equal(groupedApp.readerOpens.at(-1).location.pageIndex,1);

    const staleOverview = setup();
    staleOverview.open(7,"search");
    staleOverview.holdRelevance(true);
    staleOverview.node("search-input").value = "Old question";
    let firstOverview = staleOverview.node("search-send").click();
    await flush();
    staleOverview.pending.shift().resolve(response("Old quote"));
    await firstOverview;
    for (let i=0;i<3;i++) await flush();
    staleOverview.node("search-input").value = "New question";
    let secondOverview = staleOverview.node("search-send").click();
    await flush();
    staleOverview.pending.shift().resolve(response("New quote"));
    await secondOverview;
    for (let i=0;i<3;i++) await flush();
    staleOverview.relevanceRequests[1].resolve();
    for (let i=0;i<3;i++) await flush();
    staleOverview.relevanceRequests[0].resolve();
    for (let i=0;i<3;i++) await flush();
    assert.match(staleOverview.node("direct-relevance").textContent,/New question/);
    assert.doesNotMatch(staleOverview.node("direct-relevance").textContent,/Old question/);
    assert.equal(staleOverview.errors.length,0);
    if (process.env.ZITATLOTSE_OVERVIEW_REPORT) {
        const liveOverview = JSON.parse(fs.readFileSync(process.env.ZITATLOTSE_OVERVIEW_REPORT,"utf8").replace(/^\uFEFF/, ""));
        const replay = setup([1,8]);
        replay.relevanceReplies.push(liveOverview);
        replay.open(1,"search");
        replay.node("search-input").value = liveOverview.query;
        const search = replay.node("search-send").click();
        await flush();
        replay.pending.shift().resolve(response(""));
        await search;
        for(let i=0;i<3;i++) await flush();
        for (const category of ["all", ...liveOverview.categories.filter(c=>c.count).map(c=>c.id)]) {
            await replay.node("direct-relevance-"+category).click();
            const expected = liveOverview.documents.filter(d=>category==="all" || d.category===category);
            const titles = [];
            const pages = Math.ceil(expected.length/5);
            for (let page=0;page<pages;page++) {
                for (const row of replay.node("direct-relevance-documents").children) titles.push(row.children[0].textContent);
                if(page+1<pages) await replay.node("direct-relevance-next").click();
            }
            assert.deepEqual(titles,expected.map(d=>d.title), "Actual category and pagination must contain each unique document exactly once");
        }
        console.log("Echte Dokumentgruppen in Kategorien und Seiten sichtbar: "+liveOverview.total_documents+" Dokumente aus "+liveOverview.total_attachments+" Anhängen");
    }
    // Optional replay of the actual local-service/DeepSeek results. This checks
    // real selected references in the UI without another charged provider call.
    if (process.env.ZITATLOTSE_LIVE_REPORT) {
        const report = JSON.parse(fs.readFileSync(process.env.ZITATLOTSE_LIVE_REPORT,"utf8"));
        for (const entry of report.cases) {
            assert.equal(entry.state, "complete", entry.id);
            assert.ok(entry.ui_result, "A real service result is required for UI replay");
            const replay = setup([report.library_id, 8]);
            if (entry.document_relevance) replay.relevanceReplies.push(entry.document_relevance);
            replay.open(report.library_id);
            replay.node("chat-input").value = entry.question;
            const replayJob = replay.node("chat-send").click();
            for (let i = 0; i < 3; i++) await flush();
            replay.pending.shift().resolve(entry.ui_result);
            await replayJob;
            for (let i=0;i<3;i++) await flush();
            if (entry.document_relevance) {
                if (entry.document_relevance.language_queries) assert.deepEqual(replay.relevanceRequests.at(-1).data.language_queries,
                    entry.document_relevance.language_queries, entry.id + ": the graph must reuse the actual AI language queries");
                assert.match(replay.node("chat-relevance").textContent,/Geschätzte Dokumentrelevanz/);
                assert.ok(replay.node("chat-relevance").textContent.includes(entry.question));
                for (const document of entry.document_relevance.documents.slice(0,5))
                    assert.ok(replay.node("chat-relevance-documents").textContent.includes(document.title));
                if (entry.document_relevance.documents.length > 5) {
                    await replay.node("chat-relevance-next").click();
                    assert.ok(replay.node("chat-relevance-documents").textContent.includes(entry.document_relevance.documents[5].title));
                    await replay.node("chat-relevance-previous").click();
                }
            }
            const selected = entry.ui_result.selected_results || entry.ui_result.results.filter(hit=>hit.recommended);
            for (const quote of selected.slice(0,20))
                assert.ok(replay.node("chat-results").textContent.includes(quote.quote), entry.id + ": selected original quote must be visible");
            if (entry.positive) assert.ok(selected.length, entry.id + ": no AI-selected quotes");
            else assert.equal(selected.length,0, entry.id + ": unrelated query must show no quotes");
            assert.ok(replay.node("chat-results").scrollRequest, "Completed results are brought into view");
            await replay.node("close").click();
            replay.open(report.library_id);
            if (process.env.ZITATLOTSE_PREVIEW_HTML && entry.id === "mivolo_exact")
                fs.writeFileSync(process.env.ZITATLOTSE_PREVIEW_HTML,previewHTML(replay.doc));
            for (const quote of selected.slice(0,20))
                assert.ok(replay.node("chat-results").textContent.includes(quote.quote), "Reopening preserves actual AI result");
            console.log("Echte KI-Antwort im Suchfenster sichtbar: " + entry.id + " · " + selected.length + " Zitate");
        }
    }
    console.log("Live-KI-Ablauf, Anzeigeeinstellung, Sammlung, Untersammlungen und Abbruch bei Filterwechsel: OK");
    console.log("Fenster erneut öffnen, Verlauf, Entwürfe, Treffer, Bibliotheken, Reset und Neustart: OK");
    console.log("Dokumentrelevanz, Farbgruppen, PDF öffnen, Bereich, leere Sammlung und verspätete Antworten: OK");
})().catch(error => {console.error(error); process.exitCode = 1;});
