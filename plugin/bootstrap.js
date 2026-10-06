const PLUGIN_ID = "quote-search@local.example";
const BASE = "http://127.0.0.1:8765";
const MODEL_SUGGESTIONS = {
    openai: ["gpt-4.1-mini", "gpt-4.1", "gpt-5-mini"],
    anthropic: ["claude-sonnet-5-5", "claude-opus-5-5", "claude-fable-5-1", "claude-haiku-4-5-20251001"],
};
const HTML = "http://www.w3.org/1999/xhtml";
const XUL = "http://www.mozilla.org/keymaster/gatekeeper/there.is.only.xul";
let registeredSection;
let observerID;
let pluginRoot;
let serviceLaunchPromise;
let serviceProcess;
let lastPanelCloseAt = 0;
let knownEmbeddingModel = "";
let showAIActivity = true;
const libraryCollections = new Map();
// Window-independent, per-library state. Nothing is written to disk: a Zotero
// restart starts a fresh session. Replacing a state also invalidates pending replies.
const searchSessions = new Map();
const searchSessionListeners = new Set();
const RESULTS_PER_PAGE = 20;

function newSearchSession() {
    return {messages: [], draft: "", hits: null, queries: [], page: null,
        resultPages: {}, totalResults: null, viewPage: 1, showAll: false, reviewed: false, selectedHits: null,
        pending: false, loadingMore: false, status: "", searchMode: "chat", evidence: null,
        activity: [], activityExpanded: true, scope: {}, overview: null,
        overviewPending: false, overviewError: "", overviewCategory: "all", overviewPage: 1, overviewToken: 0};
}

function storeResultsPage(state, data, number = 1) {
    state.resultPages[number] = {hits: data.results || [], next: data.next_offset,
        hasMore: Boolean(data.has_more)};
    if (Number.isInteger(data.total_results) && data.total_results >= 0)
        state.totalResults = data.total_results;
    else if (!data.has_more) state.totalResults = (number - 1) * RESULTS_PER_PAGE + (data.results || []).length;
}

function resultsView(state, mode) {
    if (mode === "chat" && state.reviewed && !state.showAll) {
        let hits = state.selectedHits || (state.hits || []).filter(hit => hit.recommended === true);
        let count = Math.max(1, Math.ceil(hits.length / RESULTS_PER_PAGE));
        let number = Math.min(state.viewPage, count);
        return {hits: hits.slice((number - 1) * RESULTS_PER_PAGE, number * RESULTS_PER_PAGE),
            number, count, total: hits.length, filtered: true, exactCount: true};
    }
    let loaded = Object.keys(state.resultPages).map(Number);
    let last = Math.max(1, ...loaded);
    let count = state.totalResults === null
        ? last + (state.resultPages[last]?.hasMore ? 1 : 0)
        : Math.max(1, Math.ceil(state.totalResults / RESULTS_PER_PAGE));
    let number = Math.min(state.viewPage, count);
    return {hits: state.resultPages[number]?.hits || [], number, count,
        total: state.totalResults, filtered: false, exactCount: state.totalResults !== null};
}

function getSearchSession(libraryID, mode) {
    libraryID = Number(libraryID);
    if (!searchSessions.has(libraryID)) searchSessions.set(libraryID,
        {chat: newSearchSession(), direct: newSearchSession()});
    return searchSessions.get(libraryID)[mode];
}

function notifySearchSession(libraryID, mode) {
    for (let listener of searchSessionListeners) listener(Number(libraryID), mode);
}

function resetSearchSession(libraryID, mode) {
    getSearchSession(libraryID, mode);
    searchSessions.get(Number(libraryID))[mode] = newSearchSession();
    notifySearchSession(libraryID, mode);
}

function isCurrentSearchSession(libraryID, mode, state) {
    return searchSessions.get(Number(libraryID))?.[mode] === state;
}

function ui(de, en) {
    return /^de(?:-|$)/i.test(Zotero.locale || "") ? de : en;
}

function uiLang() {
    return /^de(?:-|$)/i.test(Zotero.locale || "") ? "de" : "en";
}

function confirmEmbeddingChange(label, description = "") {
    let win = Zotero.getMainWindow();
    let title = ui("Embedding-Modell wechseln", "Change embedding model");
    let message = ui("Wollen Sie Ihre Datenbank auf das neue Modell aktualisieren?", "Do you want to update your database to the new model?") +
        "\n\n" + label + (description ? "\n" + description : "") + "\n\n" + ui(
            "Alle gespeicherten Text-Chunks in allen Bibliotheken werden neu berechnet. Das bisherige Modell bleibt bis zum erfolgreichen Abschluss aktiv. Gespeicherte Zitate bleiben erhalten. Bei Bedarf wird das neue Modell heruntergeladen.",
            "All stored chunks in every library will be recalculated. The previous model stays active until completion. Saved quotes are preserved. The new model will be downloaded if needed.");
    if (typeof Services !== "undefined") return Services.prompt.confirm(win, title, message);
    if (typeof Components !== "undefined") return Components.classes["@mozilla.org/embedcomp/prompt-service;1"]
        .getService(Components.interfaces.nsIPromptService).confirm(win, title, message);
    return Boolean(win.confirm?.(message));
}

const DEFAULT_MODELS = {openai:"gpt-4.1-mini",anthropic:"claude-sonnet-5-5",
    deepseek:"deepseek-flash",ollama:"gemma3:4b"};

function modelForProvider(provider, currentModel, providerChanged = false) {
    return providerChanged || !currentModel || Object.values(DEFAULT_MODELS).includes(currentModel)
        ? DEFAULT_MODELS[provider] || "" : currentModel;
}

function isConnectionFailure(error) {
    let status = error?.status ?? error?.xmlhttp?.status;
    let message = error?.message || String(error);
    return status === 0 || (status == null &&
        !/\b(?:HTTP|status code)\s*[45]\d\d\b/i.test(message)) ||
        /status code 0|Verbindung zum Server|connection refused|NS_ERROR_CONNECTION_REFUSED|could not connect|networkerror/i
        .test(message);
}

async function ensureLocalService() {
    if (serviceLaunchPromise) return serviceLaunchPromise;
    serviceLaunchPromise = (async () => {
        try {
            await Zotero.HTTP.request("GET", BASE + "/health", {timeout: 1500});
            return;
        } catch (error) {
            if (!isConnectionFailure(error)) throw error;
        }
        if (!Zotero.isWin) throw new Error(ui(
            "Automatischer Start wird derzeit nur unter Windows unterstützt.",
            "Automatic startup is currently supported on Windows only."));
        let environment = Components.classes["@mozilla.org/process/environment;1"]
            .getService(Components.interfaces.nsIEnvironment);
        let roots = [[environment.get("USERPROFILE"), ".zitatlotse"],
            [environment.get("LOCALAPPDATA"), "Zitatlotse"]];
        let executable, launcher;
        for (let [base, folder] of roots) {
            if (!base) continue;
            let file = Components.classes["@mozilla.org/file/local;1"].createInstance(Components.interfaces.nsIFile);
            file.initWithPath(base);
            for (let part of [folder, "backend", ".venv", "Scripts", "pythonw.exe"]) file.append(part);
            let script = Components.classes["@mozilla.org/file/local;1"].createInstance(Components.interfaces.nsIFile);
            script.initWithPath(base);
            for (let part of [folder, "backend", "launcher.py"]) script.append(part);
            if (file.exists() && script.exists()) { executable = file; launcher = script; break; }
        }
        if (!executable || !launcher) throw new Error(ui(
            "Der lokale Suchdienst ist nicht vollständig installiert. Bitte Install-Zitatlotse.ps1 ausführen.",
            "The local search service is not fully installed. Please run Install-Zitatlotse.ps1."));
        serviceProcess = Components.classes["@mozilla.org/process/util;1"]
            .createInstance(Components.interfaces.nsIProcess);
        serviceProcess.init(executable);
        let arguments = [launcher.path, "--supervise"];
        serviceProcess.runwAsync(arguments, arguments.length, {observe() {}});
        for (let attempt = 0; attempt < 120; attempt++) {
            await new Promise(resolve => setTimeout(resolve, 500));
            try {
                await Zotero.HTTP.request("GET", BASE + "/health", {timeout: 1500});
                return;
            } catch (error) {
                if (!isConnectionFailure(error)) throw error;
            }
        }
        throw new Error(ui(
            "Der lokale Suchdienst startet nicht. Details stehen in der Installation unter backend\\data\\service.log.",
            "The local search service did not start. See backend\\data\\service.log in the installation folder."));
    })();
    try { return await serviceLaunchPromise; }
    catch (error) {
        let detail = new Error(error?.message || String(error));
        detail.zitatlotseStartupError = true;
        throw detail;
    }
    finally { serviceLaunchPromise = undefined; }
}

async function serviceRequest(method, path, options) {
    try {
        return await Zotero.HTTP.request(method, BASE + path, options);
    } catch (error) {
        if (!isConnectionFailure(error)) throw serviceError(error);
        try { await ensureLocalService(); }
        catch (startError) { throw serviceError(startError); }
        try { return await Zotero.HTTP.request(method, BASE + path, options); }
        catch (retryError) { throw serviceError(retryError); }
    }
}

async function request(path, data, options = {}) {
    try {
        let response = await serviceRequest("POST", path, {
            headers: { "Content-Type": "application/json", "X-Zitatlotse-Client": "1" },
            body: JSON.stringify(data),
            timeout: options.timeout ?? (path === "/chat-search" ? 420000 : 180000),
        });
        return JSON.parse(response.responseText);
    } catch (error) { throw serviceError(error); }
}

function serviceError(error) {
    if (error?.zitatlotseStartupError) return error;
    let message = error?.message || String(error);
    let response = error?.xmlhttp?.responseText || error?.responseText;
    if (response) {
        try {
            let detail = JSON.parse(response).error;
            if (detail) return new Error(detail);
        } catch (_) { /* Keep the original Zotero error. */ }
    }
    if (isConnectionFailure(error)) {
        return new Error(ui(
            "Der lokale Suchdienst ist nicht erreichbar. Bitte „Suchdienst prüfen“ wählen; falls er nicht startet, service.log prüfen.",
            "The local search service is unavailable. Select ‘Check service’; if it does not start, check service.log."));
    }
    return error;
}

function selectedLibraryID() {
    let pane = Zotero.getActiveZoteroPane();
    return pane?.getSelectedLibraryIDs()?.[0] ?? pane?.getSelectedItems()?.[0]?.libraryID;
}

async function collectionSearchScope(libraryID, collectionID) {
    if (!collectionID) return {};
    let root = Zotero.Collections.get(collectionID);
    if (!root || root.libraryID !== libraryID || root.deleted)
        throw new Error(ui("Die Sammlung ist nicht mehr verfügbar.", "This collection is no longer available."));
    await Zotero.Libraries.get(libraryID).waitForDataLoad?.("item");
    let collections = [root, ...Zotero.Collections.getByParent(collectionID, true)];
    let keys = new Set();
    for (let collection of collections) {
        if (collection.libraryID !== libraryID || collection.deleted) continue;
        await collection.loadDataType?.("childItems");
        for (let item of collection.getChildItems()) {
            if (!item || item.deleted || item.libraryID !== libraryID) continue;
            if (item.isRegularItem()) await item.loadDataType?.("childItems");
            let attachments = item.isAttachment() ? [item] : item.isRegularItem()
                ? item.getAttachments().map(id => Zotero.Items.get(id)) : [];
            for (let attachment of attachments) {
                if (attachment && !attachment.deleted && attachment.libraryID === libraryID &&
                    (attachment.attachmentContentType === "application/pdf" || /\.pdf$/i.test(attachment.attachmentFilename || "")))
                    keys.add(attachment.key);
            }
        }
    }
    return {collection_id:collectionID,attachment_keys:[...keys].sort()};
}

async function documentOverviewScope(libraryID, scope) {
    if (Array.isArray(scope.attachment_keys)) return {...scope};
    await Zotero.Libraries.get(libraryID).waitForDataLoad?.("item");
    let keys = new Set();
    for (let item of await Zotero.Items.getAll(libraryID)) {
        if (item.deleted || item.libraryID !== libraryID) continue;
        if (item.isRegularItem()) await item.loadDataType?.("childItems");
        let attachments = item.isAttachment() ? [item] : item.isRegularItem()
            ? item.getAttachments().map(id => Zotero.Items.get(id)) : [];
        for (let attachment of attachments) {
            if (attachment && !attachment.deleted && attachment.libraryID === libraryID &&
                (attachment.attachmentContentType === "application/pdf" || /\.pdf$/i.test(attachment.attachmentFilename || "")))
                keys.add(attachment.key);
        }
    }
    return {...scope, attachment_keys:[...keys].sort()};
}

function clearDocumentOverview(state) {
    state.overviewToken++;
    state.overview = null;
    state.overviewPending = false;
    state.overviewError = "";
    state.overviewCategory = "all";
    state.overviewPage = 1;
}

function documentLanguageQueries(data) {
    let queries = {};
    const add = (language, query) => {
        if (typeof language !== "string" || typeof query !== "string" || !query.trim() || query.trim().length > 1000) return;
        let lang = language.replace(/_/g, "-").toLowerCase().split("-")[0];
        if (/^[a-z]{2,3}$/.test(lang) && lang !== "all" && !queries[lang]) queries[lang] = query.trim();
    };
    if (data.agentic_used && Array.isArray(data.agent_steps)) {
        for (let step of data.agent_steps) {
            let language = step.language;
            if (language === "all" && Object.keys(data.languages || {}).length === 1) language = Object.keys(data.languages)[0];
            add(language, step.query);
        }
    } else for (let [language, query] of Object.entries(data.queries || {})) add(language, query);
    return queries;
}

async function loadDocumentOverview(libraryID, mode, state, question, languageQueries = {}) {
    let token = ++state.overviewToken;
    let current = () => isCurrentSearchSession(libraryID, mode, state) && state.overviewToken === token;
    state.overviewPending = true;
    notifySearchSession(libraryID, mode);
    try {
        let scope = await documentOverviewScope(libraryID, state.scope);
        if (!current()) return;
        // Compare the current question with every chunk. No retrieval cutoffs or
        // AI quote selection affect this independent document overview.
        let data = await request("/document-relevance", {library_id:libraryID,...scope,query:question,language_queries:languageQueries});
        if (!current()) return;
        for (let document of data.documents) {
            let item = Zotero.Items.getByLibraryAndKey(libraryID, document.attachment_key);
            let parent = item?.parentID ? Zotero.Items.get(item.parentID) : null;
            document.title = parent?.getField?.("title") || item?.getField?.("title") || document.title;
        }
        state.overview = data;
    } catch (error) {
        if (current()) state.overviewError = ui("Dokumentübersicht konnte nicht geladen werden: ",
            "Could not load document overview: ") + error.message;
    } finally {
        if (current()) {
            state.overviewPending = false;
            notifySearchSession(libraryID, mode);
        }
    }
}

function activityLabel(event) {
    switch (event.type) {
        case "started": return ui("Suchanfrage gestartet", "Search request started");
        case "model_call": return event.purpose === "planning" ? ui("KI formuliert Suchanfragen", "AI is formulating search queries")
            : event.purpose === "review" ? ui("KI wertet Fundstellen aus", "AI is reviewing passages")
            : (event.round > 1 ? ui("Erneute KI-Anfrage", "Another AI request") : ui("KI plant die Suche", "AI is planning the search")) +
                (event.round ? " · " + event.round : "");
        case "tool_call": return event.tool === "finish_search" ? ui("Tool-Aufruf: Suche abschließen", "Tool call: finish search")
            : ui("Tool-Aufruf: Bibliothek durchsuchen", "Tool call: search library") + (event.step ? " · " + event.step : "");
        case "search_started": return ui("Suchanfrage ausgeführt", "Search query submitted");
        case "search_results": return ui("Ergebnisse erhalten: ", "Results received: ") + event.count;
        case "tool_result": return ui("Tool-Ergebnisse an die KI übergeben", "Tool results returned to AI");
        case "cache_reused": return ui("Vorhandene Ergebnisse dieser Anfrage wiederverwendet", "Reused existing results for this query");
        case "retry": return ui("KI-Aufruf wird wiederholt", "Retrying AI call");
        case "tool_rejected": return ui("Ungültiger Tool-Aufruf abgelehnt", "Invalid tool call rejected");
        case "fallback": return ui("Suche mit Ersatzverfahren fortgesetzt", "Search continued with fallback method");
        case "review_started": return ui("Auswertung der Fundstellen gestartet: ", "Passage review started: ") + event.count;
        case "review_batch": return ui("KI prüft weitere Belege: ", "AI is assessing more evidence: ") + event.completed + " / " + event.total;
        case "review_complete": return ui("Auswertung abgeschlossen", "Review complete");
        case "complete": return ui("Suche abgeschlossen", "Search complete");
        case "failed": return ui("Suche fehlgeschlagen", "Search failed");
        default: return "";
    }
}

