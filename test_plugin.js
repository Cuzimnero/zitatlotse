const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const requests = [];
const parent = {
    libraryID: 7, key: "PARENT", deleted: false,
    isRegularItem: () => true, isAttachment: () => false,
    getCollections: () => [12], getCreators: () => [{firstName: "A", lastName: "Beispiel"}],
    getField: name => ({title: "Artikel", date: "2026", language: "en-US"})[name] || "",
    getAttachments: () => [11],
};
const pdf = {
    libraryID: 7, key: "PDF", parentID: 10, deleted: false,
    attachmentContentType: "application/pdf", attachmentFilename: "artikel.pdf",
    isRegularItem: () => false, isAttachment: () => true,
    getField: () => "Artikel PDF", getFilePathAsync: async () => "C:\\artikel.pdf",
};
const context = vm.createContext({
    setTimeout: callback => callback(),
    Zotero: {
        HTTP: {request: async (_method, _url, options) => {
            requests.push(JSON.parse(options.body));
            return {responseText: JSON.stringify({status: "indexed", chunks: 3})};
        }},
        Items: {get: id => ({10: parent, 11: pdf})[id], getAll: async () => [parent, pdf]},
        URI: {getItemURI: item => "zotero://" + item.key},
        Libraries: {userLibraryID: 7},
        getActiveZoteroPane: () => null,
    },
});
vm.runInContext(fs.readFileSync("plugin/bootstrap.js", "utf8"), context);
const realOpenSearchWindow = vm.runInContext("openSearchWindow", context);

