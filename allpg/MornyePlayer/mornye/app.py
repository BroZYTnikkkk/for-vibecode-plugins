# SPDX-License-Identifier: LGPL-3.0-only
# Mornye Player for exteraGram. Copyright 2026 BroNik (@BroZYTnikkkk).
# Based on Mornye by zarzet (https://github.com/mornyeapp/Mornye), LGPL-3.0-only.

"""Full-screen player: local HTTP server and the API the HTML app calls."""

import base64
import collections
import hashlib
import json
import os
import random
import re
import requests
import secrets
import threading
import time
from client_utils import get_media_controller
from hook_utils import get_private_field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit
from android.os import Looper
from android_utils import log, run_on_ui_thread
from java import jclass
from org.telegram.messenger import SharedConfig, UserConfig
from .common import (
    EFFECT_AUTO,
    EFFECT_LABELS,
    EQ_CENTERS,
    EQ_PRESETS,
    MIX_CROSSFADE,
    MIX_DURATION_LABELS,
    STRENGTH_LABELS,
    USER_AGENT,
    _selected_account,
    mutagen,
)
from .automix import (
    audio_quality_label,
    message_file_path,
    message_meta,
    track_key,
)
from .library import fetch_lyrics
from .ext_runtime import ExtError, OFFICIAL_REGISTRY, _ci
from .resources import APP_HTML


# ---------------------------------------------------------------------------
# Mornye app: the full-screen player UI (HTML in a WebView, API over localhost)
# ---------------------------------------------------------------------------


def ui_call(fn, timeout=5.0):
    """Run fn on the Android UI thread and wait for its result."""
    if Looper.myLooper() == Looper.getMainLooper():
        return fn()
    box = {}
    done = threading.Event()

    def run():
        try:
            box["v"] = fn()
        except Exception as e:
            box["x"] = e
        done.set()

    run_on_ui_thread(run)
    if not done.wait(timeout):
        raise ExtError("UI thread is busy")
    if "x" in box:
        raise box["x"]
    return box.get("v")


def embedded_cover(path):
    """Embedded artwork bytes of a local audio file, or None."""
    if mutagen is None or not path or not os.path.isfile(path):
        return None
    try:
        audio = mutagen.File(path)
        if audio is None:
            return None
        pictures = getattr(audio, "pictures", None)
        if pictures:
            return bytes(pictures[0].data)
        tags = audio.tags
        if tags is None:
            return None
        if hasattr(tags, "getall"):
            for frame in tags.getall("APIC"):
                return bytes(frame.data)
        covr = tags.get("covr") if hasattr(tags, "get") else None
        if covr:
            return bytes(covr[0])
        for key in ("metadata_block_picture", "METADATA_BLOCK_PICTURE"):
            if key in tags:
                from mutagen.flac import Picture
                return bytes(Picture(base64.b64decode(tags[key][0])).data)
    except Exception:
        pass
    try:
        MMR = jclass("android.media.MediaMetadataRetriever")
        r = MMR()
        r.setDataSource(path)
        art = r.getEmbeddedPicture()
        r.release()
        return bytes(art) if art is not None else None
    except Exception:
        return None


def _image_type(data):
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return "application/octet-stream"


