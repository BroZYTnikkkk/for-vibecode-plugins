# SPDX-License-Identifier: LGPL-3.0-only
# Mornye Player for exteraGram. Copyright 2026 BroNik (@BroZYTnikkkk).
# Based on Mornye by zarzet (https://github.com/mornyeapp/Mornye), LGPL-3.0-only.

"""Mornye extensions: manifest, Web Worker runtime and host functions."""

import base64
import calendar
import hashlib
import hmac
import ipaddress
import itertools
import json
import os
import queue
import re
import requests
import secrets
import shutil
import threading
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, unquote, unquote_plus, urljoin, urlsplit, urlunsplit
from .logs import log
from .platform_android import PLATFORM
from .library import fetch_lyrics_raw
from .resources import BRIDGE_PAGE_HTML, MORNYE_PRELUDE_JS, MORNYE_PROVIDER_JS, WORKER_JS


# ---------------------------------------------------------------------------
# Mornye extensions (port of Mornye rust_backend/crates/extensions, LGPL-3.0)
#
# Mornye downloads and searches through JavaScript extensions (.sflx packages
# from extension repositories). Mornye runs them in QuickJS with a native host;
# here they run in a Web Worker of a hidden WebView, and the host functions are
# served by this plugin over a localhost HTTP bridge with a random token.
# prelude.js and provider.js are taken from Mornye unchanged.
# ---------------------------------------------------------------------------

MORNYE_COMPAT_VERSION = "5.2.6"
OFFICIAL_REGISTRY = "https://raw.githubusercontent.com/mornyeapp/Mornye-Extension/main/registry.json"
EXTENSION_TYPES = ("metadata_provider", "download_provider", "lyrics_provider")
MAX_RESPONSE_BYTES = 64 << 20
MAX_READ = 16 << 20
READ_LIMIT_ERROR = "file read exceeds 16 MiB limit; use file.readBytes with offset and length to read it in chunks"
_EXT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


class ExtError(Exception):
    pass


class ExtTimeout(ExtError):
    pass


class HostThrow(Exception):
    """Raised by a host function that throws into JavaScript."""


def _ci(data, key, default=None):
    """Go's JSON decoder matches struct fields case-insensitively."""
    if not isinstance(data, dict):
        return default
    if key in data:
        value = data[key]
        return default if value is None else value
    low = key.lower()
    for k, value in data.items():
        if isinstance(k, str) and k.lower() == low:
            return default if value is None else value
    return default


def _go_query_escape(text):
    return quote(text, safe="-_.~").replace("%20", "+")


def _go_query_parse(raw):
    values = {}
    for part in (raw or "").split("&"):
        if not part or ";" in part:
            continue
        key, _, value = part.partition("=")
        try:
            key = unquote_plus(key, errors="strict")
            value = unquote_plus(value, errors="strict")
        except Exception:
            continue
        values.setdefault(key, []).append(value)
    return values


def _go_query_encode(values):
    parts = []
    for key in sorted(values):
        for value in values[key]:
            parts.append(_go_query_escape(key) + "=" + _go_query_escape(value))
    return "&".join(parts)


def _with_query(url, pairs):
    parts = urlsplit(url)
    values = _go_query_parse(parts.query)
    for key, value in pairs:
        values[key] = [value]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, _go_query_encode(values), parts.fragment))


def _canonical_header(name):
    return "-".join(p[:1].upper() + p[1:].lower() for p in str(name).split("-"))


def _private_host(host):
    host = host.strip().strip("[]").lower()
    if host == "localhost" or host.endswith(".local"):
        return True
    try:
        ip = ipaddress.ip_address(host.split("%")[0])
    except ValueError:
        return False
    if getattr(ip, "ipv4_mapped", None):
        ip = ip.ipv4_mapped
    return ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_multicast or ip.is_unspecified or (
        ip.version == 4 and str(ip) == "255.255.255.255")


def sanitize_filename(name):
    out = []
    for ch in name:
        if ch in '<>:"/\\|?*' or ord(ch) <= 0x1F:
            out.append(" ")
        elif unicodedata.category(ch) != "Cc":
            out.append(ch)
    text = "".join(out).strip().strip(". ")
    words = []
    for word in text.split():
        word = re.sub(r"_{2,}", "_", word)
        words.append(word)
    text = " ".join(words).strip("_ ")
    raw = text.encode("utf-8")
    if len(raw) > 180:
        text = raw[:180].decode("utf-8", "ignore").strip(". ").strip().strip("_ ")
    return text or "Unknown"


def _parse_rfc3339_ns(value):
    m = re.match(r"^\s*(\d{4})-(\d{2})-(\d{2})T(\d{1,2}):(\d{2}):(\d{2})(?:[.,](\d+))?(Z|[+-]\d{2}:\d{2})\s*$", value or "")
    if not m:
        return None
    year, month, day, hour, minute, second = (int(m.group(i)) for i in range(1, 7))
    frac = (m.group(7) or "")[:9].ljust(9, "0")
    try:
        base = calendar.timegm((year, month, day, hour, minute, second, 0, 0, 0))
    except Exception:
        return None
    zone = m.group(8)
    offset = 0
    if zone != "Z":
        sign = -1 if zone[0] == "-" else 1
        offset = sign * (int(zone[1:3]) * 3600 + int(zone[4:6]) * 60)
    return (base - offset) * 1_000_000_000 + int(frac)


