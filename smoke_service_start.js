// Exercise the shipped startup function against the real installed Windows service.
// No provider calls or document text: only health/status and process startup.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const {spawn} = require("node:child_process");

async function main() {
    assert.equal(process.platform, "win32", "This smoke test starts the installed Windows service");
    let launches = 0;
    const context = vm.createContext({
        setTimeout,
        Zotero: {isWin:true, locale:"de-DE", HTTP:{request:async (method, url, options = {}) => {
            let response;
            try {
                response = await fetch(url, {method, signal:AbortSignal.timeout(options.timeout || 5000)});
            } catch (cause) {
                const error = new Error("connection refused", {cause});
                error.status = 0;
                throw error;
            }
            const responseText = await response.text();
            if (!response.ok) {
                const error = new Error(`HTTP ${response.status}`);
                error.status = response.status;
                error.responseText = responseText;
                throw error;
            }
            return {responseText};
        }}},
        Components:{interfaces:{nsIEnvironment:{}, nsIFile:{}, nsIProcess:{}}, classes:{
            "@mozilla.org/process/environment;1":{getService:() => ({get:name => process.env[name] || ""})},
            "@mozilla.org/file/local;1":{createInstance:() => ({
                initWithPath(value){this.path = value;}, append(value){this.path = path.join(this.path, value);},
                exists(){return fs.existsSync(this.path);},
            })},
            "@mozilla.org/process/util;1":{createInstance:() => ({
                init(file){this.executable = file.path;},
                runwAsync(args){
                    launches++;
                    const child = spawn(this.executable, Array.from(args), {
                        windowsHide:true, stdio:"ignore", detached:true,
                        // Startup must work without an activated virtualenv or its cwd.
                        cwd:process.env.TEMP,
                    });
                    child.on("error", error => {console.error(error.message); process.exitCode = 1;});
                    child.unref();
                },
            })},
        }},
    });
    vm.runInContext(fs.readFileSync(path.join(__dirname, "plugin", "bootstrap.js"), "utf8"), context);
    const started = Date.now();
    const responses = await Promise.all([1, 2].map(() =>
        vm.runInContext('serviceRequest("GET", "/status?library_id=1", {timeout:5000})', context)));
    assert.ok(launches <= 1, "Concurrent menu requests must share startup");
    const health = await fetch("http://127.0.0.1:8765/health").then(response => response.json());
    assert.equal(health.service, "zitatlotse");
    assert.equal(health.version, "0.26.3");
    const status = JSON.parse(responses[0].responseText);
    assert.deepEqual(status, JSON.parse(responses[1].responseText));
    const report = {version:health.version, launches, elapsed_seconds:(Date.now()-started)/1000,
        status, passed:true};
    if (process.argv[2]) fs.writeFileSync(process.argv[2], JSON.stringify(report, null, 2));
    console.log(JSON.stringify(report));
}

main().catch(error => {console.error(error.message); process.exitCode = 1;});
