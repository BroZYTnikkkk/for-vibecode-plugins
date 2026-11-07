# SPDX-License-Identifier: LGPL-3.0-only
# Mornye Player for exteraGram. Copyright 2026 BroNik (@BroZYTnikkkk).
# Based on Mornye by zarzet (https://github.com/mornyeapp/Mornye), LGPL-3.0-only.

"""Extension manager: registries, packages, settings, provider calls."""

import collections
import hashlib
import json
import os
import re
import requests
import secrets
import shutil
import threading
import time
from urllib.parse import urlsplit
from .logs import log
from .ext_runtime import (
    ExtError,
    ExtTimeout,
    HostApi,
    JsRuntime,
    MORNYE_COMPAT_VERSION,
    Manifest,
    OFFICIAL_REGISTRY,
    _EXT_ID_RE,
    _ci,
)
from .ext_sessions import SignedSessions


# -- extension manager (port of extensions/src/manager, repository, package) ----


def registry_urls(url):
    """GitHub repository links resolve to the raw registry.json, like Mornye."""
    url = (url or "").strip()
    if not url:
        raise ExtError("registry URL is empty")
    if "raw.githubusercontent.com" in url:
        return [url]
    for prefix in ("https://github.com/", "http://github.com/"):
        if url.startswith(prefix):
            parts = url[len(prefix):].split("/")
            if len(parts) < 2 or not parts[0] or not parts[1]:
                raise ExtError("invalid GitHub URL: expected github.com/<owner>/<repo>")
            repo = parts[1][:-4] if parts[1].endswith(".git") else parts[1]
            base = "https://raw.githubusercontent.com/%s/%s/" % (parts[0], repo)
            return [base + "main/registry.json", base + "master/registry.json"]
    return [url]


def _require_https(url, context):
    parts = urlsplit(url or "")
    if not parts.hostname:
        raise ExtError("%s URL is invalid: %s" % (context, url))
    if parts.scheme != "https":
        raise ExtError("%s URL must use https: %s" % (context, url))


def _version_key(version):
    out = []
    for part in re.split(r"[.+-]", str(version or "")):
        out.append((0, int(part), "") if part.isdigit() else (1, 0, part))
    return out


def _safe_extract(zip_path, target):
    """Inspect before extraction: no links, no escaping paths, bounded size."""
    import zipfile
    try:
        archive = zipfile.ZipFile(zip_path)
    except Exception:
        raise ExtError("cannot open extension file: the file may be corrupted or not a valid extension package")
    with archive:
        infos = archive.infolist()
        if len(infos) > 2048:
            raise ExtError("extension archive has too many entries")
        total = 0
        names = set()
        for info in infos:
            mode = (info.external_attr >> 16) & 0o170000
            name = info.filename.replace("\\", "/")
            clean = os.path.normpath(name).replace("\\", "/")
            if mode == 0o120000 or name.startswith("/") or clean.startswith("..") or ":" in name:
                raise ExtError("unsafe path in extension archive: %s" % name)
            if clean.lower() in names:
                raise ExtError("cannot open extension file: duplicate archive entries")
            names.add(clean.lower())
            if not info.is_dir():
                total += info.file_size
                if total > 256 << 20:
                    raise ExtError("extension archive exceeds the 256 MiB extracted size limit")
        if "manifest.json" not in names:
            raise ExtError("invalid extension package: root manifest.json not found")
        if "index.js" not in names:
            raise ExtError("invalid extension package: root index.js not found")
        manifest = Manifest(json.loads(archive.read([i for i in infos if os.path.normpath(i.filename) == "manifest.json"][0]).decode("utf-8")))
        manifest.validate()
        os.makedirs(target, exist_ok=True)
        for info in infos:
            clean = os.path.normpath(info.filename.replace("\\", "/"))
            dest = os.path.join(target, clean)
            if info.is_dir():
                os.makedirs(dest, exist_ok=True)
                continue
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with archive.open(info) as src, open(dest, "wb") as out:
                shutil.copyfileobj(src, out)
    return manifest