async function indexItem(item, onProgress) {
    let summary = { checked: 0, indexed: 0, chunks: 0, missing: 0, pdfs: 0 };
    if (!item || item.deleted || (!item.isRegularItem() && !item.isAttachment())) return summary;
    let source = item.isAttachment() && item.parentID ? Zotero.Items.get(item.parentID) : item;
    let collectionIDs = source.getCollections();
    let creators = source.isRegularItem()
        ? source.getCreators().map(c => [c.firstName, c.lastName].filter(Boolean).join(" ")).join(", ")
        : "";
    let attachments = item.isAttachment() ? [item] : item.getAttachments().map(id => Zotero.Items.get(id));
    for (let attachment of attachments) {
        if (!attachment || (attachment.attachmentContentType !== "application/pdf" &&
            !/\.pdf$/i.test(attachment.attachmentFilename || ""))) continue;
        summary.pdfs++;
        let path = await attachment.getFilePathAsync();
        if (!path) { summary.missing++; continue; }
        onProgress?.(ui("PDF „", "PDF ‘") +
            (attachment.getField("title") || attachment.attachmentFilename || attachment.key) +
            ui("“ wird in Chunks zerlegt und eingebettet …", "’ is being split into chunks and embedded…"));
        let result = await request("/index", {
            library_id: source.libraryID,
            item_key: source.key,
            attachment_key: attachment.key,
            collection_ids: collectionIDs,
            title: source.getField("title") || attachment.getField("title"),
            creators,
            year: source.isRegularItem() ? source.getField("date") : "",
            language: source.isRegularItem() ? source.getField("language") || "" : "",
            zotero_uri: Zotero.URI.getItemURI(source),
            pdf_path: path,
        });
        summary.checked++;
        if (result.status === "indexed") summary.indexed++;
        summary.chunks += result.chunks || 0;
    }
    return summary;
}

async function indexLibrary(libraryID, onProgress) {
    let summary = { checked: 0, indexed: 0, chunks: 0, missing: 0, pdfs: 0 };
    let items = (await Zotero.Items.getAll(libraryID)).filter(item =>
        !(item.isAttachment() && item.parentID));
    const isPDF = attachment => attachment && (attachment.attachmentContentType === "application/pdf" ||
        /\.pdf$/i.test(attachment.attachmentFilename || ""));
    let total = 0;
    for (let item of items) {
        if (item.isAttachment()) total += Number(isPDF(item));
        else if (item.isRegularItem()) total += item.getAttachments().filter(id => isPDF(Zotero.Items.get(id))).length;
    }
    onProgress?.(summary, undefined, total);
    for (let item of items) {
        let itemResult = await indexItem(item, message => onProgress?.(summary, message, total));
        for (let key of Object.keys(summary)) summary[key] += itemResult[key];
        if (itemResult.pdfs) onProgress?.(summary, undefined, total);
    }
    return summary;
}

function summaryText(summary, library = false) {
    if (!summary.pdfs) return library
        ? ui("Keine PDF-Datei in dieser Bibliothek gefunden.", "No PDF found in this library.")
        : ui("Keine PDF-Datei im ausgewählten Eintrag gefunden.", "No PDF found in the selected item.");
    let parts = [summary.indexed + ui(" PDFs neu verarbeitet", " PDFs processed"),
        summary.chunks + ui(" neue Text-Chunks", " new text chunks"),
        (summary.checked - summary.indexed) + ui(" bereits aktuell", " already up to date")];
    if (summary.missing) parts.push(summary.missing +
        ui(" PDF-Dateien lokal nicht verfügbar", " PDFs unavailable locally"));
    if (summary.indexed && !summary.chunks) parts.push(ui(
        "kein auslesbarer Text – eventuell OCR nötig", "no extractable text — OCR may be needed"));
    return parts.join(" · ") + ".";
}

function citationForHit(hit, styleID) {
    const simple = () => "(" + [hit.creators || hit.title, hit.year, "S. " + hit.page]
        .filter(Boolean).join(", ") + ")";
    if (styleID === "simple") return simple();
    let item = Zotero.Items.getByLibraryAndKey(hit.library_id, hit.item_key);
    let style = Zotero.Styles.get(styleID);
    if (!item || !style) return simple();
    let engine = style.getCiteProc(Zotero.locale || "de-DE", "text", {cache:true});
    try {
        engine.updateItems([item.id]);
        return engine.previewCitationCluster({
            citationItems: [{id:item.id, locator:String(hit.page), label:"page"}],
            properties: {},
        }, [], [], "text");
    } finally { engine.free(); }
}

async function openQuoteInPDF(hit, onOpened = () => {}) {
    let attachment = Zotero.Items.getByLibraryAndKey(hit.library_id, hit.attachment_key);
    if (!attachment || !attachment.isAttachment()) throw new Error(ui(
        "PDF-Anhang in dieser Bibliothek nicht gefunden.", "PDF attachment not found in this library."));
    let pageIndex = Number(hit.page) - 1;
    if (!Number.isInteger(pageIndex) || pageIndex < 0) throw new Error(ui("Ungültige PDF-Seite.", "Invalid PDF page."));
    let position = hit.position?.pageIndex === pageIndex ? hit.position : null;
    let location = position?.rects?.length ? {position} : {pageIndex};
    // Show the PDF first. Position lookup can wait behind a long local search;
    // it must never keep the overlay above the reader for up to three minutes.
    let reader = await Zotero.Reader.open(attachment.id, location, {openInBackground:false, preventJumpback:true});
    onOpened();
    try {
        // Zotero is authoritative after an attachment/storage directory moved.
        let pdfPath = await attachment.getFilePathAsync?.();
        let located = await request("/quote-position", {library_id:hit.library_id,
            attachment_key:hit.attachment_key,page:hit.page,quote:hit.quote,pdf_path:pdfPath}, {timeout:5000});
        if (located.position?.pageIndex === pageIndex && located.position?.rects?.length) position = hit.position = located.position;
    } catch (error) { Zotero.logError?.(error); }
    location = position?.rects?.length ? {position} : {pageIndex};
    // New or unloaded tabs must finish initialization before spotlight navigation.
    for (let attempt = 0; !reader && attempt < 40; attempt++) {
        let selected = Zotero.getMainWindow()?.Zotero_Tabs?.selectedID;
        reader = Zotero.Reader.getByTabID?.(selected);
        if (reader?.itemID !== attachment.id) reader = Zotero.Reader._readers?.find(
            candidate => candidate.itemID === attachment.id && !candidate._isTabClosed);
        if (!reader && (Zotero.Reader.getByTabID || Zotero.Reader._readers)) await new Promise(resolve => setTimeout(resolve, 100));
        else if (!reader) break;
    }
    if (reader) {
        await reader._initPromise;
        await reader.navigate(location);
    }
}

function element(doc, tag, text) {
    let el = doc.createElementNS(HTML, tag);
    if (text !== undefined) el.textContent = text;
    return el;
}

function centerButton(button) {
    for (let [property, value] of [["display", "inline-flex"], ["align-items", "center"],
        ["justify-content", "center"], ["text-align", "center"],
        ["vertical-align", "middle"], ["line-height", "1.25"]]) {
        button.style.setProperty(property, value, "important");
    }
}

function ensureWindowStyles(doc) {
    if (doc.getElementById("zqs-window-style")) return;
    let style = element(doc, "style", `
        @keyframes zqs-backdrop-enter { from { opacity:0; } to { opacity:1; } }
        @keyframes zqs-backdrop-exit { from { opacity:1; } to { opacity:0; } }
        @keyframes zqs-button-press {
            0%,100% { transform:scale(1); }
            45% { transform:scale(.82); }
            72% { transform:scale(1.12); }
        }
        .zqs-button-press { animation:zqs-button-press .36s ease-out; }
        item-pane-sidenav .btn[data-l10n-id="zitatfinder-sidenav"],
        item-pane-sidenav .btn[data-pane="quote-search-section"],
        item-pane-sidenav .btn[data-pane$="-quote-search-section"],
        item-pane-sidenav .zqs-native-sidenav-hidden { display:none!important; }
        #zqs-overlay.zqs-entering { animation:zqs-backdrop-enter .28s ease-out; }
        #zqs-overlay.zqs-leaving { animation:zqs-backdrop-exit .16s ease-out forwards; }
        @media (max-width:700px) {
            #zqs-overlay { padding:0!important; }
            #zqs-shell {
                width:100%!important;max-width:100%!important;
                height:100vh!important;max-height:100vh!important;
            }
            #zqs-panel {
                width:100%!important;max-width:100%!important;
                height:100vh!important;max-height:100vh!important;border-radius:0!important;
            }
            #zqs-header { min-height:64px; }
        }
    `);
    style.id = "zqs-window-style";
    doc.documentElement.append(style);
}

function animateOpenButton(button) {
    button.classList.remove("zqs-button-press");
    void button.offsetWidth;
    button.classList.add("zqs-button-press");
}

function animateSearchWindow(overlay, shell, launchRect) {
    let win = overlay.ownerDocument.defaultView;
    let animationToken = (overlay.zqsAnimationToken || 0) + 1;
    overlay.zqsAnimationToken = animationToken;
    overlay.classList.remove("zqs-entering");
    void overlay.offsetWidth;
    overlay.classList.add("zqs-entering");
    let target = shell.getBoundingClientRect();
    let fromButton = launchRect?.width > 0 && launchRect?.height > 0 && target.width > 0;
    let scale = fromButton ? .16 : .86;
    let dx = fromButton
        ? launchRect.left + launchRect.width / 2 - (target.left + target.width / 2) : 0;
    let dy = fromButton
        ? launchRect.top + launchRect.height / 2 - (target.top + target.height / 2) : 0;
    shell.style.transition = "none";
    shell.style.transformOrigin = "center center";
    overlay.zqsLaunchTransform = `translate3d(${dx}px,${dy}px,0) scale(${scale})`;
    overlay.zqsLaunchOpacity = fromButton ? ".35" : "0";
    shell.style.transform = overlay.zqsLaunchTransform;
    shell.style.opacity = overlay.zqsLaunchOpacity;
    void shell.offsetWidth;
    let frame = win.requestAnimationFrame?.bind(win) || (callback => setTimeout(callback, 16));
    frame(() => frame(() => {
        if (overlay.zitatlotseClosing || overlay.zqsAnimationToken !== animationToken) return;
        shell.style.transition = "transform .48s cubic-bezier(.2,.85,.25,1),opacity .25s ease-out";
        shell.style.opacity = "1";
        shell.style.transform = "translate3d(0,0,0) scale(1)";
    }));
}

function dismissSearchWindow(doc, overlay, escapeHandler, shell = null, reverse = false) {
    if (overlay.zitatlotseClosing) return;
    overlay.zitatlotseClosing = true;
    overlay.zqsAnimationToken = (overlay.zqsAnimationToken || 0) + 1;
    lastPanelCloseAt = Date.now();
    doc.removeEventListener("keydown", escapeHandler, true);
    overlay.classList.remove("zqs-entering");
    if (reverse && shell && overlay.zqsLaunchTransform) {
        let currentOpacity = doc.defaultView?.getComputedStyle?.(overlay).opacity || "1";
        overlay.style.animation = "none";
        overlay.style.opacity = currentOpacity;
        void overlay.offsetWidth;
        overlay.style.transition = "opacity .48s ease-in";
        shell.style.transition = "transform .48s cubic-bezier(.75,0,.8,.15),opacity .25s ease-in";
        shell.style.transform = overlay.zqsLaunchTransform;
        shell.style.opacity = overlay.zqsLaunchOpacity || "0";
        overlay.style.opacity = "0";
        setTimeout(() => overlay.remove(), 490);
    } else {
        overlay.classList.add("zqs-leaving");
        setTimeout(() => overlay.remove(), 170);
    }
}

function makeProgress(parent) {
    let doc = parent.ownerDocument;
    if (!doc.getElementById("zqs-progress-style")) {
        let style = element(doc, "style", `
            @keyframes zqs-slide { from { transform:translateX(-120%); } to { transform:translateX(300%); } }
            @keyframes zqs-stripes { to { background-position:20px 0; } }
            @keyframes zqs-page-turn {
                0%,16% { transform:rotateY(0deg) translateX(0); opacity:1; }
                50%,65% { transform:rotateY(-76deg) translateX(12px); opacity:.45; }
                95%,100% { transform:rotateY(0deg) translateX(0); opacity:1; }
            }
            .zqs-page-stack { position:relative;width:66px;height:64px;margin:0 auto 5px;perspective:220px; }
            .zqs-turning-page { position:absolute;top:5px;width:43px;height:54px;box-sizing:border-box;
                border:1px solid #8061d1;border-radius:3px;background:repeating-linear-gradient(
                to bottom,#fff 0,#fff 9px,#e4ddf4 9px,#e4ddf4 11px);box-shadow:0 2px 5px #35205a33;
                transform-origin:left center;animation:zqs-page-turn 1.8s ease-in-out infinite; }
            @media (prefers-reduced-motion:reduce) {
                .zqs-turning-page,.zqs-progress-fill { animation:none!important; }
            }
            .zqs-progress-fill { background:repeating-linear-gradient(45deg,#5b36bf 0,#5b36bf 10px,#8061d1 10px,#8061d1 20px);
                background-size:28px 28px;animation:zqs-stripes .65s linear infinite;transition:width .25s ease; }
            .zqs-progress-indeterminate { width:35%!important;animation:zqs-slide 1.2s ease-in-out infinite,zqs-stripes .65s linear infinite; }
        `);
        style.id = "zqs-progress-style";
        doc.documentElement.append(style);
    }
    let track = element(doc, "div");
    track.style.cssText = "display:none;width:100%;height:8px;margin:9px 0;border-radius:8px;overflow:hidden;background:#e8e1f5;";
    track.setAttribute("role", "progressbar");
    track.setAttribute("aria-label", ui("Fortschritt", "Progress"));
    let fill = element(doc, "div");
    fill.classList.add("zqs-progress-fill");
    fill.style.cssText = "height:100%;width:0%;border-radius:8px;";
    track.append(fill);
    parent.append(track);
    return {
        start(total) {
            track.style.display = "block";
            fill.classList.toggle("zqs-progress-indeterminate", !(total > 0));
            fill.style.width = total > 0 ? "0%" : "35%";
            if (total > 0) {
                track.setAttribute("aria-valuemin", "0");
                track.setAttribute("aria-valuemax", String(total));
                track.setAttribute("aria-valuenow", "0");
            } else {
                track.removeAttribute("aria-valuenow");
            }
        },
        update(done, total) {
            if (!(total > 0)) return this.start();
            track.style.display = "block";
            fill.classList.remove("zqs-progress-indeterminate");
            fill.style.width = Math.min(100, Math.round(100 * done / total)) + "%";
            track.setAttribute("aria-valuemin", "0");
            track.setAttribute("aria-valuemax", String(total));
            track.setAttribute("aria-valuenow", String(Math.min(done, total)));
        },
        stop() {
            track.style.display = "none";
            fill.classList.remove("zqs-progress-indeterminate");
        },
    };
}