class AppServer:
    def __init__(self, plugin):
        self.plugin = plugin
        self.api = AppApi(plugin)
        self.token = secrets.token_hex(16)
        self.prefix = "/app/%s/" % self.token
        self.server = None
        self.covers = collections.OrderedDict()
        self.cache_dir = os.path.join(plugin.library.dir, "img")
        os.makedirs(self.cache_dir, exist_ok=True)

    def url(self):
        if self.server is None:
            self.server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
            self.server.daemon_threads = True
            threading.Thread(target=self.server.serve_forever, name="mornye-app", daemon=True).start()
        return "http://127.0.0.1:%d%sindex.html" % (self.server.server_address[1], self.prefix)

    def close(self):
        if self.server is not None:
            threading.Thread(target=self.server.shutdown, daemon=True).start()
            self.server = None

    def cover(self, path):
        if path in self.covers:
            self.covers.move_to_end(path)
            return self.covers[path]
        data = embedded_cover(path)
        self.covers[path] = data
        while len(self.covers) > 120:
            self.covers.popitem(last=False)
        return data

    def remote_image(self, url):
        if not url.startswith("https://"):
            return None
        name = hashlib.sha1(url.encode("utf-8")).hexdigest()
        path = os.path.join(self.cache_dir, name)
        if os.path.isfile(path):
            with open(path, "rb") as f:
                return f.read()
        try:
            r = requests.get(url, timeout=15, headers={"User-Agent": USER_AGENT})
            if not r.ok or len(r.content) > 8 << 20:
                return None
            data = r.content
            if _image_type(data) == "application/octet-stream":
                return None
            with open(path, "wb") as f:
                f.write(data)
            return data
        except Exception:
            return None

    def _handler(self):
        app = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"
            disable_nagle_algorithm = True

            def log_message(self, *args):
                pass

            def _send(self, code, body, ctype="application/json; charset=utf-8", cache=False):
                data = body.encode("utf-8") if isinstance(body, str) else body
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "max-age=86400" if cache else "no-store")
                self._headers_buffer.append(b"\r\n")
                self._headers_buffer.append(data)
                self.flush_headers()

            def _route(self):
                parts = urlsplit(self.path)
                if not parts.path.startswith(app.prefix):
                    return None, {}
                return parts.path[len(app.prefix):], {k: v[0] for k, v in parse_qs(parts.query).items()}

            def do_GET(self):
                name, params = self._route()
                try:
                    if name == "index.html":
                        return self._send(200, APP_HTML, "text/html; charset=utf-8")
                    if name in ("cover", "img"):
                        data = app.cover(params.get("p", "")) if name == "cover" else app.remote_image(params.get("u", ""))
                        if data:
                            return self._send(200, data, _image_type(data), cache=True)
                except Exception as e:
                    log("[Mornye] app GET %s: %s" % (name, e))
                self._send(404, "{}")

            def do_POST(self):
                name, _ = self._route()
                size = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(size).decode("utf-8", "replace") if size else "{}"
                if name != "api":
                    return self._send(404, "{}")
                try:
                    req = json.loads(body)
                    fn = getattr(app.api, "a_" + str(req.get("fn")), None)
                    if fn is None:
                        raise ExtError("unknown call %s" % req.get("fn"))
                    reply = {"v": fn(*(req.get("a") or []))}
                except Exception as e:
                    reply = {"x": str(e)}
                self._send(200, json.dumps(reply, ensure_ascii=False, default=str))

        return Handler


def _track_out(t, favorites=()):
    return {"path": t["path"], "title": t.get("title") or "", "artist": t.get("artist") or "",
            "album": t.get("album") or "", "duration": int(t.get("duration") or 0), "fav": t["path"] in favorites}