class ExtensionManager:
    def __init__(self, root):
        self.root = root
        self.pkgs = os.path.join(root, "pkgs")
        self.data = os.path.join(root, "data")
        for path in (self.pkgs, self.data):
            os.makedirs(path, exist_ok=True)
        self.lock = threading.RLock()
        self.state = self._load_json("state.json", {})
        self.state.setdefault("enabled", {})
        self.state.setdefault("settings", {})
        self.state.setdefault("errors", {})
        self.state.setdefault("priorities", {"download": [], "metadata": []})
        self.state.setdefault("fallback", None)
        self.state.setdefault("repos", [OFFICIAL_REGISTRY])
        self.isrc_index = self._load_json("isrc_index.json", {})
        self.manifests = {}
        self.logs = collections.deque(maxlen=400)
        self.sessions = SignedSessions(root)
        self.api = HostApi(self)
        self.runtime = JsRuntime(self)
        self.registry_cache = {}
        self.load_all()

    # -- persistence

    def _load_json(self, name, default):
        try:
            with open(os.path.join(self.root, name), "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return default

    def _save_json(self, name, data):
        path = os.path.join(self.root, name)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, path)

    def save_state(self):
        with self.lock:
            self._save_json("state.json", self.state)

    def save_isrc_index(self):
        with self.lock:
            self._save_json("isrc_index.json", self.isrc_index)

    # -- host-facing accessors

    def manifest(self, ext):
        return self.manifests.get(ext)

    def source_path(self, ext):
        if ext not in self.manifests:
            return None
        return os.path.join(self.pkgs, ext, "index.js")

    def data_dir(self, ext):
        path = os.path.join(self.data, ext)
        os.makedirs(path, exist_ok=True)
        return path

    def settings(self, ext):
        return dict(self.state["settings"].get(ext) or {})

    def runtime_settings(self, ext):
        return {k: v for k, v in self.settings(ext).items() if not str(k).startswith("_")}

    def record_logs(self, ext, entries):
        for entry in entries or []:
            try:
                level, values, count = (list(entry) + [None, None, 1])[:3]
                text = " ".join(v if isinstance(v, str) else json.dumps(v, ensure_ascii=False) for v in (values or []))
                self.logs.append((time.time(), str(level or "INFO"), ext, text[:2000], int(count or 1)))
                if str(level or "").upper() in ("WARN", "WARNING", "ERROR"):
                    log("[Mornye:%s] %s %s" % (ext, str(level).upper(), text[:600]))
            except Exception:
                pass

    def log(self, ext, level, text):
        self.record_logs(ext, [[level, [text], 1]])

    # -- installed extensions

    def load_all(self):
        found = {}
        for name in sorted(os.listdir(self.pkgs)):
            path = os.path.join(self.pkgs, name, "manifest.json")
            if not os.path.isfile(path):
                continue
            try:
                with open(path, "r", encoding="utf-8") as f:
                    manifest = Manifest(json.load(f))
                manifest.validate()
                if manifest.name != name:
                    raise ExtError("manifest name does not match its folder")
                found[name] = manifest
            except Exception as e:
                self.log(name, "ERROR", "load failed: %s" % e)
        self.manifests = found

    def installed(self):
        result = []
        for ext, m in sorted(self.manifests.items(), key=lambda kv: kv[1].display_name.lower()):
            result.append({"id": ext, "name": m.display_name, "version": m.version, "description": m.description,
                           "types": list(m.types), "enabled": self.is_enabled(ext), "error": self.state["errors"].get(ext, ""),
                           "icon": self.icon_path(ext)})
        return result

    def icon_path(self, ext):
        m = self.manifests.get(ext)
        icon = str(_ci(m.raw, "icon", "") or "") if m else ""
        for name in ([icon] if icon else []) + ["icon.png", "icon.jpg", "icon.webp"]:
            path = os.path.normpath(os.path.join(self.pkgs, ext, name))
            if path.startswith(os.path.join(self.pkgs, ext) + os.sep) and os.path.isfile(path):
                return path
        return ""

    def is_enabled(self, ext):
        return ext in self.manifests and bool(self.state["enabled"].get(ext, False))

    def set_enabled(self, ext, enabled):
        if ext not in self.manifests:
            raise ExtError("extension not found: %s" % ext)
        with self.lock:
            self.state["enabled"][ext] = bool(enabled)
            self.state["errors"].pop(ext, None)
            self.save_state()
        if not enabled:
            self.runtime.unload(ext)

    def update_settings(self, ext, values):
        with self.lock:
            self.state["settings"][ext] = dict(values)
            self.save_state()
        self.runtime.unload(ext)

    def provider_ids(self, kind):
        return [ext for ext, m in self.manifests.items() if m.has_type(kind) and self.is_enabled(ext)]

    # -- repositories and packages

    def fetch_registry(self, url):
        last = None
        for candidate in registry_urls(url):
            try:
                _require_https(candidate, "registry")
                r = requests.get(candidate, timeout=20, headers={"User-Agent": "Mornye/" + MORNYE_COMPAT_VERSION})
                if r.status_code == 404:
                    last = ExtError("registry not found: %s" % candidate)
                    continue
                r.raise_for_status()
                data = r.json()
                items = data.get("extensions") if isinstance(data, dict) else None
                if not isinstance(items, list):
                    raise ExtError("invalid registry: extensions list missing")
                result = []
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    ext = str(item.get("id") or item.get("name") or "").strip()
                    if not _EXT_ID_RE.match(ext):
                        continue
                    item = dict(item)
                    item["id"] = ext
                    installed = self.manifests.get(ext)
                    item["installed_version"] = installed.version if installed else ""
                    item["has_update"] = bool(installed) and _version_key(item.get("version")) > _version_key(installed.version)
                    result.append(item)
                self.registry_cache[url] = result
                return result
            except ExtError as e:
                last = e
            except Exception as e:
                last = ExtError("registry fetch failed: %s" % e)
        raise last or ExtError("registry fetch failed")

    def install_from_registry(self, item, on_progress=None):
        url = str(item.get("download_url") or "")
        _require_https(url, "download")
        expected = str(item.get("sha256") or "").strip().lower()
        tmp = os.path.join(self.root, "tmp-%s.sflx" % secrets.token_hex(6))
        try:
            digest = hashlib.sha256()
            with requests.get(url, stream=True, timeout=30, headers={"User-Agent": "Mornye/" + MORNYE_COMPAT_VERSION}) as r:
                r.raise_for_status()
                total = int(r.headers.get("Content-Length") or 0)
                done = 0
                with open(tmp, "wb") as f:
                    for chunk in r.iter_content(256 * 1024):
                        f.write(chunk)
                        digest.update(chunk)
                        done += len(chunk)
                        if done > 256 << 20:
                            raise ExtError("extension package is too large")
                        if on_progress and total:
                            on_progress(done / float(total))
            if expected and digest.hexdigest() != expected:
                raise ExtError("checksum mismatch: the downloaded package does not match the registry")
            return self.install_file(tmp, expect_id=item.get("id"))
        finally:
            try:
                os.remove(tmp)
            except OSError:
                pass

    def install_file(self, path, expect_id=None):
        stage = os.path.join(self.root, "stage-%s" % secrets.token_hex(6))
        try:
            manifest = _safe_extract(path, stage)
            ext = manifest.name
            if expect_id and ext != expect_id:
                raise ExtError("package id %s does not match registry id %s" % (ext, expect_id))
            old = self.manifests.get(ext)
            if old and _version_key(manifest.version) < _version_key(old.version):
                raise ExtError("cannot downgrade %s from %s to %s" % (ext, old.version, manifest.version))
            self.runtime.unload(ext)
            target = os.path.join(self.pkgs, ext)
            backup = target + ".old"
            with self.lock:
                if os.path.isdir(backup):
                    shutil.rmtree(backup, ignore_errors=True)
                if os.path.isdir(target):
                    os.replace(target, backup)
                os.replace(stage, target)
                shutil.rmtree(backup, ignore_errors=True)
                self.manifests[ext] = manifest
                if ext not in self.state["enabled"]:
                    self.state["enabled"][ext] = True
                    for kind, key in (("download_provider", "download"), ("metadata_provider", "metadata")):
                        if manifest.has_type(kind) and ext not in self.state["priorities"][key]:
                            self.state["priorities"][key].append(ext)
                self.state["errors"].pop(ext, None)
                self.save_state()
            return ext
        finally:
            shutil.rmtree(stage, ignore_errors=True)

    def remove(self, ext):
        if ext not in self.manifests:
            raise ExtError("extension not found: %s" % ext)
        try:
            self.runtime.call(ext, "main", {"op": "function", "m": "cleanup", "a": [], "optional": True}, 10)
        except Exception:
            pass
        self.runtime.unload(ext)
        with self.lock:
            self.manifests.pop(ext, None)
            shutil.rmtree(os.path.join(self.pkgs, ext), ignore_errors=True)
            shutil.rmtree(os.path.join(self.data, ext), ignore_errors=True)
            for key in ("enabled", "settings", "errors"):
                self.state[key].pop(ext, None)
            for key in ("download", "metadata"):
                self.state["priorities"][key] = [i for i in self.state["priorities"][key] if i != ext]
            if self.state.get("search_provider") == ext:
                self.state["search_provider"] = ""
            if self.state.get("default_service") == ext:
                self.state["default_service"] = ""
            self.save_state()

    # -- priorities and provider choice

    def priorities(self, kind):
        provider = "download_provider" if kind == "download" else "metadata_provider"
        enabled = self.provider_ids(provider)
        ordered = [i for i in self.state["priorities"].get(kind, []) if i in enabled]
        return ordered + sorted(i for i in enabled if i not in ordered)

    def set_priority(self, kind, ids):
        with self.lock:
            self.state["priorities"][kind] = list(dict.fromkeys(i for i in ids if i))
            self.save_state()

    def fallback_allowed(self, ext):
        allowed = self.state.get("fallback")
        return allowed is None or ext in allowed

    def search_provider(self):
        chosen = self.state.get("search_provider") or ""
        if chosen and self.is_enabled(chosen) and self.manifests[chosen].has_custom_search:
            return chosen
        candidates = [e for e in self.priorities("metadata") if self.manifests[e].has_custom_search]
        candidates += sorted(e for e, m in self.manifests.items() if self.is_enabled(e) and m.has_custom_search and e not in candidates)
        for ext in candidates:
            if _ci(self.manifests[ext].search_behavior, "primary", False):
                return ext
        return candidates[0] if candidates else ""

    def search_providers(self):
        return [e for e, m in sorted(self.manifests.items()) if self.is_enabled(e) and m.has_custom_search]

    def default_service(self):
        chosen = self.state.get("default_service") or ""
        if chosen and self.is_enabled(chosen) and self.manifests[chosen].has_type("download_provider"):
            return chosen
        ids = self.priorities("download")
        return ids[0] if ids else ""

    def find_url_handler(self, url):
        ranks = {e: i for i, e in enumerate(self.priorities("metadata"))}
        found = [e for e, m in self.manifests.items() if self.is_enabled(e) and m.matches_url(url)]
        found.sort(key=lambda e: (ranks.get(e, 1 << 30), e))
        return found[0] if found else ""

    # -- calls

    _REQUIREMENTS = {
        "getTrack": ("metadata_provider", "is not a metadata provider"),
        "getAlbum": ("metadata_provider", "is not a metadata provider"),
        "getPlaylist": ("metadata_provider", "is not a metadata provider"),
        "getArtist": ("metadata_provider", "is not a metadata provider"),
        "getConcert": ("metadata_provider", "is not a metadata provider"),
        "searchTracks": ("metadata_provider", "is not a metadata provider"),
        "enrichTrack": ("metadata_provider", "is not a metadata provider"),
        "checkAvailability": ("download_provider", "is not a download provider"),
        "fetchLyrics": ("lyrics_provider", "is not a lyrics provider"),
    }

    def _timeout(self, ext, ms):
        m = self.manifests.get(ext)
        limit = m.network_timeout if m else 30
        return max(float(ms) / 1000.0, float(limit or 0)) + 5

    def provider_call(self, ext, method, args, timeout_ms=30000, ctx=None, lane="main"):
        m = self.manifests.get(ext)
        if m is None:
            raise ExtError("extension not found: %s" % ext)
        need = self._REQUIREMENTS.get(method)
        if need and not m.has_type(need[0]):
            raise ExtError("extension '%s' %s" % (ext, need[1]))
        if method == "customSearch" and not m.has_custom_search:
            raise ExtError("extension '%s' does not support custom search" % ext)
        if method == "handleUrl" and not (m.url_handler and _ci(m.url_handler, "enabled", False) and _ci(m.url_handler, "patterns", [])):
            raise ExtError("extension '%s' does not support URL handling" % ext)
        if not self.is_enabled(ext):
            raise ExtError("extension '%s' is disabled" % ext)
        args = list(args)
        if method == "customSearch":
            while len(args) < 2:
                args.append(None)
            if args[1] is None:
                args[1] = {}
        if method == "checkAvailability":
            self.sessions.take_verification_url(ext)
        try:
            response = self.runtime.call(ext, lane, {"op": "provider", "m": method, "a": args}, self._timeout(ext, timeout_ms), ctx)
        except ExtTimeout:
            raise ExtError("%s timeout: extension took too long to respond" % method)
        except ExtError as e:
            if method == "checkAvailability" and self.sessions.take_verification_url(ext):
                raise ExtError("verification_required: extension '%s' needs signed-session verification" % ext)
            if str(e) == "download cancelled":
                raise
            raise ExtError("%s failed: %s" % (method, e))
        response = response or {}
        if isinstance(response, dict) and response.get("parseError"):
            raise ExtError("failed to parse %s result: %s" % (method, response["parseError"]))
        value = response.get("value") if isinstance(response, dict) else None
        if method == "checkAvailability" and (value is None or not (isinstance(value, dict) and value.get("available") is True)):
            if self.sessions.take_verification_url(ext):
                raise ExtError("verification_required: extension '%s' needs signed-session verification" % ext)
            if value is None:
                return {"available": False, "reason": "not implemented"}
        if value is None:
            if method == "customSearch":
                return []
            if method == "handleUrl":
                raise ExtError("handleUrl returned null - URL not recognized")
            raise ExtError("%s returned null" % method)
        self._stamp(method, value, ext, m)
        return value

    @staticmethod
    def _stamp(method, value, ext, m):
        def one(item):
            if isinstance(item, dict):
                item["provider_id"] = ext

        def tracks(items):
            for item in items if isinstance(items, list) else []:
                one(item)

        def album(item):
            one(item)
            if isinstance(item, dict):
                tracks(item.get("tracks"))

        if method == "getTrack":
            one(value)
        elif method in ("getAlbum", "getPlaylist"):
            album(value)
        elif method == "searchTracks":
            tracks(value.get("tracks") if isinstance(value, dict) else None)
        elif method == "customSearch":
            tracks(value)
        elif method == "getArtist":
            one(value)
            for release in value.get("releases") or []:
                album(release)
        elif method == "handleUrl":
            if isinstance(value.get("track"), dict):
                one(value["track"])
            tracks(value.get("tracks"))
            if isinstance(value.get("album"), dict):
                album(value["album"])
            artist = value.get("artist")
            if isinstance(artist, dict):
                one(artist)
                for key in ("albums", "releases"):
                    for item in artist.get(key) or []:
                        album(item)
                tracks(artist.get("top_tracks"))
        elif method == "fetchLyrics":
            value["source"] = "Extension: %s" % ext
            if not value.get("provider"):
                value["provider"] = m.display_name
            if isinstance(value.get("lines"), list) and not value["lines"]:
                plain = value.get("plainLyrics") or ""
                value["lines"] = None
                if plain and value.get("instrumental") is not True:
                    value["syncType"] = "UNSYNCED"
                    lines = [{"startTimeMs": 0, "words": line, "endTimeMs": 0} for line in plain.split("\n") if line.strip()]
                    value["lines"] = lines or None

    def action(self, ext, name, timeout=60):
        if not self.is_enabled(ext):
            raise ExtError("extension is disabled")
        result = self.runtime.call(ext, "main", {"op": "action", "m": name, "a": []}, timeout)
        if isinstance(result, str):
            try:
                result = json.loads(result)
            except Exception:
                pass
        return result

    def complete_grant(self, ext, grant):
        self.sessions.set_grant(ext, grant)
        result = self.action(ext, "completeGrant")
        if not (isinstance(result, dict) and result.get("success") is True):
            error = (result or {}).get("error") or (result or {}).get("message") if isinstance(result, dict) else result
            raise ExtError("Extension completeGrant failed for %s: %s" % (ext, error))

    def pending_verification(self, ext):
        pending = self.sessions.pending.get(ext)
        if pending and time.time() - pending["created"] < 180:
            return pending
        return None

    def preflight(self, ext, ctx, download_only=True):
        m = self.manifests.get(ext)
        if m is None or not self.is_enabled(ext) or not m.signed_session:
            return False
        if download_only and not m.has_type("download_provider"):
            return False
        if self.account_download_enabled(ext):
            return False
        client = self.sessions.client(m, self.api)
        return client.preflight(ctx)

    def account_download_enabled(self, ext):
        m = self.manifests.get(ext)
        mode = (m.capabilities or {}).get("accountDownloadMode") if m else None
        if not isinstance(mode, dict):
            return False
        setting = str(mode.get("setting") or "")
        return bool(setting) and str(self.settings(ext).get(setting, "")) == str(mode.get("value", ""))

    def download_call(self, ext, track_id, quality, output_path, ctx, prepared=None, resolution_ms=60000):
        m = self.manifests.get(ext)
        if m is None or not m.has_type("download_provider"):
            raise ExtError("extension '%s' is not a download provider" % ext)
        if not self.is_enabled(ext):
            raise ExtError("extension '%s' is disabled" % ext)
        allowance = 60000 if not resolution_ms else min(resolution_ms, 300000)
        options = {"resolutionTimeoutMs": allowance}
        if prepared:
            options["preparedContext"] = prepared
        self.sessions.take_verification_url(ext)
        ctx.resolution_deadline = time.time() + allowance / 1000.0
        try:
            response = self.runtime.call(ext, "dl", {"op": "download", "a": [track_id, quality, output_path, options]}, 30 * 60, ctx)
        except ExtTimeout:
            return {"success": False, "error_type": "timeout", "error_message": "download timeout: extension took too long to complete"}
        except ExtError as e:
            if str(e) == "download cancelled":
                raise
            return {"success": False, "error_type": "script_error", "error_message": str(e)}
        if isinstance(response, dict) and response.get("parseError"):
            return {"success": False, "error_type": "script_error", "error_message": response["parseError"]}
        value = response.get("value") if isinstance(response, dict) else None
        if value is None:
            return {"success": False, "error_type": "not_implemented", "error_message": "download returned null"}
        if value.get("success") is not True and self.sessions.take_verification_url(ext) and \
                str(value.get("error_type") or "").lower() != "verification_required":
            value["error_type"] = "verification_required"
            value["error_message"] = value.get("error_message") or "Verification required"
        return value

    # -- search helpers used by the UI

    def search(self, query, filter_id=None, provider=None):
        provider = provider or self.search_provider()
        if provider:
            items = self.provider_call(provider, "customSearch", [query, {"filter": filter_id} if filter_id else {}])
            return provider, items if isinstance(items, list) else []
        ids = self.priorities("metadata")
        for ext in ids:
            try:
                value = self.provider_call(ext, "searchTracks", [query, 20])
                return ext, value.get("tracks") or []
            except Exception as e:
                self.log(ext, "WARN", "search failed: %s" % e)
        raise ExtError("Нет расширений для поиска. Установите их в разделе «Расширения».")

    def search_metadata(self, query, limit=5):
        for ext in self.priorities("metadata"):
            try:
                value = self.provider_call(ext, "searchTracks", [query, limit], 30000)
                tracks = value.get("tracks") or []
                if tracks:
                    return tracks
            except Exception:
                continue
        return []

    def lyrics(self, track_name, artist, album="", duration_s=0):
        for ext, m in sorted(self.manifests.items()):
            if not (self.is_enabled(ext) and m.has_type("lyrics_provider")):
                continue
            try:
                value = self.provider_call(ext, "fetchLyrics", [track_name, artist, album, int(duration_s or 0)], 20000)
                if value and value.get("lines"):
                    return value
            except Exception as e:
                self.log(ext, "WARN", "lyrics failed: %s" % e)
        return None

    def close(self):
        self.runtime.close()