function openSearchWindow(libraryID = selectedLibraryID() || Zotero.Libraries.userLibraryID,
    tab = "chat", launchButton = null) {
    let onSessionChange;
    let win = Zotero.getMainWindow();
    let doc = win.document;
    let launchRect = launchButton?.getBoundingClientRect?.();
    ensureWindowStyles(doc);
    let overlay = doc.getElementById("zqs-overlay");
    if (overlay?.zitatlotseClosing) {
        if (launchButton) return;
        overlay.remove();
        overlay = null;
    }
    if (overlay?.zitatlotseSetLibrary && overlay?.zitatlotseShowTab) {
        if (launchButton && overlay.zitatlotseLaunchButton === launchButton) {
            overlay.zitatlotseClose();
            return;
        }
        overlay.zitatlotseSetLibrary(libraryID);
        overlay.zitatlotseRefreshSelection?.();
        overlay.zitatlotseShowTab(tab);
        return;
    }
    ensureLocalService().catch(error => Zotero.logError(error));
    if (overlay?.zitatlotseClose) overlay.zitatlotseClose();
    else overlay?.remove();
    const add = (parent, tag, label, css, id) => {
        let node = element(doc, tag, label);
        if (css) node.style.cssText = css;
        if (tag === "button") centerButton(node);
        if (id) node.id = id;
        parent.append(node);
        return node;
    };
    const buttonStyle = "appearance:none;-moz-appearance:none;display:inline-flex;align-items:center;justify-content:center;vertical-align:middle;box-sizing:border-box;min-height:38px;text-align:center;cursor:pointer;border:1px solid #bfbaca;border-radius:6px;padding:8px 12px;background:white;color:#252333;font:14px system-ui;line-height:1.25;";
    const primaryStyle = buttonStyle + "background:#5b36bf;color:white;border:0;font-weight:700;";
    const rowStyle = "display:flex;align-items:center;gap:9px;flex-wrap:wrap;margin:10px 0;";
    const cardStyle = "background:white;border:1px solid #e2dfeb;border-radius:9px;padding:16px;margin:12px 0;";
    const inputStyle = "display:block;box-sizing:border-box;width:100%;min-height:38px;padding:8px 10px;border:1px solid #bfbaca;border-radius:6px;font:14px system-ui;";
    const field = (parent, label, inputTag, id) => {
        add(parent, "label", label, "display:block;margin:14px 0 5px;font-weight:700;");
        return add(parent, inputTag, undefined, inputStyle, id);
    };
    overlay = add(doc.documentElement, "div", undefined,
        "position:fixed;inset:0;box-sizing:border-box;z-index:2147483647;background:#14102199;display:flex;align-items:center;justify-content:center;overflow:auto;padding:clamp(8px,2vw,20px);", "zqs-overlay");
    overlay.zitatlotseLaunchButton = launchButton;
    if (launchButton) overlay.style.pointerEvents = "none";
    let shell = add(overlay, "div", undefined,
        "position:relative;box-sizing:border-box;width:min(850px,100%);max-width:100%;max-height:calc(100vh - 16px);min-width:0;min-height:0;flex:none;pointer-events:auto;", "zqs-shell");
    let panel = add(shell, "div", undefined,
        "box-sizing:border-box;width:100%;max-height:calc(100vh - 16px);min-width:0;min-height:0;overflow:auto;background:#f7f6fb;border-radius:10px;box-shadow:0 14px 50px #0006;font:14px system-ui;color:#252333;", "zqs-panel");
    let header = add(panel, "div", undefined,
        "position:sticky;top:0;z-index:2;display:flex;min-width:0;align-items:center;justify-content:space-between;gap:12px;background:#5b36bf;color:white;padding:12px clamp(10px,2vw,20px);", "zqs-header");
    add(header, "strong", "❞ Zitatlotse", "font-size:clamp(16px,3vw,21px);min-width:0;overflow-wrap:anywhere;line-height:1.2;color:white;");
    let close = add(header, "button", undefined,
        "appearance:none;-moz-appearance:none;display:inline-flex;align-items:center;justify-content:center;box-sizing:border-box;flex:none;cursor:pointer;background:#5b36bf;color:white;border:2px solid white;border-radius:6px;width:46px;height:46px;min-width:46px;min-height:46px;padding:0;", "zqs-close");
    close.setAttribute("aria-label", ui("Schließen", "Close"));
    close.setAttribute("title", ui("Schließen", "Close"));
    let closeIcon = doc.createElementNS("http://www.w3.org/2000/svg", "svg");
    closeIcon.setAttribute("viewBox", "0 0 24 24");
    closeIcon.setAttribute("width", "18");
    closeIcon.setAttribute("height", "18");
    closeIcon.style.cssText = "display:block;flex:none;pointer-events:none;";
    for (let [x1, y1, x2, y2] of [[5, 5, 19, 19], [19, 5, 5, 19]]) {
        let line = doc.createElementNS("http://www.w3.org/2000/svg", "line");
        for (let [name, value] of Object.entries({x1, y1, x2, y2, stroke:"white", "stroke-width":"2.5", "stroke-linecap":"round"})) {
            line.setAttribute(name, String(value));
        }
        closeIcon.append(line);
    }
    close.append(closeIcon);
    const closePanel = () => {
        if (overlay.zitatlotseClosing) return;
        clearTimeout(embeddingTimer);
        searchSessionListeners.delete(onSessionChange);
        doc.removeEventListener("pointerdown", outsidePress, true);
        dismissSearchWindow(doc, overlay, escapeHandler, shell, true);
    };
    overlay.zitatlotseClose = closePanel;
    // Firefox renders HTML select choices in a native popup outside the shell.
    // Its events can be retargeted to the document/XUL popup. Never dismiss the
    // search window from those events, or from Escape used to dismiss a select.
    const nativePopupEvent = event => {
        const popupTags = new Set(["select", "option", "menupopup", "menuitem", "popup"]);
        const path = event.composedPath?.() || [];
        const nodes = [event.target, event.originalTarget, ...path];
        if (nodes.some(node => popupTags.has(node?.localName?.toLowerCase()))) return true;
        const focused = doc.activeElement;
        return focused?.localName?.toLowerCase() === "select" && shell.contains(focused);
    };
    const escapeHandler = event => {
        if (event.key === "Escape" && !event.defaultPrevented && !nativePopupEvent(event)) closePanel();
    };
    const closeOnFirstPress = event => {
        event.preventDefault();
        event.stopPropagation();
        event.stopImmediatePropagation();
        closePanel();
    };
    close.addEventListener("pointerdown", closeOnFirstPress, true);
    close.addEventListener("click", closeOnFirstPress, true);
    const outsidePress = event => {
        const path = event.composedPath?.() || [];
        if (event.defaultPrevented || (event.button !== undefined && event.button !== 0) ||
            nativePopupEvent(event) || shell.contains(event.target) || path.includes(shell) ||
            (launchButton && (event.target === launchButton || path.includes(launchButton)))) return;
        // A native popup may dispatch a click on the document after its change
        // handler/confirmation. Only an actual outside pointer press can close.
        if (!event.target || event.target === doc || event.target === doc.documentElement) return;
        const rect = shell.getBoundingClientRect();
        if (Number.isFinite(event.clientX) && Number.isFinite(event.clientY) &&
            event.clientX >= rect.left && event.clientX <= rect.left + rect.width &&
            event.clientY >= rect.top && event.clientY <= rect.top + rect.height) return;
        event.preventDefault();
        event.stopPropagation();
        event.stopImmediatePropagation();
        closePanel();
    };
    doc.addEventListener("pointerdown", outsidePress, true);
    doc.addEventListener("keydown", escapeHandler, true);
    let tabs = add(panel, "div", undefined, "display:flex;justify-content:center;align-items:center;flex-wrap:wrap;min-width:0;gap:7px;padding:12px clamp(10px,2vw,20px);border-bottom:1px solid #ddd9eb;");
    let chatTab = add(tabs, "button", ui("KI-Suche", "AI search"), buttonStyle, "zqs-chat-tab");
    let searchTab = add(tabs, "button", ui("Direkte Suche", "Direct search"), buttonStyle);
    let savedTab = add(tabs, "button", ui("Gespeicherte Zitate", "Saved quotes"), buttonStyle);
    let connectionsTab = add(tabs, "button", ui("Verbindungen", "Connections"), buttonStyle);
    let preferencesTab = add(tabs, "button", ui("Einstellungen", "Settings"), buttonStyle);
    let main = add(panel, "div", undefined, "box-sizing:border-box;min-width:0;padding:clamp(10px,2vw,20px);");
    let libraryRow = add(main, "div", undefined, "display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin:4px 0 14px;");
    let libraryLabel = add(libraryRow, "label", ui("Bibliothek für Suche und Verarbeitung:",
        "Library for search and processing:"), "font-weight:700;");
    let librarySelect = add(libraryRow, "select", undefined,
        "min-width:220px;max-width:100%;min-height:38px;padding:7px 10px;border:1px solid #bfbaca;border-radius:6px;background:white;color:#252333;font:14px system-ui;");
    for (let library of Zotero.Libraries.getAll()) {
        let option = add(librarySelect, "option", library.name);
        option.value = String(library.libraryID);
    }
    let collectionRow = add(main, "div", undefined, rowStyle);
    let collectionLabel = add(collectionRow, "label", ui("Sammlung für die Suche:", "Collection to search:"), "font-weight:700;");
    collectionLabel.setAttribute("for", "zqs-collection");
    let collectionSelect = add(collectionRow, "select", undefined, inputStyle + "width:auto;min-width:220px;max-width:100%;", "zqs-collection");
    add(collectionRow, "small", ui("Einschließlich Untersammlungen", "Including subcollections"), "color:#615d6c;");
    let serviceState = add(main, "p", ui("Lokaler Suchdienst wird geprüft …", "Checking local search service…"),
        "padding:10px;border-radius:6px;background:#eeeafa;white-space:normal;");
    let serviceProgress = makeProgress(main);
    let indexState = add(main, "p", ui("Indexstand wird geladen …", "Loading index status…"),
        "color:#615d6c;");
    let indexStatusProgress = makeProgress(main);
    let status = add(main, "p", ui("Bereit", "Ready"),
        "padding:10px;border-radius:6px;background:#eeeafa;white-space:normal;margin-bottom:5px;");
    let searchVisual = add(main, "div", undefined, "display:none;padding:2px 10px 12px;");
    let pageStack = add(searchVisual, "div", undefined, undefined);
    pageStack.classList.add("zqs-page-stack");
    pageStack.setAttribute("aria-hidden", "true");
    for (let index = 0; index < 3; index++) {
        let page = add(pageStack, "div", index === 2 ? "PDF" : "", undefined);
        page.classList.add("zqs-turning-page");
        page.style.left = (index * 7) + "px";
        page.style.animationDelay = (-index * 0.6) + "s";
        page.style.fontSize = "9px";
        page.style.fontWeight = "700";
        page.style.color = "#5b36bf";
        page.style.padding = "3px";
    }
    let searchProgress = makeProgress(searchVisual);
    let chatPanel = add(main, "section");
    let chatCard = add(chatPanel, "div", undefined, cardStyle +
        "border:2px solid #0f766e;border-radius:12px;box-shadow:0 0 0 3px rgba(15,118,110,.08),0 4px 14px rgba(15,118,110,.08);", "zqs-chat-card");
    add(chatCard, "strong", ui("Frage deine Bibliothek", "Ask your library"), "font-size:17px;");
    add(chatCard, "p", ui(
        "Beschreibe in eigenen Worten, wonach du suchst. Die KI sucht in den Sprachen deiner PDFs, prüft die Fundstellen und fasst passende Belege kurz zusammen.",
        "Describe what you need. AI searches in your PDFs’ languages, reviews passages and briefly summarizes relevant evidence."),
        "line-height:1.5;color:#615d6c;");
    let chatHistory = add(chatCard, "div", undefined,
        "display:flex;flex-direction:column;gap:10px;max-height:240px;overflow-y:auto;overflow-x:hidden;scrollbar-gutter:stable;box-sizing:border-box;padding-right:14px;margin:12px 0;", "zqs-chat-history");
    let chatInput = add(chatCard, "textarea", undefined,
        inputStyle + "min-height:80px;resize:vertical;line-height:1.5;", "zqs-chat-input");
    chatInput.setAttribute("aria-label", ui("Frage an die Bibliothek", "Question for your library"));
    chatInput.setAttribute("placeholder", ui("Zum Beispiel: Suche Belege für Overfitting in diesen Studien",
        "For example: Find evidence of overfitting in these studies"));
    let chatActions = add(chatCard, "div", undefined, rowStyle);
    let chatMode = add(chatActions, "select", undefined, inputStyle + "width:auto;max-width:100%;", "zqs-chat-mode");
    chatMode.setAttribute("aria-label", ui("Suchmodus", "Search mode"));
    for (let [value, label] of [["chat", ui("KI-Suche", "AI search")], ["evidence", ui("Belege suchen", "Find evidence")]]) {
        let option = add(chatMode, "option", label);
        option.value = value;
    }
    let chatSend = add(chatActions, "button", ui("Frage senden", "Send question"), primaryStyle, "zqs-chat-send");
    let chatManage = add(chatActions, "button", ui("PDFs verarbeiten", "Process PDFs"), buttonStyle);
    let chatReset = add(chatActions, "button", ui("Chat zurücksetzen", "Reset chat"), buttonStyle, "zqs-chat-reset");
    add(chatCard, "small", ui("Der Verlauf bleibt bis zum Zurücksetzen oder Zotero-Neustart erhalten.",
        "History stays until you reset it or restart Zotero."), "display:block;color:#615d6c;");
    let activityPanel = add(chatPanel, "details", undefined, cardStyle + "display:none;", "zqs-ai-activity");
    let activitySummary = add(activityPanel, "summary", "", "cursor:pointer;font-weight:700;line-height:1.5;", "zqs-ai-activity-summary");
    let activityList = add(activityPanel, "ol", undefined, "max-height:200px;overflow:auto;padding-left:24px;margin:12px 0 0;", "zqs-ai-activity-list");
    activityPanel.addEventListener("toggle", () => {
        getSearchSession(currentLibraryID, "chat").activityExpanded = activityPanel.open;
    });
    let chatOverview = add(chatPanel, "div", undefined, cardStyle + "display:none;", "zqs-chat-relevance");
    let chatFilterRow = add(chatPanel, "label", undefined,
        "display:none;align-items:center;gap:9px;margin:16px 0 4px;cursor:pointer;", "zqs-chat-filter-row");
    let chatShowAll = add(chatFilterRow, "input", undefined,
        "appearance:auto;width:18px;height:18px;margin:0;accent-color:#5b36bf;cursor:pointer;", "zqs-chat-show-all");
    chatShowAll.setAttribute("type", "checkbox");
    add(chatFilterRow, "span", ui("Alle Treffer anzeigen", "Show all results"));
    let chatResults = add(chatPanel, "div", undefined, cardStyle, "zqs-chat-results");
    add(chatResults, "p", ui("Hier erscheinen passende Textstellen aus dieser Bibliothek.",
        "Matching passages from this library will appear here."), "margin:0;color:#615d6c;");
    let chatPagination = add(chatPanel, "nav", undefined, rowStyle + "justify-content:center;", "zqs-chat-pagination");
    chatPagination.setAttribute("aria-label", ui("Seiten der KI-Suchergebnisse", "AI search result pages"));
    let searchPanel = add(main, "section");
    let searchCard = add(searchPanel, "div", undefined, cardStyle);
    let selectedItemLabel = add(searchCard, "p", "", "margin:0 0 10px;color:#615d6c;");
    let actions = add(searchCard, "div", undefined, rowStyle);
    let single = add(actions, "button", ui("Diesen Eintrag verarbeiten", "Process this item"),
        primaryStyle + "min-height:44px;font-size:15px;");
    let scan = add(actions, "button", ui("Alle neuen/geänderten PDFs verarbeiten",
        "Process all new/changed PDFs"), buttonStyle);
    let health = add(actions, "button", ui("Suchdienst prüfen", "Check service"), buttonStyle);
    let processingProgress = makeProgress(searchCard);
    let searchRow = add(searchCard, "div", undefined, rowStyle);
    let query = add(searchRow, "input", undefined, inputStyle + "flex:1;min-width:180px;", "zqs-search-input");
    query.setAttribute("type", "search");
    query.setAttribute("placeholder", ui("Thema oder Suchfrage", "Topic or search question"));
    let search = add(searchRow, "button", ui("Suchen", "Search"), primaryStyle, "zqs-search-send");
    let searchReset = add(searchRow, "button", ui("Suche zurücksetzen", "Reset search"), buttonStyle, "zqs-search-reset");
    let directOverview = add(searchPanel, "div", undefined, cardStyle + "display:none;", "zqs-direct-relevance");
    let results = add(searchPanel, "div", undefined, cardStyle, "zqs-search-results");
    add(results, "p", ui("Hier erscheinen gefundene Zitate aus der ausgewählten Bibliothek.",
        "Quotes from the selected library will appear here."), "margin:0;color:#615d6c;");
    let searchPagination = add(searchPanel, "nav", undefined, rowStyle + "justify-content:center;", "zqs-search-pagination");
    searchPagination.setAttribute("aria-label", ui("Seiten der Suchergebnisse", "Search result pages"));
    let savedPanel = add(main, "section");
    let savedCard = add(savedPanel, "div", undefined, cardStyle);
    add(savedCard, "strong", ui("Gespeicherte Zitate", "Saved quotes"), "font-size:17px;");
    let savedSearch = add(savedCard, "input", undefined, inputStyle + "margin:12px 0;");
    savedSearch.setAttribute("type", "search");
    savedSearch.setAttribute("placeholder", ui("Zitate, Titel und Notizen durchsuchen", "Search quotes, titles and notes"));
    let savedProgress = makeProgress(savedCard);
    let savedResults = add(savedPanel, "div", undefined, cardStyle);
    let settingsPanel = add(main, "section");
    let settingsCard = add(settingsPanel, "div", undefined, cardStyle);
    let provider = field(settingsCard, ui("Anbieter für die Auswahl der Fundstellen",
        "Provider for selecting passages"), "select", "zqs-provider");
    for (let [value, label] of [["none", ui("Kein LLM – lokale Suche", "No LLM – local search")],
        ["openai", "OpenAI"], ["anthropic", "Anthropic"], ["deepseek", "DeepSeek"],
        ["ollama", ui("Ollama (lokal)", "Ollama (local)")]]) {
        let option = add(provider, "option", label);
        option.value = value;
    }
    let model = field(settingsCard, ui("Modell", "Model"), "input", "zqs-llm-model");
    model.setAttribute("autocomplete", "off");
    let modelChoices = field(settingsCard, ui("Modell auswählen", "Choose a model"), "select", "zqs-llm-model-options");
    let modelInfo = add(settingsCard, "small", "", "display:block;margin-top:5px;color:#615d6c;", "zqs-llm-model-info");
    let refreshModels = add(settingsCard, "button", ui("Modellliste aktualisieren", "Refresh model list"),
        buttonStyle + "margin-top:8px;", "zqs-model-refresh");
    let modelProgress = makeProgress(settingsCard);
    let keyBox = add(settingsCard, "div");
    let apiKey = field(keyBox, ui("API-Schlüssel", "API key"), "input", "zqs-api-key");
    apiKey.setAttribute("type", "password");
    apiKey.setAttribute("autocomplete", "off");
    let keyState = add(keyBox, "small", ui("Noch kein Schlüssel gespeichert.", "No key saved yet."),
        "color:#615d6c;");
    let ollamaBox = add(settingsCard, "div");
    let ollamaURL = field(ollamaBox, ui("Lokale Ollama-Adresse", "Local Ollama address"), "input");
    ollamaURL.value = "http://127.0.0.1:11434";
    add(ollamaBox, "small", ui("Ollama muss laufen und das Modell installiert sein.",
        "Ollama must be running and the model installed."), "color:#615d6c;");
    let settingsActions = add(settingsCard, "div", undefined, rowStyle);
    let save = add(settingsActions, "button", ui("Verbindung speichern", "Save connection"), primaryStyle);
    let test = add(settingsActions, "button", ui("Verbindung testen", "Test connection"), buttonStyle);
    let settingsProgress = makeProgress(settingsCard);
    add(settingsCard, "small", ui(
        "Bei einer Cloud-Suche werden die Frage und bis zu acht Fundstellen an den gewählten Anbieter gesendet. Für Suchanfrage und Auswertung können zwei Anfragen anfallen. Ein Verbindungstest kann eine kleine Anfrage abrechnen.",
        "Cloud search sends the question and up to eight passages to the selected provider. Query planning and result review may use two requests. A connection test may incur a small charge."),
        "color:#615d6c;");
    let preferencesPanel = add(main, "section");
    let preferencesCard = add(preferencesPanel, "div", undefined, cardStyle);
    add(preferencesCard, "strong", ui("Zitate exportieren", "Export quotations"), "font-size:17px;");
    let citationStyle = field(preferencesCard, ui("Zitierstil", "Citation style"), "select");
    let simpleOption = add(citationStyle, "option", ui("Einfacher Kurzbeleg (Autor, Jahr, Seite)",
        "Simple citation (author, year, page)"));
    simpleOption.value = "simple";
    try {
        for (let style of Zotero.Styles.getVisible()) {
            let option = add(citationStyle, "option", style.title);
            option.value = style.styleID;
        }
    } catch (error) { Zotero.logError(error); }
    let savedCitationStyle = Zotero.Prefs.get("extensions.zitatlotse.citationStyle", true) || "simple";
    citationStyle.value = Array.from(citationStyle.options).some(option => option.value === savedCitationStyle)
        ? savedCitationStyle : "simple";
    add(preferencesCard, "p", ui(
        "Beim Kopieren wird die Originaltextstelle mit einem Kurzbeleg im ausgewählten Zotero-Stil ausgegeben. Die PDF-Seite wird als Seitenangabe übernommen.",
        "Copying includes the original passage and a citation in the selected Zotero style. The PDF page is used as the page locator."),
        "line-height:1.5;color:#615d6c;");
    let agentCard = add(preferencesPanel, "div", undefined, cardStyle);
    add(agentCard, "strong", ui("Mehrstufige KI-Suche", "Multi-step AI search"), "font-size:17px;");
    let agentLabel = add(agentCard, "label", undefined, rowStyle + "cursor:pointer;");
    let agentEnabled = add(agentLabel, "input", undefined,
        "appearance:auto;width:18px;height:18px;margin:0;accent-color:#5b36bf;", "zqs-agent-enabled");
    agentEnabled.setAttribute("type", "checkbox");
    add(agentLabel, "span", ui("Mehrstufige Suche erlauben (Agentic Calls)", "Allow multi-step search (agentic calls)"));
    let agentSteps = field(agentCard, ui("Maximale Suchschritte pro Frage", "Maximum search steps per question"), "select", "zqs-agent-steps");
    for (let count = 1; count <= 6; count++) {
        let option = add(agentSteps, "option", String(count));
        option.value = String(count);
    }
    let saveAgentSettings = add(agentCard, "button", ui("Sucheinstellungen speichern", "Save search settings"),
        primaryStyle + "margin-top:12px;", "zqs-agent-save");
    let agentSettingsProgress = makeProgress(agentCard);
    add(agentCard, "p", ui(
        "Die KI kann Fundstellen lesen, ihre Suchfrage anpassen und weitere Aspekte suchen. Standard: 3 Suchschritte, danach eine Zusammenfassung. Die Suche bleibt in der gewählten Bibliothek. Unterstützt das Modell keine Funktionsaufrufe, wird die normale KI-Suche verwendet. Zusätzliche Schritte können länger dauern und bei Cloud-Anbietern mehr kosten.",
        "AI can read passages, refine its query and search other aspects. Default: 3 search steps, followed by a summary. Search stays in the selected library. If the model cannot use function calls, standard AI search is used. Additional steps can take longer and cost more with cloud providers."),
        "line-height:1.5;color:#615d6c;");
    agentEnabled.disabled = agentSteps.disabled = saveAgentSettings.disabled = true;
    let activityCard = add(preferencesPanel, "div", undefined, cardStyle);
    let activitySettingLabel = add(activityCard, "label", undefined, rowStyle + "cursor:pointer;");
    let activityEnabled = add(activitySettingLabel, "input", undefined,
        "appearance:auto;width:18px;height:18px;margin:0;accent-color:#5b36bf;", "zqs-show-ai-activity");
    activityEnabled.setAttribute("type", "checkbox");
    activityEnabled.checked = showAIActivity;
    activityEnabled.disabled = true;
    add(activitySettingLabel, "span", ui("KI-Ablauf anzeigen", "Show AI activity"));
    add(activityCard, "p", ui("Zeigt während der KI- und Belegsuche Suchanfragen, Tool-Aufrufe, erhaltene Ergebnisse und die Auswertung. Änderungen werden sofort gespeichert.",
        "Shows queries, tool calls, received results and review progress during AI and evidence searches. Changes are saved immediately."), "line-height:1.5;color:#615d6c;");
    let embeddingCard = add(preferencesPanel, "div", undefined, cardStyle);
    add(embeddingCard, "strong", ui("Lokales Embedding-Modell", "Local embedding model"), "font-size:17px;");
    let embeddingChoice = field(embeddingCard, ui("Modell für Dokumente und Suchanfragen", "Model for documents and queries"), "select", "zqs-embedding-model");
    add(embeddingCard, "p", ui("Wähle ein Embedding-Modell, das alle Sprachen der durchsuchten Dokumente unterstützt. Bei Fragen in einer anderen Sprache muss das Modell sprachübergreifende Suche unterstützen oder die Suchanfrage übersetzt werden. Eine übersetzte Frage ersetzt keine fehlende Unterstützung der Dokumentsprache.",
        "Choose an embedding model that supports all languages of the documents you search. For questions in another language, use a cross-language model or translate the query. Translating the question does not replace support for the document language."),
        "padding:12px;border:1px solid #ddd3f5;border-radius:8px;background:#f4efff;line-height:1.5;font-size:13px;",
        "zqs-embedding-language-hint");
    let embeddingDescription = add(embeddingCard, "p", "", "color:#615d6c;line-height:1.5;", "zqs-embedding-description");
    let embeddingDetails = add(embeddingCard, "button", ui("Modelldetails auf Hugging Face", "Model details on Hugging Face"), buttonStyle, "zqs-embedding-details");
    embeddingDetails.disabled = true;
    let customEdit = add(embeddingCard, "button", ui("Eingabeprofil bearbeiten", "Edit input profile"), buttonStyle + "margin-left:6px;display:none;", "zqs-custom-edit");
    let embeddingStatus = add(embeddingCard, "p", ui("Modelle werden geladen …", "Loading models…"), "line-height:1.5;", "zqs-embedding-status");
    let embeddingProgress = makeProgress(embeddingCard);
    let embeddingRetry = add(embeddingCard, "button", ui("Neuberechnung erneut starten", "Retry rebuilding"), buttonStyle, "zqs-embedding-retry");
    embeddingRetry.style.display = "none";
    add(embeddingCard, "small", ui(
        "Ein Wechsel berechnet alle gespeicherten Text-Chunks und Themenvektoren in allen Bibliotheken neu. Gespeicherte Zitate bleiben erhalten. Das Modell wird bei Bedarf heruntergeladen.",
        "Switching recalculates all stored chunks and topic vectors in every library. Saved quotes are preserved. The model is downloaded if needed."), "color:#615d6c;line-height:1.5;");
    embeddingChoice.disabled = true;
    let customEmbedding = add(embeddingCard, "details", undefined, "margin-top:16px;padding:14px;border:1px solid #ddd9eb;border-radius:8px;background:#faf9ff;", "zqs-custom-embedding");
    add(customEmbedding, "summary", ui("Eigenes Hugging-Face-Modell hinzufügen", "Add a custom Hugging Face model"), "cursor:pointer;font-weight:700;");
    add(customEmbedding, "p", ui("Gib die Modell-ID oder den Link zur Modellseite ein. Unterstützt werden lokale, mit SentenceTransformers kompatible Text-Embedding-Modelle. Frage- und Dokumentprofil müssen zur Modellbeschreibung passen.",
        "Enter the model ID or its model-page link. Local text embedding models compatible with SentenceTransformers are supported. Query and document formats must match the model card."), "font-size:13px;line-height:1.5;color:#615d6c;");
    add(customEmbedding, "small", ui("Klassifikationsmodelle wie FinBERT eignen sich nicht für diese Suche und werden abgelehnt. Für deutsche Fragen zu englischen Papers ein mehrsprachiges Embedding-Modell verwenden.",
        "Classification models such as FinBERT are unsuitable for this search and are rejected. Use a multilingual embedding model for questions and papers in different languages."),
        "display:block;margin-bottom:10px;color:#615d6c;line-height:1.5;");
    let customRepo = field(customEmbedding, ui("Hugging-Face-Modell", "Hugging Face model"), "input", "zqs-custom-repo");
    customRepo.setAttribute("placeholder", "sentence-transformers/all-MiniLM-L12-v2");
    let customProfile = field(customEmbedding, ui("Eingabeprofil", "Input profile"), "select", "zqs-custom-profile");
    for (let [value, label] of [["auto", ui("Automatisch – Frage-/Dokument-Prompts aus dem Modell", "Automatic – model's query/document prompts")],
        ["plain", ui("Ohne Präfix – z. B. MiniLM, BGE M3", "No prefix – e.g. MiniLM, BGE M3")],
        ["e5", ui("E5 – query: / passage:", "E5 – query: / passage:")],
        ["bge", ui("BGE Englisch – Suchanweisung für Fragen", "BGE English – retrieval instruction for queries")],
        ["qwen", ui("Qwen Embedding – Instruct / Query", "Qwen Embedding – Instruct / Query")],
        ["custom", ui("Eigene Frage-/Dokument-Präfixe", "Custom query/document prefixes")]]) {
        let option = add(customProfile, "option", label); option.value = value;
    }
    customProfile.value = "auto";
    let customPrefixes = add(customEmbedding, "div", undefined, "display:none;");
    let customQueryPrefix = field(customPrefixes, ui("Frage-Präfix (inkl. Leerzeichen/Zeilenumbrüchen)", "Query prefix (including spaces/newlines)"), "textarea", "zqs-custom-query-prefix");
    let customPassagePrefix = field(customPrefixes, ui("Dokument-Präfix", "Document prefix"), "textarea", "zqs-custom-passage-prefix");
    customProfile.addEventListener("change", () => { customPrefixes.style.display = customProfile.value === "custom" ? "block" : "none"; });
    let customRevision = field(customEmbedding, ui("Modellversion (optional: Branch oder Commit)", "Model revision (optional: branch or commit)"), "input", "zqs-custom-revision");
    let customBatch = field(customEmbedding, ui("Texte pro Verarbeitungsschritt (1–64)", "Texts per processing batch (1–64)"), "input", "zqs-custom-batch");
    customBatch.setAttribute("type", "number"); customBatch.setAttribute("min", "1"); customBatch.setAttribute("max", "64"); customBatch.value = "8";
    let customLoad = add(customEmbedding, "button", ui("Modell laden und verwenden", "Load and use model"), primaryStyle + "margin-top:12px;", "zqs-custom-load");
    add(customEmbedding, "small", ui("Das Modell wird einmal heruntergeladen und danach lokal genutzt. Eigener Python-Code aus Modell-Repositories wird nicht ausgeführt. Große Modelle benötigen entsprechend RAM/VRAM.",
        "The model downloads once and then runs locally. Custom Python code from model repositories is not executed. Large models require sufficient RAM/VRAM."), "display:block;margin-top:10px;line-height:1.5;color:#615d6c;");
    let embeddingModels = [], activeEmbedding = "", embeddingTimer;
    let currentLibraryID = libraryID;
    const report = message => { status.textContent = message; };
    const modelPlaceholder = label => {
        modelChoices.replaceChildren();
        let option = add(modelChoices, "option", label);
        option.value = "";
        modelChoices.value = "";
    };
    modelPlaceholder(ui("Modelle laden …", "Load models…"));
    const updateSelectedItem = () => {
        let item = Zotero.getActiveZoteroPane()?.getSelectedItems()?.[0];
        single.textContent = item?.isAttachment() ? ui("Diese PDF verarbeiten", "Process this PDF")
            : ui("Diesen Eintrag verarbeiten", "Process this item");
        selectedItemLabel.textContent = item
            ? ui("Ausgewählter Eintrag: ", "Selected item: ") + (item.getField("title") || item.attachmentFilename || item.key)
            : ui("Bitte links einen Eintrag oder eine PDF-Datei auswählen.", "Select an item or PDF on the left.");
    };
    overlay.zitatlotseRefreshSelection = updateSelectedItem;
    const refreshCollections = () => {
        let selected = libraryCollections.get(currentLibraryID) || 0;
        collectionSelect.replaceChildren();
        let all = add(collectionSelect, "option", ui("Gesamte Bibliothek", "Entire library"));
        all.value = "0";
        let available = Zotero.Collections?.getByLibrary(currentLibraryID, true) || [];
        for (let collection of available) {
            let option = add(collectionSelect, "option", "  ".repeat(Math.max(0, collection.level || 0)) + collection.name);
            option.value = String(collection.id);
        }
        if (selected && !available.some(collection => collection.id === selected)) {
            selected = 0;
            resetSearchSession(currentLibraryID, "chat");
            resetSearchSession(currentLibraryID, "direct");
        }
        libraryCollections.set(currentLibraryID, selected);
        collectionSelect.value = String(selected);
    };
    collectionSelect.addEventListener("change", () => {
        libraryCollections.set(currentLibraryID, Number(collectionSelect.value));
        for (let mode of ["chat", "direct"]) {
            let old = getSearchSession(currentLibraryID, mode);
            if (old.jobID) request(old.jobEndpoint + "/cancel", {library_id:currentLibraryID,job_id:old.jobID,
                collection_id:old.scope.collection_id || 0}).catch(error => Zotero.logError(error));
            resetSearchSession(currentLibraryID, mode);
            let fresh = getSearchSession(currentLibraryID, mode);
            fresh.draft = old.draft;
            fresh.searchMode = old.searchMode;
            notifySearchSession(currentLibraryID, mode);
        }
        report(ui("Suchbereich geändert. Neue Anfragen suchen in der gewählten Sammlung.", "Search scope changed. New queries search the selected collection."));
    });
    overlay.zitatlotseSetLibrary = id => {
        let library = Zotero.Libraries.get(Number(id));
        if (!library) return;
        let changed = currentLibraryID !== library.libraryID;
        currentLibraryID = library.libraryID;
        librarySelect.value = String(currentLibraryID);
        refreshCollections();
        renderSearchSession("chat");
        renderSearchSession("direct");
        if (changed) savedSearch.value = "";
        refreshStatus();
        if (savedPanel.style.display !== "none") loadSaved();
    };
    librarySelect.addEventListener("change", () => {
        overlay.zitatlotseSetLibrary(librarySelect.value);
        report(ui("Bibliothek gewählt: ", "Library selected: ") + Zotero.Libraries.get(currentLibraryID).name + ".");
    });
    overlay.zitatlotseShowTab = name => {
        let isChat = name === "chat";
        let isConnections = name === "settings";
        let isPreferences = name === "preferences";
        let isSaved = name === "saved";
        if (isChat) chatCard.after(status, searchVisual);
        else if (name === "search") searchCard.after(status, searchVisual);
        else main.append(status, searchVisual);
        chatPanel.style.display = isChat ? "block" : "none";
        searchPanel.style.display = name === "search" ? "block" : "none";
        savedPanel.style.display = isSaved ? "block" : "none";
        settingsPanel.style.display = isConnections ? "block" : "none";
        preferencesPanel.style.display = isPreferences ? "block" : "none";
        chatTab.style.background = isChat ? "#e6dcff" : "white";
        searchTab.style.background = name === "search" ? "#e6dcff" : "white";
        savedTab.style.background = isSaved ? "#e6dcff" : "white";
        connectionsTab.style.background = isConnections ? "#e6dcff" : "white";
        preferencesTab.style.background = isPreferences ? "#e6dcff" : "white";
        if (isChat || name === "search") renderSearchSession(isChat ? "chat" : "direct");
        else refreshSearchProgress();
        (isPreferences ? citationStyle : isConnections ? provider : isSaved ? savedSearch : isChat ? chatInput : query).focus();
        if (isConnections) loadSettings();
        if (isSaved) loadSaved();
        if (isPreferences) { loadSearchSettings(); loadEmbeddingModels(); }
    };
    const updateProvider = (providerChanged = false) => {
        keyBox.style.display = ["openai", "anthropic", "deepseek"].includes(provider.value) ? "block" : "none";
        ollamaBox.style.display = provider.value === "ollama" ? "block" : "none";
        model.value = modelForProvider(provider.value, model.value, providerChanged);
        modelPlaceholder(ui("Modelle laden …", "Load models…"));
        modelInfo.textContent = "";
    };
    const get = async path => {
        try {
            let response = await serviceRequest("GET", path, {timeout:5000});
            return JSON.parse(response.responseText);
        } catch (error) { throw serviceError(error); }
    };
    let modelListRequest = 0;
    const showModelListing = listing => {
        modelPlaceholder(ui("Modell auswählen …", "Choose a model…"));
        for (let entry of listing.models) {
            let option = add(modelChoices, "option", entry.label); option.value = entry.id;
        }
        if (listing.models.some(entry => entry.id === model.value)) modelChoices.value = model.value;
        if (listing.source === "suggestions") {
            const reasons = {
                no_key: ui("API-Schlüssel eingeben, um die verfügbaren Modelle abzurufen.", "Enter an API key to fetch available models."),
                key_rejected: ui("Der API-Schlüssel wurde abgelehnt. Bitte prüfen.", "The API key was rejected. Please check it."),
                unavailable: ui("Die Anbieter-Liste ist derzeit nicht erreichbar.", "The provider list is currently unavailable."),
                empty: ui("Die Anbieter-Liste enthält keine passenden Textmodelle.", "The provider list contains no suitable text models."),
            };
            modelInfo.textContent = ui("Modellvorschläge; Zugang wurde nicht geprüft. ", "Model suggestions; access has not been verified. ") +
                (reasons[listing.reason] || reasons.unavailable);
        } else {
            modelInfo.textContent = listing.models.length + (listing.source === "installed"
                ? listing.models.length === 1 ? ui(" lokal installiertes Modell.", " locally installed model.") : ui(" lokal installierte Modelle.", " locally installed models.")
                : listing.models.length === 1 ? ui(" vom Anbieter abgerufenes Modell.", " model fetched from the provider.") : ui(" vom Anbieter abgerufene Modelle.", " models fetched from the provider."));
        }
    };
    const loadModels = async () => {
        let chosenProvider = provider.value;
        let sequence = ++modelListRequest;
        if (chosenProvider === "none") {
            modelPlaceholder(ui("Kein Anbieter gewählt", "No provider selected"));
            modelInfo.textContent = "";
            modelProgress.stop();
            return;
        }
        if (MODEL_SUGGESTIONS[chosenProvider]) showModelListing({source:"suggestions", reason:"unavailable",
            models:MODEL_SUGGESTIONS[chosenProvider].map(id => ({id,label:id}))});
        else { modelPlaceholder(ui("Modelle werden geladen …", "Loading models…")); modelInfo.textContent = ""; }
        modelProgress.start();
        try {
            let listing = await request("/models", {
                provider: chosenProvider, api_key: apiKey.value.trim(),
                ollama_url: ollamaURL.value.trim(),
            });
            if (sequence !== modelListRequest || provider.value !== chosenProvider) return;
            if (!listing.models?.length && MODEL_SUGGESTIONS[chosenProvider]) listing = {source:"suggestions",reason:"empty",
                models:MODEL_SUGGESTIONS[chosenProvider].map(id=>({id,label:id}))};
            showModelListing(listing);
        } catch (error) {
            if (sequence !== modelListRequest || provider.value !== chosenProvider) return;
            if (MODEL_SUGGESTIONS[chosenProvider]) showModelListing({source:"suggestions",reason:"unavailable",
                models:MODEL_SUGGESTIONS[chosenProvider].map(id=>({id,label:id}))});
            else { modelPlaceholder(ui("Keine Modellliste verfügbar", "Model list unavailable")); modelInfo.textContent = error.message; }
        } finally {
            if (sequence === modelListRequest) modelProgress.stop();
        }
    };
    const refreshStatus = async () => {
        let requestedLibraryID = currentLibraryID;
        indexStatusProgress.start();
        try {
            let data = await get("/status?library_id=" + requestedLibraryID);
            if (requestedLibraryID === currentLibraryID) {
                indexState.textContent = ui("In dieser Bibliothek: ", "In this library: ") +
                    data.documents + " PDFs · " + data.chunks +
                    ui(" durchsuchbare Text-Chunks · ", " searchable text chunks · ") +
                    (data.topic_documents || 0) + ui(" PDFs mit Themenmerkmalen.",
                        " PDFs with topic tags.");
            }
        } catch {
            indexState.textContent = ui("Indexstand derzeit nicht verfügbar.", "Index status is currently unavailable.");
        } finally { indexStatusProgress.stop(); }
    };
    const loadSettings = async () => {
        settingsProgress.start();
        try {
            let saved = await get("/settings");
            provider.value = saved.provider;
            model.value = saved.model;
            ollamaURL.value = saved.ollama_url;
            apiKey.value = "";
            keyState.textContent = saved.has_key ? ui("Ein Schlüssel ist im System gespeichert.", "A key is saved in the system.")
                : ui("Noch kein Schlüssel gespeichert.", "No key saved yet.");
            updateProvider();
            loadModels();
        } catch (error) {
            if (settingsPanel.style.display !== "none") report(ui("Einstellungen konnten nicht geladen werden: ",
                "Could not load settings: ") + error.message);
        } finally { settingsProgress.stop(); }
    };
    const loadSearchSettings = async () => {
        agentEnabled.disabled = agentSteps.disabled = saveAgentSettings.disabled = true;
        agentSettingsProgress.start();
        try {
            let saved = await get("/settings");
            if (typeof saved.agentic_enabled !== "boolean") throw new Error(ui(
                "Bitte den lokalen Suchdienst aus dem aktuellen Quellcode-Paket aktualisieren.",
                "Update the local search service from the current source package."));
            showAIActivity = saved.show_ai_activity !== false;
            activityEnabled.checked = showAIActivity;
            activityEnabled.disabled = false;
            for (let id of searchSessions.keys()) notifySearchSession(id, "chat");
            agentEnabled.checked = saved.agentic_enabled;
            agentSteps.value = String(saved.agentic_max_steps);
            agentEnabled.disabled = saveAgentSettings.disabled = false;
            agentSteps.disabled = !agentEnabled.checked;
        } catch (error) { report(ui("Sucheinstellungen konnten nicht geladen werden: ",
            "Could not load search settings: ") + error.message); }
        finally { agentSettingsProgress.stop(); }
    };
    const describeEmbedding = () => {
        let entry = embeddingModels.find(entry => entry.id === embeddingChoice.value);
        embeddingDescription.textContent = (entry?.[uiLang()] || "") + (entry?.dimensions
            ? " · " + entry.dimensions + ui(" Dimensionen", " dimensions") : "");
        if (entry?.compatibility?.[uiLang()]) embeddingDescription.textContent += " · " + entry.compatibility[uiLang()];
        embeddingDetails.disabled = !entry?.url?.startsWith("https://huggingface.co/");
        customEdit.style.display = entry?.custom ? "inline-flex" : "none";
    };
    customEdit.addEventListener("click", () => {
        let entry = embeddingModels.find(entry => entry.id === embeddingChoice.value);
        if (!entry?.custom) return;
        customRepo.value = entry.id;
        customProfile.value = entry.input_format || "auto";
        customRevision.value = entry.revision || "";
        customBatch.value = String(entry.batch_size || 8);
        customQueryPrefix.value = entry.query_prefix || "";
        customPassagePrefix.value = entry.passage_prefix || "";
        customPrefixes.style.display = customProfile.value === "custom" ? "block" : "none";
        customEmbedding.open = true;
        customRepo.focus();
    });
    embeddingDetails.addEventListener("click", () => {
        let entry = embeddingModels.find(entry => entry.id === embeddingChoice.value);
        if (entry?.url?.startsWith("https://huggingface.co/")) Zotero.launchURL(entry.url);
    });
    const loadEmbeddingModels = async () => {
        clearTimeout(embeddingTimer);
        try {
            let data = await get("/embedding-models");
            if (overlay.zitatlotseClosing) return;
            embeddingModels = data.models || [];
            activeEmbedding = data.active_model;
            let job = data.job || {};
            let busy = ["loading", "rebuilding"].includes(job.state);
            embeddingChoice.replaceChildren();
            for (let entry of embeddingModels) {
                let option = add(embeddingChoice, "option", entry.label + (entry.id === activeEmbedding ? ui(" · Aktiv", " · Active") : ""));
                if (entry.compatibility?.status === "incompatible") {
                    option.textContent += ui(" · Nicht geeignet", " · Unsuitable");
                    option.disabled = true;
                }
                option.value = entry.id;
            }
            if (!embeddingModels.some(entry => entry.id === activeEmbedding)) {
                let option = add(embeddingChoice, "option", activeEmbedding);
                option.value = activeEmbedding;
            }
            embeddingChoice.value = busy ? job.model : activeEmbedding;
            describeEmbedding();
            embeddingChoice.disabled = busy;
            for (let input of [customRepo, customProfile, customRevision, customBatch, customQueryPrefix, customPassagePrefix, customLoad]) input.disabled = busy;
            embeddingRetry.style.display = job.state === "failed" ? "inline-flex" : "none";
            embeddingRetry.disabled = busy;
            if (busy) {
                embeddingStatus.textContent = job.state === "loading" ? ui("Modell wird geladen …", "Loading model…")
                    : ui("Datenbank wird neu berechnet: ", "Recalculating database: ") + job.completed + " / " + job.total;
                embeddingProgress.start(job.state === "rebuilding" ? job.total : undefined);
                if (job.state === "rebuilding") embeddingProgress.update(job.completed, job.total);
                embeddingTimer = setTimeout(loadEmbeddingModels, 1000);
            } else {
                embeddingProgress.stop();
                embeddingStatus.textContent = job.state === "failed"
                    ? ui("Neuberechnung fehlgeschlagen. Bisheriger Index bleibt aktiv: ", "Rebuild failed. Previous index remains active: ") + job.error
                    : ui("Aktives Modell: ", "Active model: ") + activeEmbedding;
                let compatibility = data.active_compatibility;
                if (compatibility?.[uiLang()]) embeddingStatus.textContent += " · " + compatibility[uiLang()];
                embeddingStatus.style.color = compatibility?.status === "incompatible" ? "#b42318" : "";
            }
            let signature = data.active_signature || activeEmbedding;
            if (knownEmbeddingModel && knownEmbeddingModel !== signature) {
                // Preserve conversation/drafts, invalidate cached pages and any pending old-model replies.
                for (let [id, sessions] of searchSessions) for (let mode of ["chat", "direct"]) {
                    let previous = sessions[mode];
                    sessions[mode] = {...newSearchSession(),messages:previous.messages,draft:previous.draft,
                        searchMode:previous.searchMode,status:ui("Modell aktualisiert. Bitte erneut suchen.", "Model updated. Please search again.")};
                    notifySearchSession(id, mode);
                }
                refreshStatus();
            }
            knownEmbeddingModel = signature;
        } catch (error) {
            embeddingProgress.stop();
            embeddingChoice.disabled = true;
            embeddingStatus.textContent = ui("Embedding-Modelle konnten nicht geladen werden: ", "Could not load embedding models: ") + error.message;
        }
    };
    const changeEmbedding = async (force = false) => {
        let selected = embeddingChoice.value;
        describeEmbedding();
        if (selected === activeEmbedding && force !== true) return;
        let label = embeddingModels.find(entry => entry.id === selected)?.label || selected;
        if (!confirmEmbeddingChange(label, embeddingDescription.textContent)) {
            embeddingChoice.value = activeEmbedding;
            describeEmbedding();
            return;
        }
        embeddingChoice.disabled = true;
        embeddingProgress.start();
        try {
            await request("/embedding/rebuild", {model:selected,confirmed:true});
            await loadEmbeddingModels();
        } catch (error) {
            embeddingChoice.disabled = false;
            embeddingProgress.stop();
            embeddingStatus.textContent = ui("Modellwechsel fehlgeschlagen: ", "Model change failed: ") + error.message;
        }
    };
    embeddingChoice.addEventListener("change", () => changeEmbedding());
    customLoad.addEventListener("click", async () => {
        let id = customRepo.value.trim();
        let batch = Number(customBatch.value);
        if (!id || !Number.isInteger(batch) || batch < 1 || batch > 64) {
            embeddingStatus.textContent = ui("Bitte eine Modell-ID und eine Batchgröße von 1 bis 64 eingeben.", "Enter a model ID and a batch size from 1 to 64.");
            return;
        }
        if (!confirmEmbeddingChange(id, ui("Eigenes Hugging-Face-Modell. Download und Prüfung vor der Neuberechnung.", "Custom Hugging Face model. Download and validation before rebuilding."))) return;
        customLoad.disabled = true;
        embeddingChoice.disabled = true;
        embeddingProgress.start();
        embeddingStatus.textContent = ui("Modell wird geladen und geprüft …", "Loading and checking model…");
        try {
            await request("/embedding/rebuild", {confirmed:true,custom_model:{id,input_format:customProfile.value,
                revision:customRevision.value.trim(),batch_size:batch,query_prefix:customQueryPrefix.value,passage_prefix:customPassagePrefix.value}});
            await loadEmbeddingModels();
        } catch (error) {
            embeddingProgress.stop();
            customLoad.disabled = false;
            embeddingChoice.disabled = false;
            embeddingStatus.textContent = ui("Modell konnte nicht geladen werden: ", "Could not load model: ") + error.message;
        }
    });
    embeddingRetry.addEventListener("click", async () => {
        let data = await get("/embedding-models");
        embeddingChoice.value = data.job.model;
        await changeEmbedding(true);
    });
    activityEnabled.addEventListener("change", async () => {
        let previous = showAIActivity;
        showAIActivity = activityEnabled.checked;
        activityEnabled.disabled = true;
        for (let id of searchSessions.keys()) notifySearchSession(id, "chat");
        try {
            await request("/settings", {show_ai_activity:showAIActivity});
            report(ui("Anzeigeeinstellung gespeichert.", "Display preference saved."));
        } catch (error) {
            showAIActivity = previous;
            activityEnabled.checked = previous;
            for (let id of searchSessions.keys()) notifySearchSession(id, "chat");
            report(ui("Speichern fehlgeschlagen: ", "Save failed: ") + error.message);
        } finally { activityEnabled.disabled = false; }
    });
    agentEnabled.addEventListener("change", () => { agentSteps.disabled = !agentEnabled.checked; });
    saveAgentSettings.addEventListener("click", async () => {
        saveAgentSettings.disabled = true;
        agentSettingsProgress.start();
        try {
            await request("/settings", {agentic_enabled:agentEnabled.checked,
                agentic_max_steps:Number(agentSteps.value)});
            report(ui("Sucheinstellungen gespeichert.", "Search settings saved."));
        } catch (error) { report(ui("Speichern fehlgeschlagen: ", "Save failed: ") + error.message); }
        finally { saveAgentSettings.disabled = false; agentSettingsProgress.stop(); }
    });
    const saveSettings = async () => {
        save.disabled = true;
        settingsProgress.start();
        try {
            let saved = await request("/settings", {
                provider:provider.value, model:model.value.trim(), api_key:apiKey.value.trim(),
                ollama_url:ollamaURL.value.trim()
            });
            apiKey.value = "";
            keyState.textContent = saved.has_key ? ui("Schlüssel ist im System gespeichert.", "Key is saved in the system.")
                : ui("Noch kein Schlüssel gespeichert.", "No key saved yet.");
            report(ui("Verbindung gespeichert: ", "Connection saved: ") + saved.provider + ".");
            loadModels();
            return true;
        } catch (error) { report(ui("Speichern fehlgeschlagen: ", "Save failed: ") + error.message); return false; }
        finally { save.disabled = false; settingsProgress.stop(); }
    };
    chatTab.addEventListener("click", () => overlay.zitatlotseShowTab("chat"));
    searchTab.addEventListener("click", () => overlay.zitatlotseShowTab("search"));
    savedTab.addEventListener("click", () => overlay.zitatlotseShowTab("saved"));
    connectionsTab.addEventListener("click", () => overlay.zitatlotseShowTab("settings"));
    preferencesTab.addEventListener("click", () => overlay.zitatlotseShowTab("preferences"));
    citationStyle.addEventListener("change", () => {
        Zotero.Prefs.set("extensions.zitatlotse.citationStyle", citationStyle.value, true);
        report(ui("Zitierstil gespeichert: ", "Citation style saved: ") + citationStyle.selectedOptions[0].textContent + ".");
    });
    provider.addEventListener("change", () => { apiKey.value = ""; updateProvider(true); loadModels(); });
    modelChoices.addEventListener("change", () => {
        if (modelChoices.value) model.value = modelChoices.value;
    });
    model.addEventListener("input", () => {
        if (modelChoices.value !== model.value) modelChoices.value = "";
    });
    refreshModels.addEventListener("click", loadModels);
    apiKey.addEventListener("change", () => { if (apiKey.value.trim()) loadModels(); });
    ollamaURL.addEventListener("change", () => { if (provider.value === "ollama") loadModels(); });
    save.addEventListener("click", saveSettings);
    test.addEventListener("click", async () => {
        if (!await saveSettings()) return;
        test.disabled = true;
        settingsProgress.start();
        report(ui("Verbindung wird geprüft …", "Checking connection…"));
        try {
            await request("/test-connection", {});
            report(ui("Verbindung und Modell antworten.", "Connection and model are responding."));
        } catch (error) { report(ui("Verbindung fehlgeschlagen: ", "Connection failed: ") + error.message); }
        finally { test.disabled = false; settingsProgress.stop(); }
    });
    health.addEventListener("click", async () => {
        serviceState.textContent = ui("Lokaler Suchdienst wird geprüft …", "Checking local search service…");
        serviceProgress.start();
        try {
            let healthResult = await get("/health");
            serviceState.textContent = healthResult.models_cached === false
                ? ui("Lokaler Suchdienst läuft. Die Modelle werden bei der ersten Verarbeitung heruntergeladen; dafür ist Internet nötig.",
                    "Local service is running. Models will download during first processing; internet is required.")
                : ui("Lokaler Suchdienst und Modelle sind bereit.", "Local search service and models are ready.");
            serviceState.style.background = "#e8f5ea";
        } catch {
            serviceState.textContent = ui("Lokaler Suchdienst ist nicht erreichbar. Install-Zitatlotse.ps1 aus dem Quellcode-Archiv ausführen und danach „Suchdienst prüfen“ anklicken.",
                "Local service is unavailable. Run Install-Zitatlotse.ps1 from the source archive, then click ‘Check service’. ");
            serviceState.style.background = "#fff0dc";
        } finally { serviceProgress.stop(); }
    });
    single.addEventListener("click", async () => {
        updateSelectedItem();
        let item = Zotero.getActiveZoteroPane()?.getSelectedItems()?.[0];
        if (!item) { report(ui("Bitte zuerst einen Eintrag auswählen.", "Select an item first.")); return; }
        if (item.libraryID !== currentLibraryID) {
            report(ui("Der ausgewählte Eintrag gehört zu einer anderen Bibliothek. Bitte oben die passende Bibliothek wählen.",
                "The selected item belongs to another library. Select that library above."));
            return;
        }
        single.disabled = true;
        processingProgress.start();
        report(ui("Eintrag wird verarbeitet …", "Processing item…"));
        try {
            let summary = await indexItem(item, report);
            report(summaryText(summary));
            await refreshStatus();
        } catch (error) { report(ui("Verarbeitung fehlgeschlagen: ", "Processing failed: ") + error.message); }
        finally { single.disabled = false; processingProgress.stop(); }
    });
    scan.addEventListener("click", async () => {
        scan.disabled = true;
        processingProgress.start();
        report(ui("Bibliothek wird geprüft …", "Checking library…"));
        try {
            let summary = await indexLibrary(currentLibraryID, (progress, message, total) => {
                processingProgress.update(progress.pdfs, total);
                report(message || progress.checked + ui(" PDFs geprüft; ", " PDFs checked; ") +
                    progress.indexed + ui(" verarbeitet …", " processed…"));
            });
            report(summaryText(summary, true));
            await refreshStatus();
        } catch (error) { report(ui("Verarbeitung fehlgeschlagen: ", "Processing failed: ") + error.message); }
        finally { scan.disabled = false; processingProgress.stop(); }
    });
    chatManage.addEventListener("click", () => overlay.zitatlotseShowTab("search"));
    const copyQuote = hit => {
        let citation = "„" + hit.quote + "“ " + citationForHit(hit, citationStyle.value);
        Zotero.Utilities.Internal.copyTextToClipboard(citation);
        report(ui("Zitat im gewählten Zitierstil kopiert.", "Quote copied in the selected citation style."));
    };
    const openingQuotes = new Set();
    const openHit = async hit => {
        let key = [hit.library_id, hit.attachment_key, hit.page, hit.quote].join("|");
        if (openingQuotes.has(key)) return;
        openingQuotes.add(key);
        report(ui("PDF wird geöffnet …", "Opening PDF…"));
        try {
            await openQuoteInPDF(hit, closePanel);
        }
        catch (error) {
            Zotero.logError?.(error);
            if (overlay.zitatlotseClosing) Zotero.alert?.(win, "Zitatlotse", ui("PDF konnte nicht geöffnet werden: ", "Could not open PDF: ") + error.message);
            else report(ui("PDF konnte nicht geöffnet werden: ", "Could not open PDF: ") + error.message);
        } finally { openingQuotes.delete(key); }
    };
    let savedRequestNumber = 0;
    const loadSaved = async () => {
        let sequence = ++savedRequestNumber;
        let requestedLibrary = currentLibraryID;
        savedProgress.start();
        try {
            let data = await request("/saved/list", {library_id:requestedLibrary,query:savedSearch.value.trim()});
            if (sequence !== savedRequestNumber || requestedLibrary !== currentLibraryID) return;
            savedResults.replaceChildren();
            if (!data.results.length) {
                add(savedResults, "p", ui("Keine gespeicherten Zitate gefunden.", "No saved quotes found."));
                return;
            }
            for (let hit of data.results) {
                let card = add(savedResults, "div", undefined,
                    "border-top:1px solid #dedbe7;padding:14px 0;");
                add(card, "strong", hit.title + ui(" · PDF-Seite ", " · PDF page ") + hit.page);
                let quote = add(card, "p", "„" + hit.quote + "“",
                    "line-height:1.5;cursor:pointer;white-space:pre-wrap;");
                quote.setAttribute("title", ui("Doppelklick: Fundstelle im PDF öffnen", "Double-click: open passage in PDF"));
                quote.addEventListener("dblclick", () => openHit(hit));
                let note = add(card, "textarea", undefined, inputStyle + "min-height:72px;resize:vertical;");
                note.value = hit.note || "";
                note.setAttribute("placeholder", ui("Notiz zu diesem Zitat", "Note for this quote"));
                let actions = add(card, "div", undefined, rowStyle);
                let saveNote = add(actions, "button", ui("Notiz speichern", "Save note"), buttonStyle);
                saveNote.addEventListener("click", async () => {
                    saveNote.disabled = true;
                    try {
                        await request("/saved/note", {library_id:currentLibraryID,id:hit.id,note:note.value});
                        report(ui("Notiz gespeichert.", "Note saved."));
                    } catch (error) { report(ui("Notiz konnte nicht gespeichert werden: ", "Could not save note: ") + error.message); }
                    finally { saveNote.disabled = false; }
                });
                let copy = add(actions, "button", ui("Zitat kopieren", "Copy quote"), buttonStyle);
                copy.addEventListener("click", () => {
                    try { copyQuote(hit); }
                    catch (error) { report(ui("Zitat konnte nicht kopiert werden: ", "Could not copy quote: ") + error.message); }
                });
                let open = add(actions, "button", ui("Im PDF öffnen", "Open in PDF"), buttonStyle);
                open.addEventListener("click", () => openHit(hit));
                let remove = add(actions, "button", ui("Entfernen", "Remove"), buttonStyle);
                remove.addEventListener("click", async () => {
                    remove.disabled = true;
                    try {
                        await request("/saved/delete", {library_id:currentLibraryID,id:hit.id});
                        card.remove();
                        report(ui("Zitat entfernt.", "Quote removed."));
                    } catch (error) { report(ui("Zitat konnte nicht entfernt werden: ", "Could not remove quote: ") + error.message); }
                    finally { remove.disabled = false; }
                });
            }
        } catch (error) {
            if (sequence === savedRequestNumber) report(ui("Gespeicherte Zitate konnten nicht geladen werden: ",
                "Could not load saved quotes: ") + error.message);
        } finally { if (sequence === savedRequestNumber) savedProgress.stop(); }
    };
    let savedSearchTimer;
    savedSearch.addEventListener("input", () => {
        clearTimeout(savedSearchTimer);
        savedSearchTimer = setTimeout(loadSaved, 250);
    });
    const renderHits = (container, hits) => {
        if (!hits.length) {
            add(container, "p", ui("Keine ausreichend passende Originaltextstelle gefunden.",
                "No sufficiently relevant original passage found."));
            add(container, "p", ui(
                "Tipps: Suche mit zentralen Fachbegriffen oder Synonymen, formuliere die Frage kürzer und prüfe, ob die PDFs verarbeitet wurden und durchsuchbaren Text enthalten.",
                "Tips: Try key terms or synonyms, shorten the question, and check that the PDFs were processed and contain searchable text."),
                "color:#615d6c;line-height:1.45;");
            return;
        }
        for (let hit of hits) {
            let card = add(container, "div", undefined, "border-top:1px solid #dedbe7;padding:14px 0;");
            add(card, "strong", (hit.reference_number ? "[" + hit.reference_number + "] " : "") +
                hit.title + ui(" · PDF-Seite ", " · PDF page ") + hit.page);
            if (hit.recommended) add(card, "span", ui(" · Von KI ausgewählt", " · Selected by AI"),
                "color:#5b36bf;font-weight:700;");
            if (hit.stance) {
                if (hit.evidence_scope === "aspect") add(card, "small", ui(
                    "Aspektbeleg – zeigt einen Vorteil oder Nachteil, belegt aber nicht allein die Gesamtbewertung.",
                    "Aspect evidence – demonstrates a benefit or drawback, but does not establish the overall judgment."),
                    "display:block;margin-top:8px;color:#615d6c;line-height:1.45;");
                if (hit.point) add(card, "p", hit.point, "font-weight:700;line-height:1.45;");
                if (hit.reason) add(card, "p", hit.reason, "color:#615d6c;line-height:1.45;");
            }
            let quote = add(card, "p", "„" + hit.quote + "“",
                "line-height:1.5;cursor:pointer;white-space:pre-wrap;");
            quote.setAttribute("title", ui("Doppelklick: Fundstelle im PDF öffnen", "Double-click: open passage in PDF"));
            quote.addEventListener("dblclick", () => openHit(hit));
            let actions = add(card, "div", undefined, rowStyle);
            let copy = add(actions, "button", ui("Zitat kopieren", "Copy quote"), buttonStyle);
            copy.addEventListener("click", () => {
                try { copyQuote(hit); }
                catch (error) { report(ui("Zitat konnte nicht kopiert werden: ", "Could not copy quote: ") + error.message); }
            });
            let open = add(actions, "button", ui("Im PDF öffnen", "Open in PDF"), buttonStyle);
            open.addEventListener("click", async () => {
                open.disabled = true;
                try { await openHit(hit); } finally { open.disabled = false; }
            });
            let saveHit = add(actions, "button", ui("Zitat speichern", "Save quote"), buttonStyle);
            saveHit.addEventListener("click", async () => {
                saveHit.disabled = true;
                try {
                    if (hit.library_id !== currentLibraryID) throw new Error(ui(
                        "Die Bibliothek wurde gewechselt. Bitte erneut suchen.",
                        "The library changed. Search again."));
                    await request("/saved/add", hit);
                    saveHit.textContent = ui("Gespeichert", "Saved");
                    report(ui("Zitat gespeichert.", "Quote saved."));
                } catch (error) {
                    saveHit.disabled = false;
                    report(ui("Zitat konnte nicht gespeichert werden: ", "Could not save quote: ") + error.message);
                }
            });
        }
    };
    const addBubble = (role, message) => {
        add(chatHistory, "div", message,
            "align-self:" + (role === "user" ? "flex-end" : "flex-start") +
            ";box-sizing:border-box;min-width:0;max-width:90%;overflow-wrap:anywhere;padding:10px 12px;border-radius:10px;line-height:1.45;white-space:pre-wrap;background:" +
            (role === "user" ? "#5b36bf;color:white;" : "#eeeafa;color:#252333;"));
        chatHistory.scrollTop = chatHistory.scrollHeight;
    };
    const renderEvidence = (container, state, hits) => {
        let balance = state.evidence;
        add(container, "strong", ui("Belegprüfung: ", "Evidence assessment: ") + balance.claim, "display:block;margin:12px 0;");
        add(container, "small", ui("Bei einer Abwägung werden belegte Vorteile und Nachteile als Aspektbelege gekennzeichnet. Die Verteilung entscheidet nicht automatisch über die Gesamtbewertung.",
            "For trade-offs, demonstrated benefits and drawbacks are marked as aspect evidence. Their distribution does not automatically determine the overall judgment."),
            "display:block;color:#615d6c;line-height:1.5;");
        for (let [stance, label, color] of [["pro", ui("Pro – spricht für die Aussage", "Pro – favors the claim"), "#137a49"],
            ["contra", ui("Kontra – spricht gegen die Aussage", "Contra – opposes the claim"), "#ba303b"],
            ["neutral", ui("Neutral oder unklar", "Neutral or unclear"), "#615d6c"]]) {
            if (stance === "neutral" && !state.showAll) continue;
            let group = add(container, "section", undefined, "margin:18px 0;", "zqs-evidence-" + stance);
            add(group, "h3", label + " · " + balance[stance], "color:" + color + ";margin:0 0 8px;font-size:17px;");
            let matches = hits.filter(hit => hit.stance === stance);
            if (matches.length) renderHits(group, matches);
            else add(group, "p", balance[stance] ? ui("Weitere Belege auf den anderen Ergebnisseiten.", "More evidence on other result pages.")
                : ui("Keine entsprechenden Belege gefunden.", "No corresponding evidence found."), "color:#615d6c;");
        }
        let summary = add(container, "div", undefined, "padding-top:16px;border-top:1px solid #e2dfeb;", "zqs-evidence-balance");
        add(summary, "strong", ui("Verteilung der Pro-/Kontra-Fundstellen", "Distribution of supporting/opposing passages"));
        let directional = balance.pro + balance.contra;
        if (directional) {
            let pro = balance.pro_percent, contra = balance.contra_percent;
            let bar = add(summary, "div", undefined,
                "display:flex;width:100%;height:28px;overflow:hidden;border-radius:8px;margin:12px 0;background:#eee;", "zqs-evidence-bar");
            bar.setAttribute("role", "img");
            bar.setAttribute("aria-label", "Pro " + pro + "%, " + ui("Kontra ", "Contra ") + contra + "%");
            add(bar, "div", "", "height:100%;width:" + pro + "%;background:#168450;transition:width .35s ease;");
            add(bar, "div", "", "height:100%;width:" + contra + "%;background:#cf3c48;transition:width .35s ease;");
            add(summary, "p", "Pro: " + balance.pro + " (" + pro + "%) · " + ui("Kontra: ", "Contra: ") + balance.contra + " (" + contra + "%)");
        } else add(summary, "p", ui("Keine eindeutig unterstützenden oder widersprechenden Belege gefunden.",
            "No clearly supporting or opposing evidence found."));
        add(summary, "small", ui("Ausgewertet: ", "Assessed: ") + balance.total + ui(" unterschiedliche Fundstellen. Neutral/unklar: ", " distinct passages. Neutral/unclear: ") + balance.neutral +
            ui(". Die Prozentwerte beziehen sich auf Pro- und Kontra-Fundstellen.", ". Percentages refer to supporting and opposing passages."), "color:#615d6c;line-height:1.5;");
    };
    const refreshSearchProgress = () => {
        let mode = chatPanel.style.display !== "none" ? "chat"
            : searchPanel.style.display !== "none" ? "direct" : null;
        let state = mode && getSearchSession(currentLibraryID, mode);
        let busy = state && (state.pending || state.loadingMore);
        searchVisual.style.display = busy ? "block" : "none";
        if (busy && state.reviewTotal > 0) searchProgress.update(state.reviewDone, state.reviewTotal);
        else if (busy) searchProgress.start();
        else searchProgress.stop();
    };
    const renderPagination = (mode, state, view) => {
        let nav = mode === "chat" ? chatPagination : searchPagination;
        nav.replaceChildren();
        nav.style.display = view.count > 1 ? "flex" : "none";
        if (view.count <= 1) return;
        const pageButton = (label, number, id) => {
            let button = add(nav, "button", label, buttonStyle, id);
            button.disabled = state.pending || state.loadingMore || number < 1 || number > view.count || number === view.number;
            if (number === view.number) {
                button.style.background = "#e6dcff";
                button.setAttribute("aria-current", "page");
            }
            button.addEventListener("click", () => goToResultsPage(mode, number));
        };
        pageButton(ui("Zurück", "Previous"), view.number - 1, "zqs-" + mode + "-previous");
        let pages = view.count <= 7 ? Array.from({length:view.count}, (_, i) => i + 1)
            : [...new Set([1, view.number - 1, view.number, view.number + 1, view.count])]
                .filter(number => number >= 1 && number <= view.count).sort((a, b) => a - b);
        let previous = 0;
        for (let number of pages) {
            if (previous && number > previous + 1) add(nav, "span", "…");
            pageButton(String(number), number, "zqs-" + mode + "-page-" + number);
            previous = number;
        }
        pageButton(ui("Weiter", "Next"), view.number + 1, "zqs-" + mode + "-next");
        add(nav, "small", ui("Seite ", "Page ") + view.number +
            (view.exactCount ? ui(" von ", " of ") + view.count + " · " + view.total + ui(" Treffer", " results")
                : ui(" · weitere Treffer verfügbar", " · more results available")),
            "flex-basis:100%;text-align:center;color:#615d6c;");
    };
    const relevanceTiers = [
        ["highest", ui("Höchste Ähnlichkeit", "Highest similarity"), "#dc454b"],
        ["high", ui("Höhere Ähnlichkeit", "Higher similarity"), "#ee8c38"],
        ["medium", ui("Mittlere Ähnlichkeit", "Medium similarity"), "#ddbc48"],
        ["low", ui("Geringere Ähnlichkeit", "Lower similarity"), "#9aabc1"],
        ["lowest", ui("Geringste Ähnlichkeit", "Lowest similarity"), "#607088"],
        ["same", ui("Gleiche Ähnlichkeit", "Equal similarity"), "#7352c7"],
        ["unindexed", ui("Noch nicht bewertet", "Not scored yet"), "#d7d9e1"]
    ];
    const renderDocumentOverview = (mode, state) => {
        let container = mode === "chat" ? chatOverview : directOverview;
        let data = state.overview;
        let signature = [state.overviewPending, state.overviewError, state.overviewCategory, state.overviewPage].join("|");
        if (container.relevanceState === state && container.relevanceData === data && container.relevanceSignature === signature) return;
        container.relevanceState = state;
        container.relevanceData = data;
        container.relevanceSignature = signature;
        container.replaceChildren();
        container.style.display = data || state.overviewPending || state.overviewError ? "block" : "none";
        if (container.style.display === "none") return;
        add(container, "strong", ui("Geschätzte Dokumentrelevanz", "Estimated document relevance"), "font-size:17px;");
        if (state.overviewPending) {
            add(container, "p", ui("Vergleiche Dokumente mit der aktuellen Frage …", "Comparing documents with the current question…"));
            makeProgress(container).start();
            return;
        }
        if (state.overviewError) { add(container, "p", state.overviewError); return; }
        add(container, "p", data.query, "margin:10px 0 6px;overflow-wrap:anywhere;line-height:1.5;");
        add(container, "small", ui("Höchste Chunk-Ähnlichkeit je Dokument · relative Einteilung",
            "Highest chunk similarity per document · relative groups"), "display:block;color:#615d6c;margin-bottom:12px;");
        if (data.model) add(container, "small", ui("Modell: ", "Model: ") + data.model,
            "display:block;color:#615d6c;margin-bottom:8px;");
        let compatibility = data.model_compatibility;
        if (compatibility?.[uiLang()]) add(container, "p", compatibility[uiLang()],
            "padding:10px;border:1px solid #f2c7bd;border-radius:8px;background:#fff4ef;color:#92331e;line-height:1.5;",
            "zqs-" + mode + "-relevance-warning");
        if (compatibility?.status === "incompatible") {
            add(container, "p", ui("Die Grafik wird erst mit einem geeigneten Embedding-Modell berechnet.",
                "The chart requires a suitable embedding model."));
            let settings = add(container, "button", ui("Embedding-Modell in Einstellungen ändern", "Change embedding model in Settings"), buttonStyle);
            settings.addEventListener("click", () => preferencesTab.click());
            return;
        }
        add(container, "small", ui("Die Farben vergleichen die Dokumente innerhalb dieses Suchbereichs. Der Ähnlichkeitswert ist keine Relevanzwahrscheinlichkeit.",
            "Colors compare documents within this search scope. Similarity is not a relevance probability."),
            "display:block;color:#615d6c;line-height:1.4;margin-bottom:12px;");
        if (Object.keys(data.language_queries || {}).length) {
            let formulations = add(container, "details", undefined, "margin:8px 0 12px;font-size:12px;color:#615d6c;");
            add(formulations, "summary", ui("Suchformulierungen nach Dokumentsprache", "Search queries by document language"), "cursor:pointer;");
            for (let [language, query] of Object.entries(data.language_queries))
                add(formulations, "p", language.toUpperCase() + ": " + query, "margin:6px 0;overflow-wrap:anywhere;");
            add(formulations, "small", ui("Ohne passende Sprachvariante wird die ursprüngliche Frage mit dem mehrsprachigen Modell verglichen.",
                "Without a matching language variant, the multilingual model compares the original question."));
        }
        if (data.duplicate_attachments) add(container, "small", data.total_attachments + ui(" PDF-Anhänge · ", " PDF attachments · ") +
            data.duplicate_attachments + ui(" identische Kopien zusammengefasst.", " identical copies grouped."),
            "display:block;color:#615d6c;margin-bottom:12px;", "zqs-" + mode + "-relevance-duplicates");
        if (!data.total_documents) {
            add(container, "p", ui("Keine PDFs in diesem Suchbereich.", "No PDFs in this search scope."));
            return;
        }
        let layout = add(container, "div", undefined, "display:flex;flex-wrap:wrap;gap:20px;align-items:flex-start;");
        let chartColumn = add(layout, "div", undefined, "flex:0 1 230px;min-width:0;max-width:100%;");
        const svgNode = (tag, attrs, parent) => {
            let node = doc.createElementNS("http://www.w3.org/2000/svg", tag);
            for (let [key, value] of Object.entries(attrs)) node.setAttribute(key, String(value));
            parent.append(node);
            return node;
        };
        let chart = svgNode("svg", {viewBox:"0 0 220 220",width:220,height:220,role:"img",
            "aria-label":ui("Verteilung der Dokumentrelevanz", "Document relevance distribution")}, chartColumn);
        chart.style.cssText = "display:block;max-width:100%;height:auto;";
        let chartTitle = svgNode("title", {}, chart);
        chartTitle.textContent = data.total_documents + ui(" Dokumente im Suchbereich", " documents in scope");
        let radius = 80, circumference = 2 * Math.PI * radius, offset = 0;
        let animated = container.relevanceAnimated !== data;
        container.relevanceAnimated = data;
        let reduceMotion = win.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
        for (let [id, label, color] of relevanceTiers) {
            let category = data.categories.find(c => c.id === id);
            if (!category?.count) continue;
            let length = circumference * category.count / data.total_documents;
            let visible = Math.max(0, length - (category.count === data.total_documents ? 0 : 2));
            let segment = svgNode("circle", {cx:110,cy:110,r:radius,fill:"none",stroke:color,
                "stroke-width":30,"stroke-dasharray":`${animated && !reduceMotion ? 0 : visible} ${circumference}`,
                "stroke-dashoffset":-offset,transform:"rotate(-90 110 110)"}, chart);
            segment.style.cssText = "cursor:pointer;transition:stroke-dasharray 650ms ease;";
            let tooltip = svgNode("title", {}, segment);
            tooltip.textContent = `${label}: ${category.count} (${category.percentage}%)`;
            segment.addEventListener("click", () => selectCategory(id));
            if (animated && !reduceMotion) win.requestAnimationFrame(() => win.requestAnimationFrame(() =>
                segment.setAttribute("stroke-dasharray", `${visible} ${circumference}`)));
            offset += length;
        }
        let count = svgNode("text", {x:110,y:106,"text-anchor":"middle",fill:"#272237","font-size":30,"font-weight":700}, chart);
        count.textContent = String(data.total_documents);
        let caption = svgNode("text", {x:110,y:130,"text-anchor":"middle",fill:"#615d6c","font-size":13}, chart);
        caption.textContent = ui("Dokumente", "Documents");
        add(chartColumn, "small", data.scored_documents + " / " + data.total_documents + ui(" Dokumente bewertet", " documents scored"),
            "display:block;text-align:center;color:#615d6c;");
        let detail = add(layout, "div", undefined, "flex:1 1 260px;min-width:0;");
        let legend = add(detail, "div", undefined, "display:flex;flex-wrap:wrap;gap:6px;margin-bottom:14px;");
        const selectCategory = id => {
            state.overviewCategory = id;
            state.overviewPage = 1;
            notifySearchSession(currentLibraryID, mode);
        };
        const legendButton = (id, label, color) => {
            let button = add(legend, "button", undefined, buttonStyle + "gap:6px;font-size:12px;padding:6px 8px;",
                "zqs-" + mode + "-relevance-" + id);
            button.setAttribute("aria-pressed", String(state.overviewCategory === id));
            if (state.overviewCategory === id) button.style.background = "#eeeafa";
            if (color) add(button, "span", "", `display:inline-block;width:9px;height:9px;flex-shrink:0;border-radius:50%;background:${color};`);
            add(button, "span", label);
            button.addEventListener("click", () => selectCategory(id));
        };
        legendButton("all", ui("Alle", "All") + " · " + data.total_documents);
        for (let [id, label, color] of relevanceTiers) {
            let category = data.categories.find(c => c.id === id);
            if (category?.count) legendButton(id, `${label} · ${category.count} · ${category.percentage}%`, color);
        }
        let documents = data.documents.filter(d => state.overviewCategory === "all" || d.category === state.overviewCategory);
        let pages = Math.max(1, Math.ceil(documents.length / 5));
        state.overviewPage = Math.min(state.overviewPage, pages);
        let list = add(detail, "div", undefined, "display:flex;flex-direction:column;gap:9px;", "zqs-" + mode + "-relevance-documents");
        for (let document of documents.slice((state.overviewPage - 1) * 5, state.overviewPage * 5)) {
            let row = add(list, "div", undefined, "border-top:1px solid #e4e0ee;padding-top:9px;line-height:1.4;");
            add(row, "strong", document.title, "display:block;font-size:13px;overflow-wrap:anywhere;");
            let meta = document.similarity === null ? ui("Noch keine Chunks bewertet", "No chunks scored yet")
                : ui("Ähnlichkeit: ", "Similarity: ") + document.similarity.toFixed(3) +
                    (document.page ? ui(" · Seite ", " · Page ") + document.page : "");
            if (document.duplicate_count) meta += " · " + (document.duplicate_count + 1) + ui(" identische Anhänge", " identical attachments");
            let actions = add(row, "div", undefined, "display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-top:5px;");
            add(actions, "small", meta, "color:#615d6c;");
            let open = add(actions, "button", ui("PDF öffnen", "Open PDF"), buttonStyle + "font-size:12px;padding:4px 8px;");
            open.addEventListener("click", async () => {
                try {
                    let keys = [...new Set([document.attachment_key, ...(document.attachment_keys || [])])];
                    let attachment = keys.map(key => Zotero.Items.getByLibraryAndKey(document.library_id, key))
                        .find(item => item?.isAttachment() && !item.deleted && item.libraryID === document.library_id);
                    if (!attachment) throw new Error(ui("PDF ist nicht mehr verfügbar.", "PDF is no longer available."));
                    await Zotero.Reader.open(attachment.id, {pageIndex:Math.max(0, (document.page || 1) - 1)});
                    closePanel();
                } catch (error) { report(error.message); }
            });
        }
        if (pages > 1) {
            let nav = add(detail, "nav", undefined, rowStyle + "margin-top:12px;justify-content:center;");
            for (let [label, delta] of [[ui("Zurück", "Previous"), -1], [ui("Weiter", "Next"), 1]]) {
                let button = add(nav, "button", label, buttonStyle, "zqs-" + mode + "-relevance-" + (delta < 0 ? "previous" : "next"));
                button.disabled = state.overviewPage + delta < 1 || state.overviewPage + delta > pages;
                button.addEventListener("click", () => {state.overviewPage += delta; notifySearchSession(currentLibraryID, mode);});
                if (delta > 0) nav.append(button);
                else add(nav, "span", state.overviewPage + " / " + pages);
            }
        }
    };
    const renderSearchSession = mode => {
        let isChat = mode === "chat";
        let state = getSearchSession(currentLibraryID, mode);
        let container = isChat ? chatResults : results;
        let view = resultsView(state, mode);
        state.viewPage = view.number;
        (isChat ? chatInput : query).value = state.draft;
        (isChat ? chatSend : search).disabled = state.pending || state.loadingMore;
        if (isChat) {
            activityEnabled.checked = showAIActivity;
            activityPanel.style.display = showAIActivity && (state.pending || state.activity.length) ? "block" : "none";
            if (activityPanel.open !== state.activityExpanded) activityPanel.open = state.activityExpanded;
            let lastActivity = state.activity.at(-1);
            activitySummary.textContent = ui("KI-Ablauf", "AI activity") + (lastActivity ? " · " + activityLabel(lastActivity)
                : state.pending ? ui(" · Anfrage wird gestartet …", " · Starting request…") : "");
            let followActivity = activityList.scrollHeight - activityList.scrollTop - activityList.clientHeight < 30;
            activityList.replaceChildren();
            for (let event of state.activity) {
                let label = activityLabel(event);
                if (!label) continue;
                let item = add(activityList, "li", undefined, "margin:8px 0;line-height:1.5;overflow-wrap:anywhere;");
                let seconds = Math.max(0, Math.floor(event.elapsed || 0));
                add(item, "small", Math.floor(seconds / 60) + ":" + String(seconds % 60).padStart(2, "0") + " · ", "color:#615d6c;");
                add(item, "span", label);
                if (event.query) add(item, "div", (event.language && event.language !== "all" ? event.language + ": " : "") + event.query,
                    "color:#615d6c;font-size:13px;margin-top:2px;");
            }
            if (followActivity) activityList.scrollTop = activityList.scrollHeight;
            chatMode.value = state.searchMode;
            chatMode.disabled = state.pending || state.loadingMore;
            chatInput.setAttribute("placeholder", state.searchMode === "evidence"
                ? ui("Aussage eingeben, z. B.: Modell X zeigt auf Datensatz Y Overfitting.", "Enter a claim, e.g.: Model X overfits on dataset Y.")
                : ui("Stelle eine Frage an deine Bibliothek", "Ask your library a question"));
            chatSend.textContent = state.searchMode === "evidence" ? ui("Belege suchen", "Find evidence") : ui("Frage senden", "Send question");
            chatHistory.replaceChildren();
            for (let message of state.messages) addBubble(message.role, message.content);
            chatFilterRow.style.display = state.reviewed && state.hits !== null ? "flex" : "none";
            chatShowAll.checked = state.showAll;
            chatShowAll.disabled = state.pending || state.loadingMore;
        }
        container.replaceChildren();
        if (isChat && state.queries.length) add(container, "p", ui("Suchanfragen: ", "Search queries: ") +
            state.queries.map(([language, value]) => language + ": " + value).join(" · "),
            "color:#615d6c;line-height:1.5;");
        if (state.hits !== null) {
            if (isChat && state.evidence) renderEvidence(container, state, view.hits);
            else if (view.filtered && !view.hits.length && state.hits.length) add(container, "p", ui(
                "Keine von der KI ausgewählten Zitate. Mit „Alle Treffer anzeigen“ kannst du die übrigen Fundstellen ansehen.",
                "No AI-selected quotes. Enable ‘Show all results’ to view the other passages."));
            else renderHits(container, view.hits);
            if (isChat && !state.reviewed && state.hits.length) add(container, "small", ui(
                "Lokale Treffer – keine KI-Auswahl verfügbar.", "Local results – no AI selection available."), "color:#615d6c;");
        }
        else if (!state.pending) add(container, "p", ui(
            "Hier erscheinen passende Textstellen aus dieser Bibliothek.",
            "Matching passages from this library will appear here."), "margin:0;color:#615d6c;");
        renderPagination(mode, state, view);
        renderDocumentOverview(mode, state);
        if ((isChat ? chatPanel : searchPanel).style.display !== "none")
            report(state.status || ui("Bereit", "Ready"));
        refreshSearchProgress();
    };
    onSessionChange = (id, mode) => {
        if (id === currentLibraryID && !overlay.zitatlotseClosing) renderSearchSession(mode);
    };
    searchSessionListeners.add(onSessionChange);
    chatInput.addEventListener("input", () => {
        getSearchSession(currentLibraryID, "chat").draft = chatInput.value;
    });
    chatMode.addEventListener("change", () => {
        let state = getSearchSession(currentLibraryID, "chat");
        if (state.pending || state.loadingMore) return;
        state.searchMode = chatMode.value;
        notifySearchSession(currentLibraryID, "chat");
    });
    query.addEventListener("input", () => {
        getSearchSession(currentLibraryID, "direct").draft = query.value;
    });
    chatReset.addEventListener("click", () => {
        let state = getSearchSession(currentLibraryID, "chat");
        if (state.jobID) request(state.jobEndpoint + "/cancel", {library_id:currentLibraryID,job_id:state.jobID,
            collection_id:state.scope.collection_id || 0}).catch(error => Zotero.logError(error));
        resetSearchSession(currentLibraryID, "chat");
        chatInput.focus();
    });
    searchReset.addEventListener("click", () => {
        resetSearchSession(currentLibraryID, "direct");
        query.focus();
    });
    chatShowAll.addEventListener("change", () => {
        let state = getSearchSession(currentLibraryID, "chat");
        state.showAll = chatShowAll.checked;
        state.viewPage = 1;
        notifySearchSession(currentLibraryID, "chat");
    });
    const goToResultsPage = async (mode, number) => {
        let libraryAtStart = currentLibraryID;
        let state = getSearchSession(libraryAtStart, mode);
        let view = resultsView(state, mode);
        if (number < 1 || number > view.count || state.pending || state.loadingMore) return;
        if (view.filtered || state.resultPages[number]) {
            state.viewPage = number;
            notifySearchSession(libraryAtStart, mode);
            return;
        }
        if (!state.page?.id) return;
        state.loadingMore = true;
        state.status = ui("Lade Seite ", "Loading page ") + number + " …";
        notifySearchSession(libraryAtStart, mode);
        try {
            let offset = state.totalResults === null && state.resultPages[number - 1]
                ? state.resultPages[number - 1].next : (number - 1) * RESULTS_PER_PAGE;
            let data = await request("/search", {library_id:libraryAtStart,
                collection_id:state.scope.collection_id || 0,search_id:state.page.id,offset,limit:RESULTS_PER_PAGE});
            if (!isCurrentSearchSession(libraryAtStart, mode, state)) return;
            storeResultsPage(state, data, number);
            state.viewPage = number;
            state.status = ui("Seite ", "Page ") + number;
        } catch (error) {
            if (isCurrentSearchSession(libraryAtStart, mode, state)) {
                if (/abgelaufen|expired/i.test(error.message)) {
                    state.status = ui("Die Suche ist abgelaufen. Bitte erneut suchen.",
                        "The search expired. Run it again.");
                } else state.status = ui("Weitere Treffer konnten nicht geladen werden: ",
                    "Could not load more passages: ") + error.message;
            }
        } finally {
            state.loadingMore = false;
            if (isCurrentSearchSession(libraryAtStart, mode, state)) notifySearchSession(libraryAtStart, mode);
        }
    };
    const runChat = async () => {
        let question = chatInput.value.trim();
        let libraryAtStart = currentLibraryID;
        let state = getSearchSession(libraryAtStart, "chat");
        if (!question || state.pending || state.loadingMore) return;
        let history = state.messages.slice(-6);
        state.messages.push({role:"user",content:question});
        state.draft = "";
        state.pending = true;
        clearDocumentOverview(state);
        state.hits = null;
        state.queries = [];
        state.page = null;
        state.resultPages = {};
        state.totalResults = null;
        state.viewPage = 1;
        state.showAll = false;
        state.reviewed = false;
        state.selectedHits = null;
        state.agentSteps = [];
        state.evidence = null;
        state.jobID = null;
        state.activity = [];
        state.reviewDone = state.reviewTotal = 0;
        state.status = ui("Durchsuche Bibliothek …", "Searching library…");
        notifySearchSession(libraryAtStart, "chat");
        try {
            state.scope = await collectionSearchScope(libraryAtStart, libraryCollections.get(libraryAtStart) || 0);
            if (!isCurrentSearchSession(libraryAtStart, "chat", state)) return;
            let payload = {library_id:libraryAtStart,...state.scope,message:question,history,ui_lang:uiLang(),limit:20,mode:state.searchMode};
            state.jobEndpoint = state.searchMode === "evidence" ? "/evidence" : "/chat";
            let started = await request(state.jobEndpoint + "/start", payload);
            state.jobID = started.job_id;
            let jobScope = {library_id:libraryAtStart,collection_id:state.scope.collection_id || 0,job_id:started.job_id};
            let data;
            while (true) {
                if (!isCurrentSearchSession(libraryAtStart, "chat", state)) {
                    request(state.jobEndpoint + "/cancel", jobScope).catch(error => Zotero.logError(error));
                    return;
                }
                let job = await request(state.jobEndpoint + "/status", jobScope);
                if (!isCurrentSearchSession(libraryAtStart, "chat", state)) return;
                state.activity = Array.isArray(job.activity) ? job.activity : state.activity;
                state.reviewDone = job.completed || 0;
                state.reviewTotal = job.total || 0;
                if (job.state === "complete") { data = job.result; break; }
                if (job.state === "failed" || job.state === "cancelled") throw new Error(job.error || ui("Suche wurde zurückgesetzt.", "Search was reset."));
                state.status = job.phase === "reviewing"
                    ? state.searchMode === "evidence" ? ui("Bewerte Belege: ", "Assessing evidence: ") + state.reviewDone + " / " + state.reviewTotal
                        : ui("KI wertet Fundstellen aus …", "AI is reviewing passages…")
                    : ui("Durchsuche Bibliothek …", "Searching library…");
                notifySearchSession(libraryAtStart, "chat");
                await new Promise(resolve => setTimeout(resolve, 1000));
            }
            if (!isCurrentSearchSession(libraryAtStart, "chat", state)) return;
            let explanation = data.reply || "";
            if (!data.used_ai && Object.keys(data.queries || {}).length) explanation += "\n" +
                (data.ai_configured
                    ? ui("KI derzeit nicht verfügbar: lokale Suche verwendet.",
                        "AI is currently unavailable: using local search.")
                    : ui("Ohne verbundene KI: lokale mehrsprachige Suche verwendet.",
                        "No AI connected: using local multilingual search."));
            if (data.warning) explanation += "\n" + data.warning;
            state.messages.push({role:"assistant",content:explanation});
            state.queries = Object.entries(data.queries || {}).filter(([language]) => language !== "default");
            state.hits = data.results || [];
            state.page = {id:data.search_id,next:data.next_offset,hasMore:data.has_more};
            state.reviewed = data.reviewed === true || state.hits.some(hit => typeof hit.recommended === "boolean");
            state.selectedHits = Array.isArray(data.selected_results) ? data.selected_results : null;
            state.agentSteps = data.agent_steps || [];
            state.activity = Array.isArray(data.activity) ? data.activity : state.activity;
            state.evidence = data.evidence ? {...data.evidence,claim:question} : null;
            storeResultsPage(state, data);
            let selectedCount = state.selectedHits?.length ?? state.hits.filter(hit => hit.recommended === true).length;
            state.status = state.reviewed ? selectedCount + ui(" von der KI ausgewählte Zitate", " AI-selected quotes") +
                " · " + (data.total_results ?? state.hits.length) + ui(" Fundstellen", " passages")
                : state.hits.length + ui(" Fundstellen aus dieser Bibliothek angezeigt.", " passages shown from this library.");
            loadDocumentOverview(libraryAtStart, "chat", state, question, documentLanguageQueries(data));
        } catch (error) {
            if (isCurrentSearchSession(libraryAtStart, "chat", state)) {
                let message = ui("KI-Suche fehlgeschlagen: ", "AI search failed: ") + error.message;
                state.messages.push({role:"assistant",content:message});
                state.status = message;
            }
        } finally {
            state.pending = false;
            if (isCurrentSearchSession(libraryAtStart, "chat", state)) {
                notifySearchSession(libraryAtStart, "chat");
                if (libraryAtStart === currentLibraryID && chatPanel.style.display !== "none" && !overlay.zitatlotseClosing)
                    chatResults.scrollIntoView?.({block:"nearest",behavior:"smooth"});
            }
        }
    };
    chatSend.addEventListener("click", runChat);
    chatInput.addEventListener("keydown", event => {
        if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); runChat(); }
    });
    const runSearch = async () => {
        let question = query.value.trim();
        if (!question) { report(ui("Bitte einen Suchbegriff eingeben.", "Enter a search term.")); return; }
        let libraryAtStart = currentLibraryID;
        let state = getSearchSession(libraryAtStart, "direct");
        if (state.pending || state.loadingMore) return;
        state.draft = query.value;
        state.pending = true;
        clearDocumentOverview(state);
        state.hits = null;
        state.page = null;
        state.resultPages = {};
        state.totalResults = null;
        state.viewPage = 1;
        state.status = ui("Durchsuche Bibliothek …", "Searching library…");
        notifySearchSession(libraryAtStart, "direct");
        try {
            state.scope = await collectionSearchScope(libraryAtStart, libraryCollections.get(libraryAtStart) || 0);
            if (!isCurrentSearchSession(libraryAtStart, "direct", state)) return;
            let data = await request("/search", {library_id:libraryAtStart,...state.scope,query:question,limit:20});
            if (!isCurrentSearchSession(libraryAtStart, "direct", state)) return;
            state.hits = data.results;
            state.page = {id:data.search_id,next:data.next_offset,hasMore:data.has_more};
            storeResultsPage(state, data);
            state.status = Number.isInteger(data.total_results)
                ? data.total_results + ui(" Fundstellen in dieser Bibliothek gefunden.", " passages found in this library.")
                : data.results.length + ui(" Fundstellen aus dieser Bibliothek angezeigt.", " passages shown from this library.");
            loadDocumentOverview(libraryAtStart, "direct", state, question);
        } catch (error) {
            if (isCurrentSearchSession(libraryAtStart, "direct", state))
                state.status = ui("Suche fehlgeschlagen: ", "Search failed: ") + error.message;
        } finally {
            state.pending = false;
            if (isCurrentSearchSession(libraryAtStart, "direct", state)) notifySearchSession(libraryAtStart, "direct");
        }
    };
    search.addEventListener("click", runSearch);
    query.addEventListener("keydown", event => { if (event.key === "Enter") runSearch(); });
    overlay.zitatlotseSetLibrary(libraryID);
    updateSelectedItem();
    overlay.zitatlotseShowTab(tab);
    health.click();
    loadSearchSettings();
    animateSearchWindow(overlay, shell, launchRect);
}