def _b64url(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


# -- manifest ----------------------------------------------------------------


class Manifest:
    def __init__(self, data):
        if not isinstance(data, dict):
            raise ExtError("failed to parse manifest JSON: expected an object")
        self.raw = data
        self.name = str(_ci(data, "name", "")).strip()
        self.display_name = str(_ci(data, "displayName", "") or self.name)
        self.version = str(_ci(data, "version", ""))
        self.description = str(_ci(data, "description", ""))
        self.homepage = str(_ci(data, "homepage", ""))
        self.types = [str(t) for t in _ci(data, "type", []) or []]
        perms = _ci(data, "permissions", {}) or {}
        self.network = [str(d) for d in (_ci(perms, "network", []) or [])]
        self.storage = bool(_ci(perms, "storage", False))
        self.file = bool(_ci(perms, "file", False))
        self.allow_http = bool(_ci(perms, "allowHttp", False))
        self.settings = [s for s in (_ci(data, "settings", []) or []) if isinstance(s, dict)]
        self.quality_options = [q for q in (_ci(data, "qualityOptions", []) or []) if isinstance(q, dict)]
        self.search_behavior = _ci(data, "searchBehavior")
        self.url_handler = _ci(data, "urlHandler")
        self.track_matching = _ci(data, "trackMatching")
        self.signed_session = _ci(data, "signedSession")
        self.capabilities = _ci(data, "capabilities", {}) or {}
        self.skip_metadata_enrichment = bool(_ci(data, "skipMetadataEnrichment", False))
        self.stop_fallback = bool(_ci(data, "stopProviderFallback", False)) or bool(_ci(data, "skipBuiltInFallback", False))

    def validate(self):
        if not self.name:
            raise ExtError("manifest validation error: name - name is required")
        if not _EXT_ID_RE.match(self.name) or len(self.name) > 64:
            raise ExtError("manifest validation error: name - invalid extension ID")
        if not self.version.strip():
            raise ExtError("manifest validation error: version - version is required")
        if not self.description.strip():
            raise ExtError("manifest validation error: description - description is required")
        if not self.types:
            raise ExtError("manifest validation error: type - at least one type is required")
        for kind in self.types:
            if kind not in EXTENSION_TYPES:
                raise ExtError("manifest validation error: type - invalid extension type: %s" % kind)
        if self.signed_session:
            base = str(_ci(self.signed_session, "baseUrl", "")).strip()
            if not self.storage:
                raise ExtError("manifest validation error: permissions.storage - signedSession requires storage permission")
            if not str(_ci(self.signed_session, "namespace", "")).strip():
                raise ExtError("manifest validation error: signedSession.namespace - namespace is required")
            if not base.lower().startswith("https://") or not self.is_domain_allowed(urlsplit(base).hostname or ""):
                raise ExtError("manifest validation error: signedSession.baseUrl - baseUrl host must be listed in permissions.network")

    def has_type(self, kind):
        return kind in self.types

    @property
    def has_custom_search(self):
        return bool(self.search_behavior) and bool(_ci(self.search_behavior, "enabled", False))

    @property
    def network_timeout(self):
        try:
            value = float(self.capabilities.get("networkTimeoutSeconds") or 0)
        except Exception:
            value = 0
        return value if value > 0 else 30.0

    def search_filters(self):
        return [f for f in (_ci(self.search_behavior, "filters", []) or []) if isinstance(f, dict) and f.get("id")]

    def is_domain_allowed(self, domain):
        domain = (domain or "").strip().lower()
        for allowed in self.network:
            allowed = allowed.strip().lower()
            if allowed == domain:
                return True
            if allowed.startswith("*.") and len(domain) > len(allowed) - 1 and domain.endswith(allowed[1:]):
                return True
        return False

    def matches_url(self, url):
        handler = self.url_handler
        if not handler or not _ci(handler, "enabled", False):
            return False
        url = url.strip().lower()
        parts = urlsplit(url)
        for pattern in _ci(handler, "patterns", []) or []:
            pattern = str(pattern).strip().lower()
            if not pattern:
                continue
            if "/" not in pattern and pattern.endswith(":"):
                if url.startswith(pattern):
                    return True
                continue
            if not parts.hostname:
                continue
            pattern = pattern.split("://", 1)[-1]
            host, _, path = pattern.partition("/")
            if host and (parts.hostname == host or parts.hostname.endswith("." + host)) and (
                    not path or parts.path.startswith("/" + path)):
                return True
        return False

    def find_quality(self, requested):
        requested = (requested or "").strip().lower()
        if not requested:
            return None
        for option in self.quality_options:
            if str(option.get("id", "")).strip().lower() == requested:
                return option
        return None

    def quality_kind(self, option):
        kind = str(option.get("kind", "")).strip().lower()
        if kind in ("lossless", "lossy", "spatial"):
            return kind
        token = str(option.get("id", "")).strip().lower()
        text = "%s %s" % (token, str(option.get("label", "")).lower())
        if "atmos" in text or "dolby" in text or "surround" in text or token in ("ac4", "ac-4", "eac3", "e-ac-3", "ec-3"):
            return "spatial"
        if any(w in text for w in ("lossless", "flac", "alac", "24-bit", "16-bit")) or token == "hi_res":
            return "lossless"
        if token in ("high", "low") or any(w in text for w in ("mp3", "aac", "opus", "vorbis")):
            return "lossy"
        if token in ("best", "default", ""):
            tier = str(self.capabilities.get("downloadFallbackTier") or "").strip().lower()
            if tier in ("hi_res", "lossless"):
                return "lossless"
            if tier == "low_res":
                return "lossy"
        return ""

    def resolve_download_quality(self, requested, source=None):
        requested = (requested or "").strip()
        if not self.quality_options:
            return requested
        source_option = source.find_quality(requested) if source is not None else None
        kind = (source or self).quality_kind(source_option or {"id": requested})
        exact = self.find_quality(requested)
        if exact is not None:
            target = self.quality_kind(exact)
            if (source is not None and source.name == self.name) or (kind and kind == target) or (not kind and target != "spatial"):
                return str(exact["id"]).strip()
        kind = kind or "lossless"
        for allowed in ([kind, "lossless"] if kind in ("spatial", "lossy") else [kind]):
            for candidate in self.quality_options:
                if str(candidate.get("id", "")).strip() and self.quality_kind(candidate) == allowed:
                    return str(candidate["id"]).strip()
        raise ExtError("provider %s has no compatible %s quality for %r" % (self.name, kind, requested))

    def validate_url(self, url, redirect=False):
        """Port of mornye_network NetworkPermissions::validate."""
        prefix = "redirect blocked" if redirect else "network access denied"
        try:
            parts = urlsplit(url)
        except Exception:
            return "invalid URL"
        if not parts.scheme and not redirect:
            return "invalid URL: scheme is required"
        if parts.scheme != "https" and not (self.allow_http and parts.scheme == "http"):
            return "%s: only https is allowed" % prefix
        if parts.username or parts.password:
            return "invalid URL: embedded credentials are not allowed"
        host = parts.hostname or ""
        if not host:
            return "%s: hostname is required" % ("redirect blocked" if redirect else "invalid URL")
        if _private_host(host):
            return "%s: private/local network '%s' not allowed" % (prefix, host)
        allowed = False
        for entry in self.network:
            entry = entry.strip().lower()
            if entry == host or (entry.startswith("*.") and len(host) > len(entry) - 1 and host.endswith(entry[1:])):
                allowed = True
                break
        if not allowed:
            return "%s: domain '%s' not in allowed list" % (prefix, host)
        return None


# -- localhost bridge and Web Worker lanes ------------------------------------


class CallContext:
    """What a host call needs to know about the operation it serves."""

    def __init__(self, item_id="", resolution_ms=60000, on_progress=None):
        self.item_id = item_id
        self.cancelled = False
        self.cancelled_at = 0.0
        self.grants = []
        self.status = ""
        self.on_progress = on_progress
        self.resolution_deadline = time.time() + resolution_ms / 1000.0

    def cancel(self):
        if not self.cancelled:
            self.cancelled = True
            self.cancelled_at = time.time()

    def check(self):
        if self.cancelled:
            raise HostThrow("download cancelled")

    def report(self, fraction):
        if self.on_progress is not None:
            try:
                self.on_progress(max(0.0, min(1.0, fraction)), self.status)
            except Exception:
                pass


class _Lane:
    def __init__(self, ext, name):
        self.ext = ext
        self.name = name
        self.key = "%s/%s" % (ext, name)
        self.jobs = queue.Queue()
        self.lock = threading.RLock()
        self.loaded = False
        self.generation = 0
        self.ctx = None
        self.dead = None


class JsRuntime:
    """One hidden WebView page; one Web Worker per (extension, lane)."""

    def __init__(self, manager):
        self.manager = manager
        self.token = secrets.token_hex(16)
        self.prefix = "/rt/%s/" % self.token
        self.server = None
        self.lock = threading.Lock()
        self.lanes = {}
        self.host_stats = [0, 0.0]
        self.ctl = queue.Queue()
        self.results = {}
        self.seq = itertools.count(1)
        self.page_seen = 0.0
        self.page_ready = threading.Event()
        self.page_started = 0.0
        self.closed = False
        self._worker_js = None

    @property
    def page_url(self):
        return "http://127.0.0.1:%d%sindex.html" % (self.server.server_address[1], self.prefix)

    def start(self):
        with self.lock:
            if self.closed:
                raise ExtError("extension runtime closed")
            if self.server is None:
                self.server = ThreadingHTTPServer(("127.0.0.1", 0), _bridge_handler(self))
                self.server.daemon_threads = True
                threading.Thread(target=self.server.serve_forever, name="mornye-bridge", daemon=True).start()
            stale = self.page_started and time.time() - max(self.page_seen, self.page_started) > 80
            if not self.page_started or stale:
                if stale:
                    self._reset_lanes("extension page stopped responding")
                self.page_ready.clear()
                self.page_started = time.time()
                PLATFORM.start_page(self.page_url)
        if not self.page_ready.wait(25):
            with self.lock:
                self.page_started = 0.0
            raise ExtError("extension runtime did not start (WebView unavailable?)")

    def close(self):
        self.closed = True
        with self.lock:
            for lane in self.lanes.values():
                lane.loaded = False
                lane.dead = "extension runtime closed"
            for slot in list(self.results.values()):
                slot["result"] = {"x": "extension runtime closed"}
                slot["event"].set()
            PLATFORM.stop_page()
            if self.server is not None:
                threading.Thread(target=self.server.shutdown, daemon=True).start()

    def _reset_lanes(self, reason):
        for lane in self.lanes.values():
            lane.loaded = False
            lane.generation += 1
            lane.dead = reason

    def _lane(self, ext, name):
        with self.lock:
            lane = self.lanes.get((ext, name))
            if lane is None:
                lane = self.lanes[(ext, name)] = _Lane(ext, name)
            return lane

    def unload(self, ext):
        """Retire every worker of an extension, e.g. after settings change."""
        with self.lock:
            lanes = [lane for (e, _), lane in self.lanes.items() if e == ext]
        for lane in lanes:
            self._kill(lane, "extension reloaded")

    def _kill(self, lane, reason):
        lane.loaded = False
        lane.generation += 1
        lane.dead = reason
        try:
            while True:
                lane.jobs.get_nowait()
        except queue.Empty:
            pass
        self.ctl.put({"op": "kill", "key": lane.key})

    def call(self, ext, lane_name, job, timeout, ctx=None):
        self.start()
        lane = self._lane(ext, lane_name)
        with lane.lock:
            if not lane.loaded:
                lane.generation += 1
                lane.dead = None
                self.ctl.put({"op": "spawn", "key": lane.key, "e": ext, "l": lane.name, "g": lane.generation})
                try:
                    self._run(lane, {"op": "load", "init": True, "settings": self.manager.runtime_settings(ext)}, 45, None)
                except Exception:
                    self._kill(lane, "load failed")
                    raise
                lane.loaded = True
            return self._run(lane, job, timeout, ctx)

    def _run(self, lane, job, timeout, ctx):
        job = dict(job)
        job["id"] = next(self.seq)
        slot = {"event": threading.Event(), "result": None, "lane": lane}
        self.results[job["id"]] = slot
        lane.ctx = ctx or CallContext()
        lane.jobs.put(job)
        deadline = time.time() + timeout
        try:
            while not slot["event"].wait(0.25):
                if self.closed:
                    raise ExtError("extension runtime closed")
                if lane.dead:
                    raise ExtError("extension worker failed: %s" % lane.dead)
                now = time.time()
                if now > deadline:
                    self._kill(lane, "timeout")
                    raise ExtTimeout("%s timeout: extension took too long to respond" % job.get("m", job["op"]))
                if ctx is not None and ctx.cancelled and now - ctx.cancelled_at > 15:
                    self._kill(lane, "cancelled")
                    raise ExtError("download cancelled")
            result = slot["result"] or {}
        finally:
            self.results.pop(job["id"], None)
            lane.ctx = None
        if "x" in result:
            raise ExtError(str(result["x"]))
        if "j" in result:
            return json.loads(result["j"])
        return result.get("v")

    # -- bridge endpoints (run on the HTTP server threads) --------------------

    def on_ctl(self):
        self.page_seen = time.time()
        self.page_ready.set()
        commands = []
        try:
            commands.append(self.ctl.get(timeout=20))
            while True:
                commands.append(self.ctl.get_nowait())
        except queue.Empty:
            pass
        self.page_seen = time.time()
        return commands

    def on_next(self, ext, name, generation):
        lane = self.lanes.get((ext, name))
        if lane is None or str(lane.generation) != str(generation):
            return {"op": "stop"}
        try:
            return lane.jobs.get(timeout=20)
        except queue.Empty:
            return {"op": "noop"} if str(lane.generation) == str(generation) else {"op": "stop"}

    def on_result(self, message):
        logs = message.get("g")
        slot = self.results.get(message.get("id"))
        if logs and slot is not None:
            self.manager.record_logs(slot["lane"].ext, logs)
        if slot is not None:
            slot["result"] = message
            slot["event"].set()

    def on_worker_error(self, key, text):
        for lane in list(self.lanes.values()):
            if lane.key == key:
                lane.dead = text or "worker error"
                lane.loaded = False
        self.manager.record_logs(key.split("/")[0], [["ERROR", ["worker: %s" % text], 1]])

    def worker_js(self):
        if self._worker_js is None:
            self._worker_js = (WORKER_JS.replace("(/*PRELUDE*/)", "(" + MORNYE_PRELUDE_JS.strip() + ")")
                               .replace("(/*PROVIDER*/)", "(" + MORNYE_PROVIDER_JS.strip() + ")"))
        return self._worker_js


def _bridge_handler(rt):
    def unpack(text):
        def hook(obj):
            if len(obj) == 1 and isinstance(obj.get("__b64"), str):
                return base64.b64decode(obj["__b64"])
            return obj
        return json.loads(text, object_hook=hook)

    def default(obj):
        if isinstance(obj, (bytes, bytearray)):
            return {"__b64": base64.b64encode(bytes(obj)).decode("ascii")}
        raise TypeError("not JSON serializable: %r" % type(obj))

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        disable_nagle_algorithm = True

        def log_message(self, *args):
            pass

        def _send(self, code, body, ctype="application/json; charset=utf-8"):
            data = body.encode("utf-8") if isinstance(body, str) else body
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self._headers_buffer.append(b"\r\n")
            self._headers_buffer.append(data)
            self.flush_headers()

        def _route(self):
            parts = urlsplit(self.path)
            if not parts.path.startswith(rt.prefix):
                return None, {}
            return parts.path[len(rt.prefix):], {k: v[0] for k, v in parse_qs(parts.query).items()}

        def do_GET(self):
            name, _ = self._route()
            if name == "index.html":
                return self._send(200, BRIDGE_PAGE_HTML, "text/html; charset=utf-8")
            if name == "worker.js":
                return self._send(200, rt.worker_js(), "application/javascript; charset=utf-8")
            if name and name.startswith("ext/") and name.endswith("/index.js"):
                ext = unquote(name[4:-9])
                path = rt.manager.source_path(ext)
                if path and os.path.isfile(path):
                    with open(path, "rb") as f:
                        return self._send(200, f.read(), "application/javascript; charset=utf-8")
            self._send(404, "{}")

        def do_POST(self):
            name, params = self._route()
            size = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(size).decode("utf-8", "replace") if size else ""
            if name is None:
                return self._send(404, "{}")
            try:
                if name == "ctl":
                    return self._send(200, json.dumps(rt.on_ctl()))
                if name == "next":
                    return self._send(200, json.dumps(rt.on_next(params.get("e", ""), params.get("l", ""), params.get("g", ""))))
                if name == "result":
                    rt.on_result(unpack(body))
                    return self._send(200, "{}")
                if name == "werr":
                    rt.on_worker_error(params.get("k", ""), body[:500])
                    return self._send(200, "{}")
                if name == "host":
                    started = time.time()
                    message = unpack(body)
                    if message.get("g"):
                        rt.manager.record_logs(message.get("e", ""), message["g"])
                    try:
                        value = rt.manager.api.handle(message.get("e", ""), message.get("l", ""), message.get("n", ""), message.get("a") or [])
                        reply = {"v": value}
                    except HostThrow as e:
                        reply = {"x": str(e)}
                    except Exception as e:
                        reply = {"x": "%s: %s" % (type(e).__name__, e)}
                    out = self._send(200, json.dumps(reply, default=default))
                    if message.get("n") not in ("sleep", "request", "downloadCall", "downloadSegmentsCall", "fileCall",
                                                "mediaInfo", "mediaConvert", "legacyLyrics", "authCall", "sessionCall"):
                        stats = rt.host_stats
                        stats[0] += 1
                        stats[1] += time.time() - started
                        if stats[0] % 10 == 0:
                            log("[Mornye] bridge: %d local host calls, %.1f ms each in Python" % (stats[0], stats[1] * 1000 / stats[0]))
                    return out
            except Exception as e:
                return self._send(500, json.dumps({"x": str(e)}))
            self._send(404, "{}")

    return Handler


# -- host functions -------------------------------------------------------------


class HostApi:
    def __init__(self, manager):
        self.manager = manager
        self.sessions = {}
        self.lock = threading.Lock()
        self.auth = {}

    def handle(self, ext_id, lane_name, name, args):
        manifest = self.manager.manifest(ext_id)
        if manifest is None:
            raise HostThrow("extension '%s' is not installed" % ext_id)
        lane = self.manager.runtime.lanes.get((ext_id, lane_name))
        ctx = lane.ctx if lane is not None and lane.ctx is not None else CallContext()
        fn = getattr(self, "h_" + name, None)
        if fn is None:
            raise HostThrow("host function not available: %s" % name)
        return fn(manifest, ctx, *args)

    # -- environment

    def h_boot(self, m, ctx):
        network = bool(m.network)
        return {
            "storageEnabled": m.storage, "networkEnabled": network, "filesEnabled": m.file,
            "sessionEnabled": network and bool(m.signed_session), "authEnabled": network,
            "legacyBackend": True, "rawFfmpegStub": True, "managedConsole": True,
            "appVersion": MORNYE_COMPAT_VERSION,
        }

    def h_sleep(self, m, ctx, ms):
        end = time.time() + min(max(float(ms or 0), 0), 300000) / 1000.0
        while time.time() < end:
            if ctx.cancelled:
                return False
            time.sleep(min(0.05, max(0.0, end - time.time())))
        return not ctx.cancelled

    def h_downloadCancelled(self, m, ctx):
        return bool(ctx.item_id) and ctx.cancelled

    def h_requestCancelled(self, m, ctx):
        return ctx.cancelled

    def h_downloadItemActive(self, m, ctx):
        return bool(ctx.item_id)

    def h_downloadStatus(self, m, ctx, status):
        ctx.status = str(status).strip().lower()

    def h_resolutionRemaining(self, m, ctx):
        return max(0, int((ctx.resolution_deadline - time.time()) * 1000))

    def h_providerProgress(self, m, ctx, percent):
        if ctx.item_id and not ctx.cancelled:
            ctx.report(float(percent) / 100.0)

    def h_providerPendingVerification(self, m, ctx):
        return m.name if self.manager.sessions.pending_fresh(m.name) else None

    # -- hashing

    def h_md5(self, m, ctx, value):
        return hashlib.md5(str(value).encode("utf-8")).hexdigest()

    def h_sha256(self, m, ctx, value):
        return hashlib.sha256(str(value).encode("utf-8")).hexdigest()

    def h_hmacSHA256(self, m, ctx, message, key):
        return hmac.new(str(key).encode("utf-8"), str(message).encode("utf-8"), hashlib.sha256).hexdigest()

    def h_hmacSHA256Base64(self, m, ctx, message, key):
        digest = hmac.new(str(key).encode("utf-8"), str(message).encode("utf-8"), hashlib.sha256).digest()
        return base64.b64encode(digest).decode("ascii")

    def h_hmacSHA1(self, m, ctx, key, message):
        return list(hmac.new(bytes(int(b) & 255 for b in key), bytes(int(b) & 255 for b in message), hashlib.sha1).digest())

    def h_generateKey(self, m, ctx, length):
        length = int(length)
        if not 1 <= length <= 4096:
            return {"success": False, "error": "key length must be an integer between 1 and 4096 bytes"}
        key = os.urandom(length)
        return {"success": True, "key": base64.b64encode(key).decode("ascii"), "hex": key.hex()}

    def h_cryptoText(self, m, ctx, decrypt, data, key):
        key = hashlib.sha256(str(key).encode("utf-8")).digest()
        try:
            if decrypt:
                raw = base64.b64decode(str(data))
                plain = PLATFORM.aes_gcm(False, key, raw[:12], raw[12:])
                return {"success": True, "data": plain.decode("utf-8", "replace")}
            nonce = os.urandom(12)
            sealed = PLATFORM.aes_gcm(True, key, nonce, str(data).encode("utf-8"))
            return {"success": True, "data": base64.b64encode(nonce + sealed).decode("ascii")}
        except Exception:
            return {"success": False, "error": "invalid base64 ciphertext" if decrypt else "encryption failed"}

    def h_blockTransform(self, m, ctx, operation, payload, options):
        return {"success": False, "error": "block cipher helpers are not available in Mornye Player"}

    # -- logging

    def h_extensionLog(self, m, ctx, level, values, count):
        self.manager.record_logs(m.name, [[level, values, count]])

    # -- network

    def session(self, name):
        with self.lock:
            sess = self.sessions.get(name)
            if sess is None:
                sess = requests.Session()
                sess.headers.clear()
                sess.headers["Accept-Encoding"] = "gzip, deflate"
                sess.trust_env = True
                self.sessions[name] = sess
            return sess

    def h_validateURL(self, m, ctx, url):
        return m.validate_url(str(url))

    def h_clearCookies(self, m, ctx):
        self.session(m.name).cookies.clear()
        return True

    def open(self, m, ctx, method, url, data=None, headers=None, timeout=None, stream=True):
        """One HTTP exchange; redirects stay inside the extension's domains."""
        ctx.check()
        sess = self.session(m.name)
        method = (method or "GET").upper()
        headers = dict(headers or {})
        current = url
        for _ in range(11):
            r = sess.request(method, current, data=data, headers=headers, timeout=timeout or m.network_timeout,
                             allow_redirects=False, stream=stream)
            location = r.headers.get("Location")
            if r.status_code in (301, 302, 303, 307, 308) and location:
                r.close()
                current = urljoin(current, location)
                denied = m.validate_url(current, redirect=True)
                if denied:
                    raise HostThrow(denied)
                if r.status_code in (301, 302, 303) and method not in ("GET", "HEAD"):
                    method, data = "GET", None
                    headers = {k: v for k, v in headers.items() if k.lower() not in ("content-type", "content-length")}
                continue
            return r, current
        raise HostThrow("stopped after 10 redirects")

    def _read_all(self, ctx, r, limit=MAX_RESPONSE_BYTES):
        chunks = []
        size = 0
        for chunk in r.iter_content(64 * 1024):
            ctx.check()
            size += len(chunk)
            if size > limit:
                raise HostThrow("response body exceeds %d MiB" % (limit >> 20))
            chunks.append(chunk)
        return b"".join(chunks)

    def h_request(self, m, ctx, url, method, body, headers, default_json, user_agent, fetch):
        url = str(url)
        denied = m.validate_url(url)
        if denied:
            return {"error": denied}
        hdrs = {str(k): str(v) for k, v in (headers or {}).items()}
        names = {k.lower() for k in hdrs}
        if "user-agent" not in names:
            hdrs["User-Agent"] = user_agent
        if default_json and "content-type" not in names:
            hdrs["Content-Type"] = "application/json"
        data = str(body).encode("utf-8") if body else None
        try:
            r, final = self.open(m, ctx, method, url, data, hdrs)
            try:
                content = self._read_all(ctx, r)
            finally:
                r.close()
        except HostThrow as e:
            return {"error": str(e)}
        except Exception as e:
            return {"error": '%s "%s": %s' % (str(method).title(), url, e)}
        grouped = {}
        try:
            items = r.raw.headers.items()
        except Exception:
            items = r.headers.items()
        for key, value in items:
            grouped.setdefault(_canonical_header(key), []).append(value)
        result = {
            "status": r.status_code, "ok": 200 <= r.status_code < 300, "url": final,
            "headers": {k: (v[0] if len(v) == 1 else v) for k, v in grouped.items()},
        }
        if fetch:
            result["statusText"] = "%d %s" % (r.status_code, r.reason or "")
            result["bytes"] = content
        else:
            result["statusCode"] = r.status_code
            result["body"] = content.decode("utf-8", "replace")
        return result

    # -- storage

    def _store_path(self, m, credentials):
        return os.path.join(self.manager.data_dir(m.name), "credentials.json" if credentials else "storage.json")

    def _store_load(self, path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _store_save(self, path, data):
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, path)

    def h_storageRead(self, m, ctx, credentials, key):
        if not m.storage:
            return json.dumps({"error": "storage permission denied"})
        data = self._store_load(self._store_path(m, credentials))
        if key in data:
            return json.dumps({"found": True, "value": data[key]})
        return json.dumps({"found": False})

    def h_storageWrite(self, m, ctx, credentials, key, value):
        if not m.storage:
            return json.dumps({"success": False, "error": "storage permission denied"})
        with self.lock:
            path = self._store_path(m, credentials)
            data = self._store_load(path)
            try:
                data[key] = json.loads(value)
            except Exception as e:
                return json.dumps({"success": False, "error": str(e)})
            self._store_save(path, data)
        return json.dumps({"success": True})

    def h_storageRemove(self, m, ctx, credentials, key):
        with self.lock:
            path = self._store_path(m, credentials)
            data = self._store_load(path)
            data.pop(key, None)
            self._store_save(path, data)
        return json.dumps({"success": True})

    # -- files

    def resolve(self, m, ctx, path):
        root = os.path.realpath(self.manager.data_dir(m.name))
        path = str(path or "")
        if os.path.isabs(path):
            absolute = os.path.normpath(path)
            for grant in [root] + list(ctx.grants):
                grant = os.path.normpath(grant)
                if absolute == grant or absolute.startswith(grant + os.sep):
                    return absolute
            raise HostThrow("file access denied: absolute paths are not allowed. Use relative paths within extension sandbox")
        absolute = os.path.normpath(os.path.join(root, path))
        if absolute != root and not absolute.startswith(root + os.sep):
            raise HostThrow("file access denied: path '%s' is outside sandbox" % path)
        return absolute

    @staticmethod
    def _decode_data(value, encoding):
        encoding = (encoding or "base64").strip().lower()
        if isinstance(value, (bytes, bytearray)):
            return bytes(value)
        if isinstance(value, list):
            return bytes(int(b) & 255 for b in value)
        text = "" if value is None else str(value)
        if encoding in ("utf8", "utf-8", "text"):
            return text.encode("utf-8")
        if encoding == "hex":
            return bytes.fromhex(text)
        if encoding in ("base64url", "base64-url"):
            return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
        return base64.b64decode(text)

    @staticmethod
    def _encode_data(data, encoding):
        encoding = (encoding or "base64").strip().lower()
        if encoding == "hex":
            return data.hex()
        if encoding in ("base64url", "base64-url"):
            return _b64url(data)
        if encoding in ("utf8", "utf-8", "text"):
            return data.decode("utf-8", "replace")
        return base64.b64encode(data).decode("ascii")

    def h_fileCall(self, m, ctx, method, path, value, options):
        try:
            result = self._file_call(m, ctx, method, path, value, options if isinstance(options, dict) else {})
        except HostThrow as e:
            result = {"success": False, "error": str(e)}
        except Exception as e:
            result = {"success": False, "error": str(e)}
        if method == "exists":
            return bool(result.get("success"))
        return result

    def _file_call(self, m, ctx, method, path, value, opts):
        if not m.file:
            raise HostThrow("file permission denied")
        ctx.check()
        target = self.resolve(m, ctx, path)
        result = {"success": True}
        if method in ("exists", "getSize"):
            size = os.stat(target).st_size
            if method == "getSize":
                result["size"] = size
        elif method == "delete":
            os.remove(target)
        elif method == "read":
            with open(target, "rb") as f:
                data = f.read(MAX_READ + 1)
            if len(data) > MAX_READ:
                raise HostThrow(READ_LIMIT_ERROR)
            result["data"] = data.decode("utf-8", "replace")
        elif method == "readBytes":
            offset = int(opts.get("offset") or 0)
            length = int(opts.get("length") if opts.get("length") is not None else -1)
            if offset < 0:
                raise HostThrow("offset must be >= 0")
            size = os.path.getsize(target)
            offset = min(offset, size)
            length = size - offset if length < 0 else length
            if length > MAX_READ:
                raise HostThrow(READ_LIMIT_ERROR)
            with open(target, "rb") as f:
                f.seek(offset)
                data = f.read(min(length, size - offset))
            encoding = str(opts.get("encoding") or "base64").strip().lower()
            if encoding in ("bytes", "raw"):
                result["data"] = data
                result["data_raw"] = True
            else:
                result["data"] = self._encode_data(data, encoding)
            result.update({"bytes_read": len(data), "offset": offset, "size": size, "eof": offset + len(data) >= size})
        elif method in ("write", "writeBytes"):
            append = bool(opts.get("append"))
            has_offset = "offset" in opts and method == "writeBytes"
            if append and has_offset:
                raise HostThrow("append and offset cannot be used together")
            data = self._decode_data(value, "utf8" if method == "write" else opts.get("encoding"))
            os.makedirs(os.path.dirname(target), exist_ok=True)
            if method == "write":
                tmp = target + ".tmp-%s" % secrets.token_hex(4)
                with open(tmp, "wb") as f:
                    f.write(data)
                os.replace(tmp, target)
            else:
                mode = "ab" if append else ("r+b" if os.path.exists(target) and not opts.get("truncate") else "wb")
                with open(target, mode) as f:
                    if has_offset:
                        f.seek(int(opts.get("offset") or 0))
                    f.write(data)
                result["bytes_written"] = len(data)
                result["size"] = os.path.getsize(target)
            result["path"] = target
        elif method in ("copy", "move", "transformPatternedBlocks"):
            if not isinstance(value, str) or not value:
                raise HostThrow("destination path is required")
            destination = self.resolve(m, ctx, value)
            os.makedirs(os.path.dirname(destination), exist_ok=True)
            if method == "transformPatternedBlocks":
                return self._transform(ctx, target, destination, opts)
            if method == "move":
                shutil.move(target, destination)
            else:
                shutil.copyfile(target, destination)
            result["path"] = destination
        else:
            raise HostThrow("unknown file operation")
        return result

    def _transform(self, ctx, source, destination, opts):
        """file.transformPatternedBlocks: decrypt every Nth fixed-size segment."""
        algorithm = str(opts.get("algorithm") or "").lower()
        mode = str(opts.get("mode") or "cbc").lower()
        if not algorithm:
            raise HostThrow("algorithm is required")
        if mode not in ("cbc", "ctr"):
            raise HostThrow("unsupported block cipher mode: %s" % mode)
        if str(opts.get("padding") or "none").lower() != "none":
            raise HostThrow("patterned file transforms only support padding: none")
        key = self._decode_data(opts.get("key"), opts.get("keyEncoding") or "utf8")
        iv = self._decode_data(opts.get("iv"), opts.get("ivEncoding") or "utf8")
        if not key:
            raise HostThrow("key is required")
        decrypt = str(opts.get("operation") or "decrypt").lower() == "decrypt"
        segment = int(opts.get("segmentSize") or 0)
        every = int(opts.get("transformEvery") or 1)
        offset = int(opts.get("transformOffset") or 0)
        partial = bool(opts.get("transformPartial"))
        if not 1 <= segment <= MAX_READ:
            raise HostThrow("segmentSize must be between 1 and %d bytes" % MAX_READ)
        if every <= 0 or not 0 <= offset < every:
            raise HostThrow("transformOffset must be between 0 and transformEvery - 1")
        block = 8 if algorithm == "blowfish" else 16
        if len(iv) != block:
            raise HostThrow("iv must be %d bytes for %s" % (block, algorithm))
        cipher = PLATFORM.block_cipher(algorithm, mode, key, iv, decrypt)
        tmp = destination + ".transform.partial"
        processed = index = transformed = 0
        with open(source, "rb") as src, open(tmp, "wb") as dst:
            while True:
                ctx.check()
                chunk = src.read(segment)
                if not chunk:
                    break
                if index % every == offset and (len(chunk) == segment or partial):
                    if mode == "cbc" and len(chunk) % block:
                        raise HostThrow("selected segment %d is not a multiple of %d bytes" % (index, block))
                    chunk = cipher(chunk)
                    transformed += 1
                dst.write(chunk)
                processed += len(chunk)
                index += 1
        os.replace(tmp, destination)
        return {"success": True, "path": destination, "bytes_processed": processed,
                "segments_processed": index, "segments_transformed": transformed}

    # -- transfers

    def _transfer(self, m, ctx, url, target, headers, attempts=3, part_of=None):
        """Stream one URL to a file. Returns (ok, size, kind, message, attempt)."""
        headers = dict(headers or {})
        if not any(k.lower() == "user-agent" for k in headers):
            headers["User-Agent"] = "Mornye/" + MORNYE_COMPAT_VERSION
        tmp = target + ".part"
        message, kind = "", "transient_network"
        for attempt in range(1, attempts + 1):
            ctx.check()
            try:
                r, _ = self.open(m, ctx, "GET", url, None, headers, timeout=(20, 90))
                with r:
                    if r.status_code != 200:
                        message = "HTTP error: %d" % r.status_code
                        kind = "rate_limited" if r.status_code == 429 else (
                            "transient_network" if r.status_code >= 500 or r.status_code == 408 else "http_error")
                        if kind == "http_error":
                            return False, 0, kind, message, attempt
                        raise IOError(message)
                    total = int(r.headers.get("Content-Length") or 0)
                    size = 0
                    with open(tmp, "wb") as f:
                        for chunk in r.iter_content(256 * 1024):
                            ctx.check()
                            f.write(chunk)
                            size += len(chunk)
                            if part_of is not None:
                                part_of(len(chunk))
                            elif total:
                                ctx.report(size / float(total))
                os.replace(tmp, target)
                return True, size, "", "", attempt
            except HostThrow as e:
                if "cancel" in str(e):
                    return False, 0, "cancelled", str(e), attempt
                return False, 0, "permission", str(e), attempt
            except Exception as e:
                message = message or str(e)
                if attempt < attempts:
                    time.sleep(min(8, 2 ** (attempt - 1)))
            finally:
                if os.path.exists(tmp):
                    try:
                        os.remove(tmp)
                    except Exception:
                        pass
        return False, 0, kind, message or "download failed", attempts

    def h_downloadCall(self, m, ctx, url, path, options, headers):
        try:
            if not m.network:
                raise HostThrow("network access unavailable")
            denied = m.validate_url(str(url))
            if denied:
                raise HostThrow(denied)
            target = self.resolve(m, ctx, path)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            attempts = int((options or {}).get("maxAttempts") or 3) if isinstance(options, dict) else 3
            ok, size, kind, message, attempt = self._transfer(m, ctx, str(url), target, json.loads(headers or "{}"),
                                                              max(1, min(8, attempts)))
        except HostThrow as e:
            return json.dumps({"success": False, "error": str(e)})
        if ok:
            return json.dumps({"success": True, "path": target, "size": size, "attempts": attempt})
        return json.dumps({"success": False, "message": "", "error": message, "error_type": kind, "attempts": attempt})

    def h_downloadSegmentsCall(self, m, ctx, specs, path, options):
        def failure(kind, message, attempts=0):
            return json.dumps({"success": False, "error": message, "error_type": kind, "attempts": attempts})
        try:
            segments = json.loads(specs)
            target = self.resolve(m, ctx, path)
        except HostThrow as e:
            return failure("permission", str(e))
        except Exception as e:
            return failure("invalid_request", str(e))
        for i, seg in enumerate(segments):
            seg["url"] = str(seg.get("url") or "").strip()
            if not seg["url"]:
                return failure("invalid_request", "segment %d URL is empty" % i)
            denied = m.validate_url(seg["url"])
            if denied:
                return failure("permission", denied)
        opts = options if isinstance(options, dict) else {}
        workers = max(1, min(8, int(opts.get("maxParallel") or 4)))
        folder = target + ".segments"
        os.makedirs(folder, exist_ok=True)
        done = {"bytes": 0, "count": 0}
        lock = threading.Lock()

        def grow(n):
            with lock:
                done["bytes"] += n

        def fetch(i):
            part = os.path.join(folder, "%06d" % i)
            result = self._transfer(m, ctx, segments[i]["url"], part, segments[i].get("headers") or {}, 4, grow)
            with lock:
                done["count"] += 1
                ctx.report(done["count"] / float(len(segments)))
            return result

        try:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                results = list(pool.map(fetch, range(len(segments))))
            for ok, _, kind, message, attempt in results:
                if not ok:
                    return failure(kind or "transient_network", message, attempt)
            size = 0
            with open(target, "wb") as out:
                for i in range(len(segments)):
                    ctx.check()
                    with open(os.path.join(folder, "%06d" % i), "rb") as f:
                        shutil.copyfileobj(f, out, 1 << 20)
            size = os.path.getsize(target)
        except HostThrow as e:
            return failure("cancelled", str(e))
        finally:
            shutil.rmtree(folder, ignore_errors=True)
        return json.dumps({"success": True, "path": target, "size": size, "segments": len(segments)})

    # -- media

    def h_mediaInfo(self, m, ctx, path):
        try:
            info = PLATFORM.media_quality(self.resolve(m, ctx, path))
            return dict({"success": True}, **info)
        except Exception as e:
            return {"success": False, "error": str(e)}

    def h_mediaConvert(self, m, ctx, source, output, options):
        try:
            src = self.resolve(m, ctx, source)
            dst = self.resolve(m, ctx, output)
            codec = str((options or {}).get("codec") or "copy").lower() if isinstance(options, dict) else "copy"
            if codec != "copy":
                return json.dumps({"success": False, "error": "only codec copy is supported (no FFmpeg in Mornye Player)"})
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            if not PLATFORM.remux(src, dst):
                shutil.copyfile(src, dst)
            return json.dumps({"success": True, "path": dst, "output_path": dst})
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)})

    # -- legacy gobackend helpers

    def h_legacySanitize(self, m, ctx, value):
        return sanitize_filename(str(value))

    def h_legacyFilename(self, m, ctx, template, metadata):
        fields = json.loads(metadata or "{}")

        def sub(match):
            key = match.group(1)
            value = fields.get(key, fields.get(key.lower(), ""))
            if isinstance(value, float) and value.is_integer():
                value = int(value)
            if key in ("track", "track_number", "disc", "disc_number") and isinstance(value, int):
                return "%02d" % value
            return sanitize_filename(str(value)) if value not in ("", None) else ""
        return re.sub(r"\{([a-zA-Z_]+)\}", sub, str(template)).strip()

    def h_legacyLocalTime(self, m, ctx):
        now = int(time.time())
        t = time.gmtime(now)
        return json.dumps({"year": t.tm_year, "month": t.tm_mon, "day": t.tm_mday, "hour": t.tm_hour,
                           "minute": t.tm_min, "second": t.tm_sec, "weekday": (t.tm_wday + 1) % 7,
                           "offsetMinutes": 0, "timezone": "UTC", "timestamp": now})

    def h_legacyQuality(self, m, ctx, path):
        try:
            info = PLATFORM.media_quality(self.resolve(m, ctx, path))
            return json.dumps({"bitDepth": info.get("bit_depth", 0), "sampleRate": info.get("sample_rate", 0),
                               "totalSamples": info.get("total_samples", 0), "duration": info.get("duration", 0),
                               "codec": info.get("codec", "")})
        except Exception as e:
            return json.dumps({"error": str(e)})

    def h_legacyLyrics(self, m, ctx, spotify_id, track, artist, path, duration, text, numeric):
        try:
            seconds = float(duration or 0) / 1000.0
            data = fetch_lyrics_raw(str(track), str(artist), seconds)
            if data is None:
                return json.dumps({"lyrics": ""})
            if data.get("instrumental"):
                return json.dumps({"lyrics": "[instrumental:true]"})
            body = data.get("syncedLyrics") or data.get("plainLyrics") or ""
            if body:
                body = "[ti:%s]\n[ar:%s]\n%s" % (track, artist, body)
            return json.dumps({"lyrics": body})
        except Exception as e:
            return json.dumps({"error": str(e)})

    def h_legacyIsrc(self, m, ctx, add, directory, isrc, path):
        directory, isrc, path = str(directory).strip(), str(isrc).strip().upper(), str(path).strip()
        if not directory or not isrc or (add and not path):
            return json.dumps({"error": "outputDir, isrc, and filePath are required" if add else "outputDir and isrc are required"})
        index = self.manager.isrc_index
        if add:
            index[isrc] = path
            self.manager.save_isrc_index()
            return json.dumps({"success": True})
        found = index.get(isrc, "")
        if found and not os.path.isfile(found):
            found = ""
        return json.dumps({"exists": bool(found), "filePath": found})

    # -- signed sessions and OAuth

    def h_sessionCall(self, m, ctx, method, arguments):
        args = json.loads(arguments or "[]")
        client = self.manager.sessions.client(m, self)
        try:
            ctx.check()
            if method == "status":
                value = client.status()
            elif method == "clear":
                client.clear()
                value = {"success": True}
            elif method == "completeGrant":
                client.complete_grant(args[0] if args and isinstance(args[0], str) else "", ctx)
                value = {"success": True}
            elif method == "signedFetch":
                if len(args) < 2:
                    raise HostThrow("method and path are required")
                headers = args[3] if len(args) > 3 and isinstance(args[3], dict) else {}
                value = client.signed_fetch(str(args[0]), str(args[1]), str(args[2] or "") if len(args) > 2 else "", headers, ctx)
            else:
                raise HostThrow("unknown signed session method")
        except Exception as e:
            if method == "status":
                value = {"authenticated": False, "error": str(e)}
            elif method == "signedFetch":
                value = {"ok": False, "error": str(e)}
            else:
                value = {"success": False, "error": str(e)}
        return json.dumps(value)

    def h_authCall(self, m, ctx, method, arguments, expires_is_float=False):
        args = json.loads(arguments or "[]")
        state = self.auth.setdefault(m.name, {})
        try:
            if method == "openAuthUrl":
                if not args:
                    return json.dumps({"success": False, "error": "auth URL is required"})
                state["pending_url"] = args[0]
                PLATFORM.open_url(args[0])
                return json.dumps({"success": True})
            if method == "getAuthCode":
                return json.dumps(state.get("code"))
            if method == "setAuthCode":
                value = args[0] if args else None
                if isinstance(value, str):
                    state["code"] = value
                elif isinstance(value, dict):
                    if value.get("code"):
                        state["code"] = value["code"]
                    for key in ("access_token", "refresh_token"):
                        if value.get(key):
                            state[key] = value[key]
                    if value.get("expires_in") is not None:
                        state["expires_at"] = time.time() + float(value["expires_in"])
                return json.dumps({"success": True})
            if method == "clearAuth":
                self.auth[m.name] = {}
                return json.dumps({"success": True})
            if method == "isAuthenticated":
                return json.dumps(bool(state.get("access_token")) and time.time() < state.get("expires_at", float("inf")))
            if method == "getTokens":
                return json.dumps({"access_token": state.get("access_token", ""), "refresh_token": state.get("refresh_token", ""),
                                   "expires_at": state.get("expires_at", 0), "is_expired": time.time() >= state.get("expires_at", float("inf"))})
            if method == "generatePKCE":
                size = int(args[0]) if args else 64
                verifier = _b64url(os.urandom(96))[:max(43, min(128, size))]
                challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
                state["pkce"] = {"verifier": verifier, "challenge": challenge, "method": "S256"}
                return json.dumps(state["pkce"])
            if method == "getPKCE":
                return json.dumps(state.get("pkce") or {})
            return json.dumps({"success": False, "error": "%s is not supported in Mornye Player" % method})
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)})
