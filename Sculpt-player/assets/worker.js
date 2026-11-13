// Mornye Player extension worker: the native host of Mornye's prelude.js and
// provider.js. Every host function either runs here or goes to the Python
// plugin over a synchronous XHR, which is how the extensions expect it.
(function () {
"use strict";
const query = new URLSearchParams(self.location.search);
const EXT = query.get("e") || "";
const LANE = query.get("l") || "main";
const BASE = self.location.pathname.replace(/[^/]*$/, "");
const NativeURL = self.URL;
const NativeXHR = self.XMLHttpRequest;
const nativeFetch = self.fetch.bind(self);
const nativeSetTimeout = self.setTimeout.bind(self);
const nativeAtob = self.atob.bind(self);
const nativeBtoa = self.btoa.bind(self);
const utf8 = new self.TextEncoder();
const fromUtf8 = new self.TextDecoder("utf-8");
const pendingLogs = [];

function bytesToBase64(bytes) {
    let text = "";
    for (let i = 0; i < bytes.length; i += 0x8000) {
        text += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
    }
    return nativeBtoa(text);
}
function base64ToBytes(text) {
    const raw = nativeAtob(text);
    const bytes = new Uint8Array(raw.length);
    for (let i = 0; i < raw.length; i++) bytes[i] = raw.charCodeAt(i);
    return bytes;
}
function asBytes(value) {
    if (value instanceof Uint8Array) return value;
    if (value instanceof ArrayBuffer) return new Uint8Array(value);
    if (ArrayBuffer.isView(value)) return new Uint8Array(value.buffer, value.byteOffset, value.byteLength);
    return null;
}
function pack(value) {
    return JSON.stringify(value, function (key, item) {
        const bytes = asBytes(item);
        if (bytes) return {__b64: bytesToBase64(bytes)};
        if (typeof item === "function") return {__fn: true};
        if (typeof item === "bigint") return Number(item);
        return item;
    });
}
function unpack(text) {
    return JSON.parse(text, function (key, item) {
        if (item !== null && typeof item === "object" && typeof item.__b64 === "string") {
            return base64ToBytes(item.__b64);
        }
        return item;
    });
}
function post(path, body) {
    const xhr = new NativeXHR();
    xhr.open("POST", BASE + path, false);
    xhr.send(body);
    return xhr;
}
function bridge(name, args) {
    const message = {e: EXT, l: LANE, n: name, a: args};
    if (pendingLogs.length) message.g = pendingLogs.splice(0);
    const xhr = post("host", pack(message));
    if (xhr.status !== 200) throw new Error("Mornye host unavailable: HTTP " + xhr.status);
    const reply = unpack(xhr.responseText);
    if (reply.x !== undefined) throw new Error(reply.x);
    return reply.v;
}

// --- Go-compatible helpers that need no Python -----------------------------

function lowercase(value) {
    let out = "";
    for (const ch of value) {
        const lower = ch.toLowerCase();
        out += lower.codePointAt(0) === undefined ? ch : String.fromCodePoint(lower.codePointAt(0));
    }
    return out;
}
const NORMALIZE_SUFFIXES = [" (remastered)", " (remaster)", " - remastered", " - remaster",
    " (deluxe)", " (deluxe edition)", " - deluxe", " - deluxe edition", " (explicit)", " (clean)",
    " [explicit]", " [clean]", " (album version)", " (single version)", " (radio edit)",
    " (feat.", " (ft.", " feat.", " ft."];
function normalizeMatching(value) {
    value = lowercase(value);
    for (const suffix of NORMALIZE_SUFFIXES) {
        const index = value.indexOf(suffix);
        if (index >= 0) value = value.slice(0, index);
    }
    return value.replace(/[^a-z0-9 ]/g, "").split(/\s+/).filter(Boolean).join(" ");
}
function compareStrings(first, second) {
    first = lowercase(first.trim());
    second = lowercase(second.trim());
    if (first === second) return 1;
    let a = utf8.encode(first), b = utf8.encode(second);
    const maximum = Math.max(a.length, b.length);
    if (!a.length || !b.length) return 0;
    let prefix = 0;
    while (prefix < a.length && prefix < b.length && a[prefix] === b[prefix]) prefix++;
    a = a.subarray(prefix); b = b.subarray(prefix);
    let suffix = 0;
    while (suffix < a.length && suffix < b.length && a[a.length - 1 - suffix] === b[b.length - 1 - suffix]) suffix++;
    a = a.subarray(0, a.length - suffix); b = b.subarray(0, b.length - suffix);
    if (a.length < b.length) { const t = a; a = b; b = t; }
    const row = new Array(b.length + 1);
    for (let j = 0; j <= b.length; j++) row[j] = j;
    for (let i = 0; i < a.length; i++) {
        let diagonal = row[0];
        row[0] = i + 1;
        for (let j = 0; j < b.length; j++) {
            const old = row[j + 1];
            row[j + 1] = Math.min(old + 1, row[j] + 1, diagonal + (a[i] !== b[j] ? 1 : 0));
            diagonal = old;
        }
    }
    return 1 - row[b.length] / maximum;
}
function integerText(value, wide) {
    if (Number.isNaN(value)) return "0";
    if (value >= 9223372036854775807) return "9223372036854775807";
    if (value <= -9223372036854775808) return "-9223372036854775808";
    return BigInt(Math.trunc(value)).toString();
}
function audioTraits(qualities, modes) {
    let atmos = false, hires = false, lossless = false;
    for (let i = 0; i < Math.min(qualities.length, modes.length); i++) {
        const quality = String(qualities[i]).toUpperCase();
        atmos = atmos || String(modes[i]).toUpperCase().includes("ATMOS") || quality.includes("ATMOS");
        hires = hires || ["HI_RES", "HIRES", "MASTER", "MQA"].some(part => quality.includes(part));
        lossless = lossless || quality.includes("LOSSLESS") || quality.includes("FLAC");
        const lower = quality.toLowerCase();
        const depth = parseInt((lower.match(/(\d+)bit/) || [])[1] || "0", 10);
        const rate = parseFloat((lower.match(/([\d.]+)khz/) || [])[1] || "0") || 0;
        if (depth > 0) {
            if (depth > 16 || rate > 48) hires = true;
            else lossless = true;
        }
    }
    const traits = [];
    if (atmos) traits.push("dolby_atmos");
    if (hires) traits.push("hi_res_lossless");
    else if (lossless) traits.push("lossless");
    return traits;
}
function quoteJSON(value) {
    return JSON.stringify(value).replace(/&/g, "\\u0026").replace(/</g, "\\u003c")
        .replace(/>/g, "\\u003e").replace(/\u2028/g, "\\u2028").replace(/\u2029/g, "\\u2029");
}
function compareCodePoints(a, b) {
    const x = Array.from(a), y = Array.from(b);
    for (let i = 0; i < Math.min(x.length, y.length); i++) {
        const d = x[i].codePointAt(0) - y[i].codePointAt(0);
        if (d) return d;
    }
    return x.length - y.length;
}
function goBase64Decode(value, urlSafe) {
    value = value.replace(/[\r\n]/g, "");
    try { return base64ToBytes(value); } catch (_) {}
    if (urlSafe) {
        try { return base64ToBytes(value.replace(/-/g, "+").replace(/_/g, "/")); } catch (_) {}
    }
    return new Uint8Array(0);
}

// net/url Values: ParseQuery, Get (empty is null here, like the Rust host) and Encode.
function queryUnescape(text) {
    return decodeURIComponent(text.replace(/\+/g, " "));
}
function queryEscape(text) {
    return encodeURIComponent(text).replace(/[!'()*]/g, c => "%" + c.charCodeAt(0).toString(16).toUpperCase())
        .replace(/%20/g, "+");
}
function queryObject(input) {
    const values = new Map();
    for (const part of String(input).split("&")) {
        if (!part || part.includes(";")) continue;
        const eq = part.indexOf("=");
        let key, value;
        try {
            key = queryUnescape(eq >= 0 ? part.slice(0, eq) : part);
            value = queryUnescape(eq >= 0 ? part.slice(eq + 1) : "");
        } catch (_) { continue; }
        if (!values.has(key)) values.set(key, []);
        values.get(key).push(value);
    }
    return {
        read(method, key) {
            const found = values.get(key);
            if (method === "has") return found !== undefined;
            if (method === "getAll") return found ? found.slice() : null;
            return found && found[0] ? found[0] : null;
        },
        write(method, key, value) {
            if (method === "append") {
                if (!values.has(key)) values.set(key, []);
                values.get(key).push(value);
            } else if (method === "set") values.set(key, [value]);
            else values.delete(key);
        },
        encode() {
            const keys = Array.from(values.keys()).sort(compareCodePoints);
            const parts = [];
            for (const key of keys) for (const value of values.get(key)) parts.push(queryEscape(key) + "=" + queryEscape(value));
            return parts.join("&");
        }
    };
}
function safeDecode(text) {
    try { return decodeURIComponent(text); } catch (_) { return text; }
}
function parseURL(input, base) {
    let url = null;
    if (base !== undefined) { try { url = new NativeURL(input, base); } catch (_) {} }
    if (!url) { try { url = new NativeURL(input); } catch (_) { return {href: input}; } }
    const raw = url.search.replace(/^\?/, "");
    return {
        href: url.href, protocol: url.protocol, host: url.host, hostname: url.hostname.replace(/^\[|\]$/g, ""),
        port: url.port, pathname: safeDecode(url.pathname), search: raw ? "?" + raw : "",
        hash: url.hash ? "#" + safeDecode(url.hash.slice(1)) : "", origin: url.protocol + "//" + url.host,
        username: safeDecode(url.username), password: safeDecode(url.password), searchParams: queryObject(raw)
    };
}

const boot = bridge("boot", []);
const host = Object.create(null);
for (const flag of ["storageEnabled", "networkEnabled", "filesEnabled", "sessionEnabled", "authEnabled",
        "legacyBackend", "rawFfmpegStub", "managedConsole"]) {
    host[flag] = !!boot[flag];
}
for (const name of ["validateURL", "clearCookies", "storageRead", "storageWrite", "storageRemove",
        "sessionCall", "authCall", "md5", "sha256", "hmacSHA256", "hmacSHA256Base64", "sleep",
        "downloadCancelled", "requestCancelled", "downloadItemActive", "downloadStatus",
        "resolutionRemaining", "providerProgress", "providerPendingVerification", "mediaInfo",
        "mediaConvert", "cryptoText", "generateKey", "blockTransform", "legacySanitize",
        "legacyFilename", "legacyLocalTime", "legacyQuality", "legacyLyrics", "legacyIsrc"]) {
    host[name] = function () { return bridge(name, Array.prototype.slice.call(arguments)); };
}
host.request = function (url, method, body, headers, defaultJson, userAgent, fetch) {
    return bridge("request", [url, method, body, headers, defaultJson, userAgent, fetch]);
};
host.hmacSHA1 = function (key, message) { return bridge("hmacSHA1", [Array.from(key), Array.from(message)]); };
host.extensionLog = function (level, values, count) {
    if (pendingLogs.length < 400) pendingLogs.push([level, values, count]);
};
host.fileCall = function (method, path, value, options, callback) {
    const result = bridge("fileCall", [method, path, value === undefined ? null : value, options || null]);
    if (result && result.data_raw && result.data instanceof Uint8Array) {
        result.data = result.data.slice().buffer;
        delete result.data_raw;
    }
    if (method === "transformPatternedBlocks" && typeof callback === "function" && result && result.success) {
        try { callback(result.bytes_processed, result.bytes_processed); }
        catch (error) { return {success: false, error: "progress callback failed: " + String(error)}; }
    }
    return result;
};
host.downloadCall = function (url, path, options, headers) {
    const text = bridge("downloadCall", [url, path, options || null, headers]);
    if (options && typeof options.onProgress === "function") {
        try {
            const result = JSON.parse(text);
            if (result.success) options.onProgress(result.size || 0, result.size || 0);
        } catch (_) {}
    }
    return text;
};
host.downloadSegmentsCall = function (segments, path, options) {
    const text = bridge("downloadSegmentsCall", [segments, path, options || null]);
    if (options && typeof options.onProgress === "function") {
        try {
            const result = JSON.parse(text);
            if (result.success) options.onProgress(result.size || 0, 0, result.segments || 0, result.segments || 0);
        } catch (_) {}
    }
    return text;
};
host.logOpaqueType = function (value) { return value instanceof Promise ? "<*goja.Promise>" : ""; };
host.providerInteger = integerText;
host.providerTrim = function (value) { return String(value).trim(); };
host.providerAudioTraits = audioTraits;
host.quoteJSON = quoteJSON;
host.sortKeys = function (keys) { return Array.from(keys).sort(compareCodePoints); };
host.encode = function (value) { return Array.from(utf8.encode(value)); };
host.decode = function (bytes) { return fromUtf8.decode(Uint8Array.from(bytes, b => b & 255)); };
host.encodeBytes = function (bytes) { return bytesToBase64(Uint8Array.from(bytes, b => b & 255)); };
host.encodeBuffer = function (bytes) { return bytesToBase64(asBytes(bytes) || new Uint8Array(0)); };
host.decodeBuffer = function (bytes) { return fromUtf8.decode(asBytes(bytes) || new Uint8Array(0)); };
host.parseJSONBuffer = function (bytes) { return JSON.parse(fromUtf8.decode(asBytes(bytes) || new Uint8Array(0))); };
host.base64Encode = function (value) { return bytesToBase64(utf8.encode(value)); };
host.base64Decode = function (value, urlSafe) { return fromUtf8.decode(goBase64Decode(value, urlSafe)); };
host.compareStrings = compareStrings;
host.normalizeMatching = normalizeMatching;
host.compareDuration = function (a, b, tolerance) { return Math.abs(Math.trunc(a) - Math.trunc(b)) <= Math.trunc(tolerance); };
host.parseURL = parseURL;
host.parseQuery = queryObject;
host.appVersion = function () { return boot.appVersion; };
host.appUserAgent = function () { return "Mornye/" + boot.appVersion; };
host.randomUserAgent = function () {
    const r = () => Math.floor(Math.random() * 1e9);
    return "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/"
        + (127 + r() % 26) + ".0." + (6000 + r() % 1500) + "." + (100 + r() % 200) + " Safari/537.36";
};

const gateway = (/*PRELUDE*/)(host);
gateway.provider = (/*PROVIDER*/)(host, gateway.providerHelpers);

function errorText(error) {
    try { return String(error); } catch (_) { return "JavaScript exception"; }
}
function load() {
    importScripts(BASE + "ext/" + encodeURIComponent(EXT) + "/index.js");
    if (!gateway.registered()) throw new Error("extension did not call registerExtension()");
}
async function run(job) {
    const args = job.a || [];
    if (job.op === "load") {
        load();
        const extension = gateway.getExtension();
        if (job.init && extension && typeof extension.initialize === "function") {
            const result = extension.initialize(job.settings || {});
            if (result && typeof result.then === "function") await result;
        }
        return {v: true};
    }
    if (job.op === "function") {
        const extension = gateway.getExtension();
        const fn = extension && typeof extension === "object" ? extension[job.m] : undefined;
        if (typeof fn !== "function") return job.optional ? {v: null} : {x: "function not found: " + job.m};
        let result = fn.apply(extension, args);
        if (result && typeof result.then === "function") result = await result;
        return job.optional ? {v: null} : {j: gateway.serialize(result)};
    }
    if (job.op === "provider") {
        // Mornye parses the returned value as is; awaiting a Promise here only
        // helps extensions that return one, which would otherwise parse empty.
        let value = gateway.provider.invoke(job.m, args);
        if (value && typeof value.then === "function") value = await value;
        return {j: gateway.provider.parse(job.m, value)};
    }
    if (job.op === "download") return {j: gateway.provider.parse("download", gateway.provider.invokeDownload("download", args))};
    if (job.op === "action") return {j: gateway.serialize(gateway.invokeManaged(true, job.m, args))};
    return {x: "unknown job: " + job.op};
}
async function loop() {
    const url = BASE + "next?e=" + encodeURIComponent(EXT) + "&l=" + encodeURIComponent(LANE) + "&g=" + encodeURIComponent(query.get("g") || "");
    for (;;) {
        let job;
        try {
            const response = await nativeFetch(url, {method: "POST", cache: "no-store"});
            job = await response.json();
        } catch (_) {
            await new Promise(resolve => nativeSetTimeout(resolve, 1000));
            continue;
        }
        if (!job || job.op === "noop") continue;
        if (job.op === "stop") { self.close(); return; }
        let out;
        try { out = await run(job); } catch (error) { out = {x: errorText(error)}; }
        out.id = job.id;
        if (pendingLogs.length) out.g = pendingLogs.splice(0);
        try { post("result", pack(out)); } catch (_) {}
    }
}
loop();
})();