function renderSection({ body, item }) {
    try {
    body.replaceChildren();
    let doc = body.ownerDocument;
    let box = element(doc, "div");
    box.style.cssText = "display:block;width:100%;max-width:100%;min-width:0;box-sizing:border-box;padding:10px;overflow:hidden;";
    let info = element(doc, "div", item
        ? ui("Ausgewählt: ", "Selected: ") + (item.getField("title") || item.attachmentFilename || item.key)
        : ui("Bitte links einen Eintrag oder eine PDF-Datei auswählen.", "Select an item or PDF on the left."));
    info.style.cssText = "white-space:normal;overflow-wrap:anywhere;margin-bottom:10px;line-height:1.35;";
    let status = element(doc, "div", ui("Bereit", "Ready"));
    status.style.cssText = "white-space:normal;overflow-wrap:anywhere;line-height:1.35;margin-top:8px;";
    let single = element(doc, "button", item?.isAttachment() ? ui("Diese PDF verarbeiten", "Process this PDF")
        : ui("Diesen Eintrag verarbeiten", "Process this item"));
    single.style.cssText = "appearance:none;-moz-appearance:none;display:flex;align-items:center;justify-content:center;width:100%;max-width:100%;min-height:42px;box-sizing:border-box;background:#5b36bf;color:white;font-weight:700;line-height:1.25;text-align:center;padding:10px;border:0;border-radius:7px;margin:0 0 8px;cursor:pointer;white-space:normal;box-shadow:0 2px 6px #24134d55;";
    centerButton(single);
    single.disabled = !item || (!item.isRegularItem() && !item.isAttachment());
    let scan = element(doc, "button", ui("Alle neuen/geänderten PDFs verarbeiten", "Process all new/changed PDFs"));
    scan.style.cssText = "appearance:none;-moz-appearance:none;display:flex;align-items:center;justify-content:center;width:100%;max-width:100%;min-height:42px;box-sizing:border-box;background:#ffbf47;color:#292132;font-weight:700;line-height:1.25;text-align:center;padding:9px 10px;border:0;border-radius:7px;margin:0 0 8px;white-space:normal;cursor:pointer;";
    centerButton(scan);
    let search = element(doc, "button", ui("KI-Suche öffnen", "AI search"));
    search.style.cssText = "appearance:none;-moz-appearance:none;display:flex;align-items:center;justify-content:center;width:100%;max-width:100%;min-height:38px;box-sizing:border-box;padding:8px;line-height:1.25;text-align:center;white-space:normal;cursor:pointer;";
    centerButton(search);
    box.append(info, single, scan, search, status);
    let paneProgress = makeProgress(box);
    single.addEventListener("click", async () => {
        single.disabled = true;
        paneProgress.start();
        status.textContent = ui("Eintrag wird verarbeitet …", "Processing item…");
        try {
            let summary = await indexItem(item, message => { status.textContent = message; });
            status.textContent = summaryText(summary);
        } catch (error) {
            status.textContent = ui("Fehler: ", "Error: ") + error.message;
        } finally { single.disabled = false; paneProgress.stop(); }
    });
    scan.addEventListener("click", async () => {
        let libraryID = selectedLibraryID();
        if (!libraryID) { status.textContent = ui("Bitte eine Bibliothek auswählen.", "Select a library."); return; }
        scan.disabled = true;
        paneProgress.start();
        status.textContent = ui("Bibliothek wird geprüft …", "Checking library…");
        try {
            let summary = await indexLibrary(libraryID, (current, message, total) => {
                paneProgress.update(current.pdfs, total);
                status.textContent = message || current.checked + ui(" PDFs geprüft; ", " PDFs checked; ") +
                    current.indexed + ui(" verarbeitet …", " processed…");
            });
            status.textContent = summaryText(summary, true);
        } catch (error) {
            status.textContent = ui("Fehler: ", "Error: ") + error.message;
        } finally { scan.disabled = false; paneProgress.stop(); }
    });
    search.addEventListener("click", () => openSearchWindow(item?.libraryID, "chat", search));
    body.append(box);
    } catch (error) {
        body.textContent = ui("Zitatlotse konnte diesen Eintrag nicht anzeigen: ",
            "Zitatlotse could not display this item: ") + error.message;
        Zotero.logError(error);
    }
}