(async () => {
    let result = await vm.runInContext("indexItem(Zotero.Items.get(11))", context);
    assert.equal(result.checked, 1);
    assert.equal(result.chunks, 3);
    assert.equal(requests[0].item_key, "PARENT");
    assert.equal(requests[0].attachment_key, "PDF");
    assert.equal(requests[0].language, "en-US");
    context.Zotero.locale = "de-DE";
    assert.equal(vm.runInContext('ui("Deutsch", "English")', context), "Deutsch");
    context.Zotero.locale = "en-US";
    assert.equal(vm.runInContext('ui("Deutsch", "English")', context), "English");
    assert.equal(vm.runInContext('modelForProvider("deepseek", "mistral", true)', context),
        "deepseek-flash", "Switching from a custom Ollama model must select a DeepSeek model");
    assert.equal(vm.runInContext('modelForProvider("deepseek", "custom-deepseek", false)', context),
        "custom-deepseek", "Loading an existing provider keeps its custom model");
    assert.equal(vm.runInContext('isConnectionFailure({status:0,message:"HTTP GET failed with status code 0"})', context),
        true, "Zotero reports a stopped local service as HTTP status 0");
    assert.equal(vm.runInContext('isConnectionFailure({status:500,message:"HTTP 500"})', context), false);
    assert.equal(vm.runInContext('isConnectionFailure({message:"NetworkError when attempting to fetch resource"})', context),
        true, "A Zotero network error without a status must trigger service startup");
    requests.length = 0;
    const progressUpdates = [];
    context.progressCallback = (summary, _message, total) => progressUpdates.push([summary.pdfs, total]);
    result = await vm.runInContext("indexLibrary(7, progressCallback)", context);
    assert.equal(result.checked, 1, "The library scan must not index a child PDF twice");
    assert.equal(requests.length, 1);
    assert.deepEqual(progressUpdates.at(-1), [1, 1]);
    const nodes = [];
    const progressDoc = {
        getElementById: () => null,
        createElementNS: (_ns, tag) => {
            const classes = new Set();
            const node = {
                tag, style: {}, attributes: {}, ownerDocument: progressDoc, children: [],
                classList: {add: value => classes.add(value), remove: value => classes.delete(value),
                    toggle: (value, enabled) => enabled ? classes.add(value) : classes.delete(value),
                    contains: value => classes.has(value)},
                setAttribute(name, value) {this.attributes[name] = value;},
                removeAttribute(name) {delete this.attributes[name];},
                append(child) {this.children.push(child);},
            };
            nodes.push(node);
            return node;
        },
        documentElement: {append() {}},
    };
    context.progressParent = {ownerDocument: progressDoc, append(node) {this.track = node;}};
    const progressBar = vm.runInContext("makeProgress(progressParent)", context);
    progressBar.start();
    assert.equal(context.progressParent.track.style.display, "block");
    progressBar.update(2, 4);
    assert.equal(context.progressParent.track.attributes["aria-valuenow"], "2");
    assert.equal(context.progressParent.track.children[0].style.width, "50%");
    progressBar.stop();
    assert.equal(context.progressParent.track.style.display, "none");
    let sidenavStyles;
    const xul = () => ({setAttribute() {}, addEventListener() {}, appendChild() {}});
    const doc = {
        getElementById: id => id === "toolsMenu" ? {after() {}} : null,
        createElementNS: xul,
        documentElement: {append(node) {sidenavStyles = node.textContent;}},
    };
    context.testWindow = {document: doc, MozXULElement: {insertFTLIfNeeded() {}}};
    vm.runInContext("onMainWindowLoad({window:testWindow}); openSearchWindow = (id, tab) => { opened = {id, tab}; }", context);
    assert.ok(sidenavStyles.includes('[data-pane$="-quote-search-section"]'),
        "The larger namespaced native icon is hidden before the sidebar renders");
    let quickButton;
    let nativeButton;
    const sidenav = {
        querySelector(selector) {
            if (selector === ".zqs-quick-search") return quickButton;
            return null;
        },
        querySelectorAll() {return nativeButton ? [nativeButton] : [];},
        insertBefore(button) {quickButton = button;},
    };
    let buttonAnimations = 0;
    const quickDoc = {
        querySelectorAll: () => [sidenav],
        createElementNS: () => ({
            style: {}, setAttribute() {},
            classList: {add(name) {if (name === "zqs-button-press") buttonAnimations++;}, remove() {}},
            addEventListener(type, handler) {this.handlers ||= {}; this.handlers[type] = handler;},
        }),
    };
    context.quickWin = {document: quickDoc, getComputedStyle: () => ({display:"block"})};
    vm.runInContext('syncSidenavSearchButtons(quickWin)', context);
    assert.equal(quickButton.style.display, "flex", "The search button stays visible without a selected item");
    quickButton.handlers.click({button:0,preventDefault() {},stopPropagation() {}});
    assert.equal(context.opened.id, 7);
    assert.equal(context.opened.tab, "chat", "The right bar button opens AI search");
    assert.equal(buttonAnimations, 1, "The right bar button has a short click animation");
    quickButton.handlers.click({button:0,preventDefault() {},stopPropagation() {}});
    assert.equal(buttonAnimations, 2, "The click animation restarts on repeated clicks");
    vm.runInContext("lastPanelCloseAt = Date.now()", context);
    quickButton.handlers.click({button:0,preventDefault() {},stopPropagation() {}});
    assert.equal(buttonAnimations, 2, "A close click cannot immediately reopen the panel");
    vm.runInContext("lastPanelCloseAt = 0", context);
    const nativeWrapperClasses = new Set();
    nativeButton = {
        dataset: {pane: "quote-search\\@local\\.example-quote-search-section"},
        parentElement: {hidden:false, classList:{add: name => nativeWrapperClasses.add(name)}},
        attributes: {}, setAttribute(name, value) {this.attributes[name] = value;},
    };
    vm.runInContext('syncSidenavSearchButtons(quickWin)', context);
    assert.ok(nativeWrapperClasses.has("zqs-native-sidenav-hidden"),
        "Hide the larger icon using Zotero's actual namespaced pane ID");
    assert.equal(nativeButton.attributes["aria-hidden"], "true");
    assert.equal(nativeButton.tabIndex, -1);
    assert.equal(quickButton.style.display, "flex", "Keep the smaller working button when the native icon exists");
    nativeButton.parentElement.hidden = true;
    vm.runInContext('syncSidenavSearchButtons(quickWin)', context);
    assert.equal(quickButton.style.display, "flex", "The small button is independent of the processing section");
    let secondQuick;
    const secondSidenav = {
        querySelector(selector) {return selector === ".zqs-quick-search" ? secondQuick : null;},
        insertBefore(button) {secondQuick = button;},
    };
    quickDoc.querySelectorAll = () => [sidenav, secondSidenav];
    vm.runInContext('syncSidenavSearchButtons(quickWin)', context);
    assert.equal(secondQuick, undefined, "Only one fallback button may be created across sidebars");
    let closeRemovals = 0;
    let listenerRemovals = 0;
    context.closeDoc = {removeEventListener() {listenerRemovals++;}};
    context.closeOverlay = {
        classList: {remove() {}, add() {}},
        remove() {closeRemovals++;},
    };
    context.closeEscape = () => {};
    vm.runInContext("dismissSearchWindow(closeDoc, closeOverlay, closeEscape)", context);
    vm.runInContext("dismissSearchWindow(closeDoc, closeOverlay, closeEscape)", context);
    assert.equal(closeRemovals, 1, "The first close action removes the panel once");
    assert.equal(listenerRemovals, 1, "Closing does not leave duplicate Escape handlers");
    vm.runInContext("lastPanelCloseAt = 0", context);
    const animationFrames = [];
    const animatedShell = {
        style: {},
        getBoundingClientRect: () => ({left:300,top:100,width:600,height:500}),
    };
    context.animationOverlay = {
        ownerDocument: {defaultView: {requestAnimationFrame(callback) {animationFrames.push(callback);}}},
        classList: {remove() {}, add() {}},
    };
    context.animationShell = animatedShell;
    context.animationLaunch = {left:900,top:50,width:32,height:32};
    vm.runInContext("animateSearchWindow(animationOverlay, animationShell, animationLaunch)", context);
    assert.equal(animatedShell.style.opacity, ".35", "The whole window starts near the clicked button");
    assert.equal(animatedShell.style.transform, "translate3d(316px,-284px,0) scale(0.16)");
    assert.equal(context.animationOverlay.zqsLaunchTransform, animatedShell.style.transform);
    animationFrames.shift()();
    animationFrames.shift()();
    assert.equal(animatedShell.style.opacity, "1");
    assert.equal(animatedShell.style.transform, "translate3d(0,0,0) scale(1)",
        "The window and its close button grow together to full size");
    let reversedRemovals = 0;
    context.reverseDoc = {removeEventListener() {}, defaultView: {getComputedStyle: () => ({opacity:"1"})}};
    context.reverseShell = {style: {transform:"translate3d(0,0,0) scale(1)"}};
    context.reverseOverlay = {
        zqsLaunchTransform: context.animationOverlay.zqsLaunchTransform,
        zqsLaunchOpacity: context.animationOverlay.zqsLaunchOpacity,
        style: {}, classList: {remove() {}, add() {}},
        remove() {reversedRemovals++;},
    };
    vm.runInContext("dismissSearchWindow(reverseDoc, reverseOverlay, () => {}, reverseShell, true)", context);
    assert.equal(context.reverseShell.style.transform,
        "translate3d(316px,-284px,0) scale(0.16)",
        "Closing returns the entire window to its launch position");
    assert.equal(context.reverseShell.style.opacity, ".35");
    assert.equal(context.reverseOverlay.style.opacity, "0");
    assert.equal(reversedRemovals, 1);
    vm.runInContext("lastPanelCloseAt = 0", context);
    let toggledClosed = 0;
    let tabChanges = 0;
    context.toggleButton = {getBoundingClientRect: () => ({left:900,top:50,width:32,height:32})};
    const openOverlay = {
        zitatlotseLaunchButton: context.toggleButton,
        zitatlotseClose() {toggledClosed++;},
        zitatlotseSetLibrary() {},
        zitatlotseShowTab() {tabChanges++;},
    };
    context.Zotero.getMainWindow = () => ({document: {
        getElementById: id => id === "zqs-window-style" ? {} :
            id === "zqs-overlay" ? openOverlay : null,
    }});
    realOpenSearchWindow(7, "chat", context.toggleButton);
    assert.equal(toggledClosed, 1, "Clicking the same launcher again closes the open panel");
    assert.equal(tabChanges, 0, "The second click must not merely reopen its tab");
    let locator;
    let freed = false;
    context.Zotero.Items.getByLibraryAndKey = (libraryID, key) => {
        assert.equal(libraryID, 7);
        assert.equal(key, "PARENT");
        return {id: 10};
    };
    context.Zotero.Styles = {get: () => ({getCiteProc: () => ({
        updateItems: ids => assert.deepEqual(Array.from(ids), [10]),
        previewCitationCluster: citation => {
            locator = citation.citationItems[0].locator;
            return "(Beispiel, 2026, S. 4)";
        },
        free: () => { freed = true; },
    })})};
    context.hit = {library_id: 7, item_key: "PARENT", page: 4, creators: "A. Beispiel", year: "2026"};
    assert.equal(vm.runInContext('citationForHit(hit, "style-id")', context), "(Beispiel, 2026, S. 4)");
    assert.equal(locator, "4");
    assert.equal(freed, true);
    let opened;
    context.Zotero.Items.getByLibraryAndKey = (_libraryID, key) => {
        assert.equal(key, "PDF");
        return pdf;
    };
    pdf.id = 11;
    context.Zotero.Reader = {open: async (id, location) => { opened = {id, location}; }};
    context.hit = {library_id:7,attachment_key:"PDF",page:4,
        position:{pageIndex:3,rects:[[1,2,3,4]]}};
    await vm.runInContext("openQuoteInPDF(hit)", context);
    assert.equal(opened.id, 11);
    assert.deepEqual(JSON.parse(JSON.stringify(opened.location)),
        {position:{pageIndex:3,rects:[[1,2,3,4]]}});
    let initialized, spotlight;
    context.Zotero.Reader.open = async () => ({_initPromise:new Promise(resolve => {initialized = resolve;}),
        navigate: async location => {spotlight = location;}});
    const opening = vm.runInContext("openQuoteInPDF(hit)", context);
    for (let count = 0; count < 12; count++) await Promise.resolve();
    assert.equal(spotlight, undefined, "Spotlight must wait for the new reader tab");
    initialized();
    await opening;
    assert.deepEqual(JSON.parse(JSON.stringify(spotlight)), {position:{pageIndex:3,rects:[[1,2,3,4]]}});
    // A busy position service cannot keep the search overlay above the PDF.
    const originalHTTP = context.Zotero.HTTP.request;
    let completeLookup, panelDismissed = false, lookupOptions;
    context.dismissForPDF = () => {panelDismissed = true;};
    context.Zotero.HTTP.request = async (_method, _url, options) => {
        lookupOptions = options;
        return new Promise(resolve => {completeLookup = resolve;});
    };
    spotlight = undefined;
    context.Zotero.Reader.open = async (id, location, options) => {
        opened = {id, location, options};
        return {_initPromise:Promise.resolve(), navigate:async location => {spotlight = location;}};
    };
    context.hit = {library_id:7, attachment_key:"PDF", page:4, quote:"Exact passage"};
    const delayedLookup = vm.runInContext("openQuoteInPDF(hit, dismissForPDF)", context);
    for (let count = 0; count < 20 && !completeLookup; count++) await Promise.resolve();
    assert.equal(panelDismissed, true, "Dismiss the overlay before awaiting the position service");
    assert.equal(opened.location.pageIndex, 3, "Open the requested page immediately");
    assert.equal(opened.options.openInBackground, false);
    assert.equal(lookupOptions.timeout, 5000, "Bound position lookup independently of long searches");
    completeLookup({responseText:'{"position":{"pageIndex":3,"rects":[[10,20,30,40]]}}'});
    await delayedLookup;
    assert.deepEqual(JSON.parse(JSON.stringify(spotlight)), {position:{pageIndex:3,rects:[[10,20,30,40]]}});
    context.Zotero.HTTP.request = async () => {let error = new Error("position lookup failed"); error.status = 500; throw error;};
    context.hit = {library_id:7, attachment_key:"PDF", page:5};
    await vm.runInContext("openQuoteInPDF(hit)", context);
    assert.equal(spotlight.pageIndex, 4, "A failed locator still opens the correct PDF page");
    // Zotero returns no reader for an existing unloaded tab; retrieve it after selection.
    context.Zotero.Reader.open = async () => undefined;
    context.Zotero.Reader.getByTabID = () => ({itemID:11, _initPromise:Promise.resolve(),
        navigate:async location => {spotlight = location;}});
    await vm.runInContext("openQuoteInPDF(hit)", context);
    assert.equal(spotlight.pageIndex, 4, "Unloaded reader tabs receive the destination too");
    delete context.Zotero.Reader.getByTabID;
    context.Zotero.HTTP.request = originalHTTP;
    let launches = 0;
    let live = false;
    const localRoot = "C:\\Users\\Test\\AppData\\Local";
    const serviceContext = vm.createContext({
        setTimeout: callback => callback(),
        Zotero: {
            isWin: true,
            locale: "de-DE",
            HTTP: {request: async (_method, url) => {
                if (!live) {
                    let error = new Error("HTTP GET failed with status code 0");
                    error.status = 0;
                    error.xmlhttp = {status: 0};
                    throw error;
                }
                return {responseText: JSON.stringify(url.endsWith("/health") ?
                    {ok: true, service:"zitatlotse"} : {documents: 2})};
            }},
        },
        Components: {
            interfaces: {nsIEnvironment: {}, nsIFile: {}, nsIProcess: {}},
            classes: {
                "@mozilla.org/process/environment;1": {getService: () => ({
                    get: name => name === "LOCALAPPDATA" ? localRoot : name === "USERPROFILE" ? "C:\\Users\\Test" : "",
                })},
                "@mozilla.org/file/local;1": {createInstance: () => ({
                    initWithPath(path) {this.path = path;},
                    append(part) {this.path += "\\" + part;},
                    exists: () => true,
                })},
                "@mozilla.org/process/util;1": {createInstance: () => ({
                    init(file) {assert.ok(file.path.endsWith(".venv\\Scripts\\pythonw.exe"));},
                    runwAsync(args) {
                        assert.equal(args.length,2);
                        assert.ok(args[0].includes("\\.zitatlotse\\"), "Prefer the shared profile path over virtualized AppData");
                        assert.ok(args[0].endsWith("backend\\launcher.py"));
                        assert.equal(args[1],"--supervise");
                        launches++;
                        live = true;
                    },
                })},
            },
        },
    });
    vm.runInContext(fs.readFileSync("plugin/bootstrap.js", "utf8"), serviceContext);
    let responses = await Promise.all([
        vm.runInContext('serviceRequest("GET", "/status", {timeout:5000})', serviceContext),
        vm.runInContext('serviceRequest("GET", "/status", {timeout:5000})', serviceContext),
    ]);
    assert.equal(launches, 1, "Concurrent requests start one local process");
    assert.equal(JSON.parse(responses[0].responseText).documents, 2);
    live = false;
    const fileClass = serviceContext.Components.classes["@mozilla.org/file/local;1"];
    const oldFactory = fileClass.createInstance;
    fileClass.createInstance = () => ({initWithPath(){}, append(){}, exists:() => false});
    await assert.rejects(vm.runInContext('serviceRequest("GET", "/status", {timeout:5000})', serviceContext),
        /nicht vollständig installiert/, "Keep the precise missing-runtime error instead of a generic network message");
    fileClass.createInstance = oldFactory;
    await vm.runInContext('serviceRequest("GET", "/status", {timeout:5000})', serviceContext);
    assert.equal(launches, 2, "A failed startup must release the shared promise so a later request can recover");
    console.log("Einzel-PDF, Bibliotheksscan, Seitenbeleg und Seitenleistenknopf: OK");
})().catch(error => { console.error(error); process.exitCode = 1; });