class AppApi:
    """Everything the HTML app can ask for. Names start with a_."""

    def __init__(self, plugin):
        self.plugin = plugin

    @property
    def lib(self):
        return self.plugin.library

    @property
    def mgr(self):
        return self.plugin.extensions()

    # -- player

    def _msg_out(self, msg):
        title, artist = message_meta(msg)
        path = message_file_path(msg)
        known = self.lib.tracks_by_path().get(path) if path else None
        album = known.get("album") or "" if known else ""
        return {"title": title, "artist": artist, "album": album, "path": path or "", "id": msg.getId(),
                "duration": int(msg.getDuration() or 0), "fav": bool(path) and path in self.lib.favorites}

    def a_state(self):
        def read():
            mc = get_media_controller()
            msg = mc.getPlayingMessageObject()
            out = {"track": None, "playing": False, "position": 0.0, "duration": 0.0,
                   "shuffle": bool(SharedConfig.shuffleMusic), "repeat": int(SharedConfig.repeatMode),
                   "mix": self.plugin.get_setting("mix_mode", MIX_CROSSFADE),
                   "sleep": max(0, int(self.plugin.engine.sleep_at - time.time())) if self.plugin.engine.sleep_at else 0,
                   "downloads": sum(1 for i in self.plugin.downloads().snapshot() if i["status"] in ("queued", "running"))
                   if self.plugin._downloads is not None else 0,
                   "saved": sum(1 for i in self.plugin.downloads().snapshot() if i["status"] == "done")
                   if self.plugin._downloads is not None else 0}
            if msg is None:
                return out
            out["track"] = self._msg_out(msg)
            out["playing"] = not mc.isMessagePaused()
            player = self.plugin.engine.main_player()
            duration = float(msg.getDuration() or 0)
            position = float(msg.audioProgressSec or 0)
            try:
                if player is not None and player.getDuration() > 0:
                    duration = player.getDuration() / 1000.0
                    position = player.getCurrentPosition() / 1000.0
            except Exception:
                pass
            out["position"], out["duration"] = position, duration
            return out
        return ui_call(read)

    def a_control(self, op, value=None):
        def run():
            mc = get_media_controller()
            msg = mc.getPlayingMessageObject()
            if op == "toggle" and msg is not None:
                if mc.isMessagePaused():
                    mc.playMessage(msg)
                else:
                    mc.pauseMessage(msg)
            elif op == "next":
                mc.playNextMessage()
            elif op == "prev":
                mc.playPreviousMessage()
            elif op == "seek" and msg is not None:
                mc.seekToProgress(msg, float(max(0.0, min(1.0, value))))
            elif op == "shuffle":
                mc.setPlaybackOrderType(0 if SharedConfig.shuffleMusic else 2)
            elif op == "repeat":
                SharedConfig.setRepeatMode((int(SharedConfig.repeatMode) + 1) % 3)
            elif op == "stop":
                mc.cleanupPlayer(True, True)
            elif op == "mix":
                self.plugin.set_setting("mix_mode", int(value) % 3)
            return True
        return ui_call(run)

    def a_queue(self):
        def read():
            mc = get_media_controller()
            playlist = mc.getPlaylist()
            if playlist is None:
                return {"items": [], "current": -1}
            active = get_private_field(mc, "shuffledPlaylist") if SharedConfig.shuffleMusic else playlist
            active = active or playlist
            num = mc.getPlayingMessageObjectNum()
            items = [active.get(i) for i in range(min(active.size(), 600))]
            order = list(range(len(items)))
            if not SharedConfig.playOrderReversed:
                order.reverse()
            out = []
            current = -1
            for pos, i in enumerate(order):
                mo = items[i]
                entry = self._msg_out(mo)
                entry["i"] = i
                out.append(entry)
                if i == num:
                    current = pos
            return {"items": out, "current": current}
        return ui_call(read)

    def a_play_index(self, index):
        def run():
            mc = get_media_controller()
            playlist = mc.getPlaylist()
            active = get_private_field(mc, "shuffledPlaylist") if SharedConfig.shuffleMusic else playlist
            active = active or playlist
            try:
                method = mc.getClass().getDeclaredMethod("playMessageAtIndex", jclass("java.lang.Integer").TYPE)
                method.setAccessible(True)
                method.invoke(mc, jclass("java.lang.Integer").valueOf(int(index)))
            except Exception:
                mc.playMessage(active.get(int(index)))
            return True
        return ui_call(run)

    def a_seek_ms(self, ms):
        def run():
            mc = get_media_controller()
            msg = mc.getPlayingMessageObject()
            if msg is not None:
                try:
                    mc.seekToProgressMs(msg, int(ms))
                except Exception:
                    duration = float(msg.getDuration() or 0)
                    if duration > 0:
                        mc.seekToProgress(msg, float(ms) / 1000.0 / duration)
            return True
        return ui_call(run)

    # -- library

    def a_library(self):
        with self.lib.lock:
            tracks = list(self.lib.tracks)
        fav = self.lib.favorites
        return {"tracks": [_track_out(t, fav) for t in tracks], "scanning": self.lib.scanning,
                "permission": self.lib.has_permission()[0]}

    def a_rescan(self):
        done = threading.Event()
        self.lib.scan(lambda n: done.set())
        done.wait(120)
        return len(self.lib.tracks)

    def a_permission(self):
        act = self.plugin.ui.activity()
        return ui_call(lambda: self.lib.request_permission(act))

    def a_play_paths(self, paths, index=0, shuffle=False):
        by_path = self.lib.tracks_by_path()
        tracks = [by_path.get(p) or self.lib.track_for_file(p) for p in paths]
        tracks = [t for t in tracks if t]
        if not tracks:
            raise ExtError("нет треков")
        start = tracks[min(max(int(index), 0), len(tracks) - 1)]
        if shuffle:
            random.shuffle(tracks)
            start = tracks[0]
        ui_call(lambda: self.lib.play(tracks, tracks.index(start)), 15)
        return True

    def a_play_next(self, path):
        track = self.lib.tracks_by_path().get(path) or self.lib.track_for_file(path)
        ui_call(lambda: self.lib.play_next(track))
        return True

    def a_toggle_fav(self, path):
        return self.lib.toggle_favorite(path)

    def a_home(self):
        by_path = self.lib.tracks_by_path()
        fav = self.lib.favorites
        recent = [_track_out(by_path[h["path"]], fav) for h in self.lib.history if h.get("path") in by_path][:20]
        stats = self.lib.stats
        top = []
        for t in sorted(stats.get("tracks", {}).values(), key=lambda t: (t.get("plays", 0), t.get("seconds", 0)), reverse=True):
            match = next((x for x in by_path.values() if track_key(x["title"], x["artist"]) == track_key(t["title"], t["artist"])), None)
            if match:
                top.append(_track_out(match, fav))
            if len(top) >= 12:
                break
        artists = sorted(stats.get("artists", {}).values(), key=lambda a: (a.get("plays", 0), a.get("seconds", 0)), reverse=True)[:10]
        week = 0.0
        for i in range(7):
            week += stats.get("days", {}).get(time.strftime("%Y-%m-%d", time.localtime(time.time() - i * 86400)), 0.0)
        return {"recent": recent, "top": top, "artists": [{"name": a["name"], "plays": a.get("plays", 0)} for a in artists],
                "hours": stats.get("seconds", 0.0) / 3600.0, "week_hours": week / 3600.0, "plays": stats.get("plays", 0),
                "count": len(by_path), "favorites": len(fav)}

    def a_export(self, paths, name):
        by_path = self.lib.tracks_by_path()
        return self.lib.export_m3u([by_path[p] for p in paths if p in by_path], name)

    def a_send_saved(self, path):
        from client_utils import send_audio
        send_audio(UserConfig.getInstance(_selected_account()).getClientUserId(), path)
        return True

    def a_track_info(self, path):
        info = {"quality": audio_quality_label(path) or "", "path": path}
        try:
            info["size"] = os.path.getsize(path)
        except OSError:
            info["size"] = 0
        return info

    # -- extensions: search and catalogue

    def _providers(self):
        m = self.mgr
        out = []
        for ext in m.search_providers():
            man = m.manifest(ext)
            sb = man.search_behavior or {}
            out.append({"id": ext, "name": man.display_name, "placeholder": _ci(sb, "placeholder", "") or "",
                        "filters": [{"id": str(f.get("id")), "label": str(f.get("label") or f.get("id"))}
                                    for f in (_ci(sb, "filters", []) or []) if isinstance(f, dict)]})
        return out

    def a_providers(self):
        m = self.mgr
        return {"providers": self._providers(), "current": m.search_provider(), "installed": len(m.manifests),
                "download": m.default_service()}

    def a_search(self, query, filter_id=None, provider=None):
        query = (query or "").strip()
        if not query:
            return {"items": [], "provider": provider or ""}
        if re.match(r"^https?://", query):
            return self.a_url(query)
        if provider:
            self.mgr.state["search_provider"] = provider
            self.mgr.save_state()
        used, items = self.mgr.search(query, filter_id or None, provider or None)
        return {"items": items[:120], "provider": used}

    def a_url(self, url):
        m = self.mgr
        ext = m.find_url_handler(url)
        if not ext:
            raise ExtError("Нет расширения, которое понимает эту ссылку")
        value = m.provider_call(ext, "handleUrl", [url], 45000)
        return {"url": value, "provider": ext}

    def a_open(self, kind, ext, item_id):
        method = {"album": "getAlbum", "playlist": "getPlaylist", "artist": "getArtist"}.get(kind)
        if not method:
            raise ExtError("unknown item type %s" % kind)
        return self.mgr.provider_call(ext, method, [item_id], 45000)

    # -- downloads

    def a_download(self, tracks, play=False):
        queue = self.plugin.downloads()
        added = []
        for track in tracks or []:
            item = queue.add(track)
            item["play"] = bool(play) and len(tracks) == 1
            added.append(item["id"])
        return added

    def a_downloads(self):
        return self.plugin.downloads().snapshot()

    def a_dl_cancel(self, item_id):
        self.plugin.downloads().cancel(item_id)
        return True

    def a_dl_retry(self, item_id):
        self.plugin.downloads().retry(item_id)
        return True

    def a_dl_clear(self):
        self.plugin.downloads().clear_finished()
        return True

    def a_verify(self, ext):
        self.plugin.verify_extension(ext)
        return True

    # -- extensions: management

    def a_ext_installed(self):
        m = self.mgr
        out = m.installed()
        for item in out:
            item["download"] = item["id"] in m.provider_ids("download_provider")
        return {"items": out, "repos": list(m.state.get("repos") or []), "search_provider": m.search_provider(),
                "default_service": m.default_service(), "quality": m.state.get("quality") or "LOSSLESS",
                "auto_fallback": m.state.get("auto_fallback", True), "download_priority": m.priorities("download"),
                "metadata_priority": m.priorities("metadata")}

    def a_ext_registry(self, url=None):
        m = self.mgr
        urls = [url] if url else list(m.state.get("repos") or [OFFICIAL_REGISTRY])
        out, errors = [], []
        for u in urls:
            try:
                for item in m.fetch_registry(u):
                    item["repo"] = u
                    out.append(item)
            except Exception as e:
                errors.append("%s: %s" % (u, e))
        return {"items": out, "errors": errors}

    def a_ext_add_repo(self, url):
        m = self.mgr
        items = m.fetch_registry(url)
        with m.lock:
            if url not in m.state["repos"]:
                m.state["repos"].append(url)
            m.save_state()
        return len(items)

    def a_ext_remove_repo(self, url):
        m = self.mgr
        with m.lock:
            m.state["repos"] = [r for r in m.state["repos"] if r != url]
            m.save_state()
        return True

    def a_ext_install(self, item):
        return self.mgr.install_from_registry(item)

    def a_ext_install_all(self, items):
        done, errors = [], []
        for item in items:
            try:
                done.append(self.mgr.install_from_registry(item))
            except Exception as e:
                errors.append("%s: %s" % (item.get("id"), e))
        return {"installed": done, "errors": errors}

    def a_ext_remove(self, ext):
        self.mgr.remove(ext)
        return True

    def a_ext_enable(self, ext, enabled):
        self.mgr.set_enabled(ext, bool(enabled))
        return True

    def a_ext_settings(self, ext):
        m = self.mgr
        man = m.manifest(ext)
        if man is None:
            raise ExtError("extension not found")
        return {"id": ext, "name": man.display_name, "version": man.version, "description": man.description,
                "homepage": man.homepage, "settings": man.settings, "values": m.settings(ext),
                "quality": man.quality_options, "types": man.types,
                "logs": [{"t": e[0], "level": e[1], "text": e[3]} for e in list(m.logs) if e[2] == ext][-60:]}

    def a_ext_set_settings(self, ext, values):
        self.mgr.update_settings(ext, values or {})
        return True

    def a_ext_action(self, ext, action):
        return self.mgr.action(ext, action)

    def a_ext_prefs(self, values):
        m = self.mgr
        with m.lock:
            for key in ("search_provider", "default_service", "quality", "auto_fallback"):
                if key in values:
                    m.state[key] = values[key]
            m.save_state()
        return True

    def a_ext_priority(self, kind, ids):
        self.mgr.set_priority(kind, ids)
        return True

    # -- lyrics, sound, timers

    def a_lyrics(self):
        state = self.a_state()
        track = state.get("track")
        if not track:
            return None
        title, artist, duration = track["title"], track["artist"], track["duration"]
        try:
            value = self.mgr.lyrics(title, artist, track.get("album") or "", duration)
        except Exception:
            value = None
        if value and value.get("lines"):
            synced = value.get("syncType") != "UNSYNCED"
            lines = [[int(l.get("startTimeMs") or 0), l.get("words") or ""] for l in value["lines"]]
            return {"synced": synced, "lines": lines, "source": value.get("provider") or value.get("source") or ""}
        data = fetch_lyrics(title, artist, duration)
        if not data:
            return {"synced": False, "lines": [], "source": ""}
        return {"synced": data["synced"], "lines": [[ms, text] for ms, text in data["lines"]], "source": "lrclib.net"}

    def a_settings(self):
        p = self.plugin
        keys = {"mix_mode": MIX_CROSSFADE, "mix_duration": 0, "automix_effect": EFFECT_AUTO, "skip_fade": 2,
                "normalize": True, "eq_enabled": False, "eq_preset": 0, "bass_boost": 0, "virtualizer": 0,
                "loudness_boost": 0, "skip_silence": False, "autoplay": True}
        out = {k: p.get_setting(k, d) for k, d in keys.items()}
        out["eq_custom"] = p.custom_eq()
        out["eq_presets"] = [[name, list(g)] for name, g in EQ_PRESETS]
        out["eq_centers"] = EQ_CENTERS
        out["mix_labels"] = MIX_DURATION_LABELS
        out["effect_labels"] = EFFECT_LABELS
        out["strength_labels"] = STRENGTH_LABELS
        return out

    def a_set_setting(self, key, value):
        allowed = {"mix_mode", "mix_duration", "automix_effect", "skip_fade", "normalize", "eq_enabled", "eq_preset",
                   "bass_boost", "virtualizer", "loudness_boost", "skip_silence", "autoplay", "eq_custom"}
        if key not in allowed:
            raise ExtError("setting not allowed")
        if key == "eq_custom":
            value = json.dumps([float(v) for v in value])
        self.plugin.set_setting(key, value)
        ui_call(lambda: self.plugin.engine.reapply_fx())
        return True

    def a_sleep(self, minutes, end_of_track=False):
        self.plugin.engine.set_sleep(int(minutes or 0), bool(end_of_track))
        return True