function startup({ rootURI }) {
    pluginRoot = rootURI;
    ensureLocalService().catch(error => Zotero.logError(error));
    for (let win of Zotero.getMainWindows()) onMainWindowLoad({ window: win });
    registeredSection = Zotero.ItemPaneManager.registerSection({
        paneID: "quote-search-section",
        pluginID: PLUGIN_ID,
        header: { l10nID: "zitatfinder-section", icon: pluginRoot + "search.svg" },
        sidenav: { l10nID: "zitatfinder-sidenav", icon: pluginRoot + "search.svg" },
        bodyXHTML: '<html:div style="padding:10px">' + ui("Eintrag auswählen, um PDFs zu verarbeiten.",
            "Select an item to process PDFs.") + '</html:div>',
        onInit: ({ body, item, setEnabled }) => {
            setEnabled(true);
            let section = body.closest("collapsible-section");
            if (section) section.open = true;
            renderSection({ body, item });
        },
        onItemChange: ({ body, item, setEnabled }) => {
            setEnabled(true);
            renderSection({ body, item });
        },
        onRender: renderSection,
        onToggle: ({ body, item }) => renderSection({ body, item }),
    });
    observerID = Zotero.Notifier.registerObserver({
        notify: async (event, type, ids) => {
            if (type !== "item" || !["add", "modify"].includes(event)) return;
            for (let id of ids) {
                try {
                    let changed = Zotero.Items.get(id);
                    let parent = changed?.isAttachment() && changed.parentID
                        ? Zotero.Items.get(changed.parentID) : changed;
                    await indexItem(parent);
                } catch (error) { Zotero.logError(error); }
            }
        },
    }, ["item"], PLUGIN_ID);
}

function shutdown() {
    searchSessions.clear();
    searchSessionListeners.clear();
    if (observerID) Zotero.Notifier.unregisterObserver(observerID);
    if (registeredSection) Zotero.ItemPaneManager.unregisterSection(registeredSection);
    for (let win of Zotero.getMainWindows()) onMainWindowUnload({ window: win });
}

function isZitatlotseSectionButton(button) {
    let pane = button?.dataset?.pane;
    // Zotero namespaces paneID with the plugin ID; use its returned ID and legacy suffix.
    return typeof pane === "string" && (pane === registeredSection ||
        pane === "quote-search-section" || pane.endsWith("-quote-search-section") ||
        button.dataset.l10nId === "zitatfinder-sidenav");
}

function syncSidenavSearchButtons(win) {
    let doc = win.document;
    let sidenavs = [...(doc.querySelectorAll?.("item-pane-sidenav") || [])];
    let visible = node => {
        if (!node || node.hidden || node.parentElement?.hidden) return false;
        let rects = node.getClientRects?.();
        if (rects && !rects.length) return false;
        let style = win.getComputedStyle?.(node);
        return style?.display !== "none" && style?.visibility !== "hidden";
    };
    let host = sidenavs.find(visible);
    for (let sidenav of sidenavs) {
        // Keep the processing section, but remove its larger navigation icon from the UI.
        let nativeButtons = [...(sidenav.querySelectorAll?.('.btn[data-pane]') || []),
            ...(sidenav.shadowRoot?.querySelectorAll('.btn[data-pane]') || [])];
        for (let button of nativeButtons.filter(isZitatlotseSectionButton)) {
            let wrapper = button.closest?.(".pin-wrapper") || button.parentElement || button;
            wrapper.classList.add("zqs-native-sidenav-hidden");
            button.setAttribute("aria-hidden", "true");
            button.tabIndex = -1;
        }
        let quick = sidenav.querySelector(".zqs-quick-search");
        if (!quick && sidenav === host) {
            quick = doc.createElementNS(HTML, "button");
            quick.className = "zqs-quick-search";
            quick.type = "button";
            quick.title = ui("Zitatlotse: KI-Suche öffnen", "Zitatlotse: AI search");
            quick.setAttribute("aria-label", quick.title);
            quick.style.cssText = "appearance:none;box-sizing:border-box;width:32px;height:32px;" +
                "margin:4px auto;padding:3px;border:0;border-radius:6px;cursor:pointer;" +
                "background-color:transparent;background-position:center;background-repeat:no-repeat;" +
                "background-size:24px 24px;flex:none;";
            quick.style.backgroundImage = 'url("' + pluginRoot + 'search.svg")';
            quick.addEventListener("click", event => {
                if (event.button !== 0) return;
                event.preventDefault();
                event.stopPropagation();
                if (Date.now() - lastPanelCloseAt < 300) return;
                animateOpenButton(quick);
                openSearchWindow(selectedLibraryID() || Zotero.Libraries.userLibraryID, "chat", quick);
            });
            let locate = sidenav.querySelector('.btn[data-action="locate"]')?.parentElement;
            sidenav.insertBefore(quick, locate || sidenav.querySelector("popupset") || null);
        }
        if (!quick) continue;
        let showQuick = sidenav === host;
        let display = showQuick ? "flex" : "none";
        if (quick.style.display !== display) quick.style.display = display;
        quick.tabIndex = showQuick ? 0 : -1;
    }
}

function onMainWindowLoad({ window }) {
    window.MozXULElement.insertFTLIfNeeded("zitatfinder.ftl");
    let doc = window.document;
    ensureWindowStyles(doc);
    let syncQueued = false;
    let scheduleSync = () => {
        if (syncQueued) return;
        syncQueued = true;
        setTimeout(() => {
            syncQueued = false;
            syncSidenavSearchButtons(window);
        }, 50);
    };
    scheduleSync();
    if (window.MutationObserver && doc.documentElement) {
        window.ZitatlotseSidenavObserver = new window.MutationObserver(scheduleSync);
        window.ZitatlotseSidenavObserver.observe(doc.documentElement, {
            childList: true, subtree: true, attributes: true, attributeFilter: ["hidden", "style", "disabled"],
        });
    }
    let tools = doc.getElementById("toolsMenu");
    if (!tools) return;
    doc.getElementById("zitatlotse-menubar")?.remove();
    let menu = doc.createElementNS(XUL, "menu");
    menu.id = "zitatlotse-menubar";
    menu.setAttribute("label", "Zitatlotse");
    let popup = doc.createElementNS(XUL, "menupopup");
    for (let [label, tab] of [[ui("KI-Suche öffnen", "AI search"), "chat"],
        [ui("Direkte Suche", "Direct search"), "search"],
        [ui("Gespeicherte Zitate", "Saved quotes"), "saved"],
        [ui("Verbindungen …", "Connections…"), "settings"],
        [ui("Einstellungen …", "Settings…"), "preferences"]]) {
        let entry = doc.createElementNS(XUL, "menuitem");
        entry.setAttribute("label", label);
        entry.addEventListener("command", () => openSearchWindow(selectedLibraryID() || Zotero.Libraries.userLibraryID, tab));
        popup.appendChild(entry);
    }
    menu.appendChild(popup);
    tools.after(menu);
}

function onMainWindowUnload({ window }) {
    window.ZitatlotseSidenavObserver?.disconnect();
    delete window.ZitatlotseSidenavObserver;
    for (let button of window.document.querySelectorAll?.(".zqs-quick-search") || []) button.remove();
    let overlay = window.document.getElementById("zqs-overlay");
    if (overlay?.zitatlotseClose) overlay.zitatlotseClose();
    else overlay?.remove();
    window.document.getElementById("zitatlotse-menubar")?.remove();
    window.document.getElementById("zqs-progress-style")?.remove();
    window.document.getElementById("zqs-window-style")?.remove();
    window.document.querySelector('[href="zitatfinder.ftl"]')?.remove();
}

function install() {}
function uninstall() {}
