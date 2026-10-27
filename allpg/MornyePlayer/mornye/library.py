# SPDX-License-Identifier: LGPL-3.0-only
# Mornye Player for exteraGram. Copyright 2026 BroNik (@BroZYTnikkkk).
# Based on Mornye by zarzet (https://github.com/mornyeapp/Mornye), LGPL-3.0-only.

"""Local music library, playback of local files, LRCLIB lyrics."""

import json
import math
import os
import random
import re
import requests
import shutil
import threading
import time
from client_utils import get_media_controller, run_on_queue
from file_utils import get_files_dir
from hook_utils import get_private_field, set_private_field
from ui.bulletin import BulletinHelper
from android.os import Build, Environment
from android_utils import run_on_ui_thread
from .logs import log
from java import jarray, jbyte, jclass
from java.lang import Boolean as JBoolean, String as JString
from org.telegram.messenger import ApplicationLoader, FileLoader, MessageObject, SharedConfig, UserConfig
from org.telegram.tgnet import TLRPC
from .common import (
    AUDIO_EXTS,
    USER_AGENT,
    _norm_key,
    _selected_account,
    mutagen,
)
from .automix import (
    message_file_path,
    message_meta,
    read_tags,
    track_key,
)


# ---------------------------------------------------------------------------
# Library, downloads, history and stats
# ---------------------------------------------------------------------------


class Library:
    def __init__(self, plugin):
        self.plugin = plugin
        self.dir = os.path.join(get_files_dir(), "mornye_player")
        os.makedirs(self.dir, exist_ok=True)
        self.tracks = []
        self.scanning = False
        self.lock = threading.Lock()
        self.stats = self._load("stats.json", {"tracks": {}, "artists": {}, "seconds": 0.0, "plays": 0, "days": {}})
        self.favorites = set(self._load("favorites.json", []))
        self.history = self._load("history.json", [])
        cache = self._load("library.json", {})
        self.tracks = cache.get("tracks", [])
        # Local MessageObjects get fresh negative ids. MediaController sorts a
        # playlist of negative ids from the largest down and plays towards
        # larger ids, so ids grow in listening order.
        self.id_seq = -2000000000 + int(time.time() * 10) % 500000000

    def _load(self, name, default):
        try:
            with open(os.path.join(self.dir, name), "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return default

    def _save(self, name, data):
        try:
            tmp = os.path.join(self.dir, name + ".tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
            os.replace(tmp, os.path.join(self.dir, name))
        except Exception as e:
            log("[Mornye] save %s: %s" % (name, e))

    # -- folders ----------------------------------------------------------

    def download_dir(self):
        custom = (self.plugin.get_setting("download_dir", "") or "").strip()
        if custom:
            path = custom
        else:
            path = os.path.join(str(Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_MUSIC).getAbsolutePath()), "Mornye")
        try:
            os.makedirs(path, exist_ok=True)
            probe = os.path.join(path, "mornye-write-check.mp3")
            open(probe, "w").close()
            os.remove(probe)
            return path
        except Exception:
            fallback = os.path.join(str(ApplicationLoader.applicationContext.getExternalFilesDir(None).getAbsolutePath()), "Music")
            os.makedirs(fallback, exist_ok=True)
            return fallback

    def folders(self):
        raw = self.plugin.get_setting("folders", "") or ""
        result = [p.strip() for p in re.split(r"[;\n,]", raw) if p.strip()]
        result.append(self.download_dir())
        try:
            # Earlier builds saved here when Music/Mornye was not writable.
            private = os.path.join(str(ApplicationLoader.applicationContext.getExternalFilesDir(None).getAbsolutePath()), "Music")
            if os.path.isdir(private):
                result.append(private)
        except Exception:
            pass
        return list(dict.fromkeys(result))

    # -- permissions ------------------------------------------------------

    def has_permission(self):
        ctx = ApplicationLoader.applicationContext
        perm = "android.permission.READ_MEDIA_AUDIO" if Build.VERSION.SDK_INT >= 33 else "android.permission.READ_EXTERNAL_STORAGE"
        return ctx.checkSelfPermission(perm) == 0, perm

    def request_permission(self, activity):
        ok, perm = self.has_permission()
        if ok or activity is None:
            return ok
        try:
            activity.requestPermissions(jarray(JString)([perm]), 4721)
        except Exception:
            pass
        return False

    # -- scanning ---------------------------------------------------------

    def scan(self, on_done=None):
        if self.scanning:
            return
        self.scanning = True

        def work():
            found = {}
            old = {t["path"]: t for t in self.tracks}
            try:
                if self.plugin.get_setting("use_mediastore", True) and self.has_permission()[0]:
                    self._scan_mediastore(found)
                for folder in self.folders():
                    self._scan_folder(folder, found, old)
            except Exception as e:
                log("[Mornye] scan: %s" % e)
            tracks = sorted(found.values(), key=lambda t: (_norm_key(t["artist"]), _norm_key(t["album"]), _norm_key(t["title"])))
            with self.lock:
                self.tracks = tracks
            self._save("library.json", {"tracks": tracks, "scanned": time.time()})
            self.scanning = False
            if on_done:
                run_on_ui_thread(lambda: on_done(len(tracks)))

        run_on_queue(work)

    def _scan_mediastore(self, found):
        ctx = ApplicationLoader.applicationContext
        MediaStore = jclass("android.provider.MediaStore$Audio$Media")
        extra = ["album_artist", "composer", "track", "year", "date_added", "genre"]
        base = ["_data", "title", "artist", "album", "duration", "date_modified"]
        cursor = None
        # genre and album_artist are only columns on newer Android; drop them one by one when refused
        for n in range(len(extra), -1, -1):
            try:
                cursor = ctx.getContentResolver().query(MediaStore.EXTERNAL_CONTENT_URI, jarray(JString)(base + extra[:n]),
                                                        "is_music != 0", None, "title")
                extra = extra[:n]
                break
            except Exception:
                continue
        if cursor is None:
            return
        try:
            while cursor.moveToNext():
                path = cursor.getString(0)
                if not path:
                    continue
                path = str(path)
                if not os.path.exists(path):
                    continue
                artist = cursor.getString(2)
                artist = str(artist) if artist and str(artist) != "<unknown>" else "Неизвестный исполнитель"
                found[path] = {
                    "path": path,
                    "title": str(cursor.getString(1) or os.path.basename(path)),
                    "artist": artist,
                    "album": str(cursor.getString(3) or ""),
                    "duration": int(cursor.getLong(4) // 1000),
                    "mtime": int(cursor.getLong(5)),
                }
                row = found[path]
                for i, col in enumerate(extra):
                    v = cursor.getString(6 + i)
                    if v and str(v) != "<unknown>":
                        row[col] = str(v)
        finally:
            cursor.close()

    def _scan_folder(self, folder, found, old):
        if not os.path.isdir(folder):
            return
        for root, dirs, files in os.walk(folder):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            for name in files:
                if not name.lower().endswith(AUDIO_EXTS):
                    continue
                path = os.path.join(root, name)
                if path in found:
                    continue
                try:
                    mtime = int(os.path.getmtime(path))
                except Exception:
                    continue
                cached = old.get(path)
                if cached and cached.get("mtime") == mtime and "tags_v" in cached:
                    found[path] = cached
                    continue
                tags = read_tags(path)
                found[path] = {
                    "path": path,
                    "title": tags["title"] or name,
                    "artist": tags["artist"] or "Неизвестный исполнитель",
                    "album": tags["album"] or "",
                    "duration": tags["duration"],
                    "mtime": mtime,
                    "tags_v": 2,
                }
                row = found[path]
                for src, col in (("albumartist", "album_artist"), ("composer", "composer"), ("genre", "genre"),
                                 ("tracknumber", "track"), ("date", "year")):
                    if tags.get(src):
                        row[col] = str(tags[src])

    # -- playback ---------------------------------------------------------

    def next_id(self):
        self.id_seq += 1
        return self.id_seq

    def build_message(self, track, account, msg_id=None):
        """A local MessageObject, the same shape Telegram's attach menu uses."""
        path = track["path"]
        msg = TLRPC.TL_message()
        msg.out = True
        msg.id = msg_id if msg_id is not None else self.next_id()
        user_id = UserConfig.getInstance(account).getClientUserId()
        msg.peer_id = TLRPC.TL_peerUser()
        msg.peer_id.user_id = user_id
        msg.from_id = TLRPC.TL_peerUser()
        msg.from_id.user_id = user_id
        msg.date = int(time.time())
        msg.message = ""
        msg.attachPath = path
        media = TLRPC.TL_messageMediaDocument()
        media.flags |= 3
        media.document = TLRPC.TL_document()
        msg.media = media
        msg.flags |= 768
        doc = media.document
        doc.id = 0
        doc.access_hash = 0
        doc.file_reference = jarray(jbyte)(0)
        doc.date = msg.date
        ext = os.path.splitext(path)[1][1:].lower() or "mp3"
        doc.mime_type = "audio/" + ("mpeg" if ext == "mp3" else ext)
        try:
            doc.size = os.path.getsize(path)
        except Exception:
            doc.size = 0
        doc.dc_id = 0
        attr = TLRPC.TL_documentAttributeAudio()
        attr.duration = float(track.get("duration") or 0) if _audio_duration_is_double() else int(track.get("duration") or 0)
        attr.title = track.get("title") or os.path.basename(path)
        attr.performer = track.get("artist") or ""
        attr.flags |= 3
        doc.attributes.add(attr)
        fname = TLRPC.TL_documentAttributeFilename()
        fname.file_name = os.path.basename(path)
        doc.attributes.add(fname)
        return MessageObject(account, msg, False, True)

    def play(self, tracks, index, account=None):
        if not tracks:
            return
        if account is None:
            account = _selected_account()
        if len(tracks) > 400:
            # Building thousands of MessageObjects on the UI thread stalls it.
            lo = max(0, index - 50)
            tracks = tracks[lo:lo + 400]
            index -= lo
        lst = jclass("java.util.ArrayList")()
        objects = []
        for t in tracks:
            mo = self.build_message(t, account)
            objects.append(mo)
            lst.add(mo)
        play_list(lst, objects[index])

    def play_next(self, track, account=None):
        mc = get_media_controller()
        if account is None:
            account = _selected_account()
        mo = self.build_message(track, account)
        if mc.getPlayingMessageObject() is None:
            self.play([track], 0, account)
            return
        insert_after_current(mo)

    def append(self, tracks, account=None):
        """Put tracks at the end of the current queue (or start playing them)."""
        mc = get_media_controller()
        if account is None:
            account = _selected_account()
        if mc.getPlayingMessageObject() is None:
            self.play(tracks, 0, account)
            return
        for t in tracks:
            append_to_queue(self.build_message(t, account))

    def set_favorite(self, paths, value):
        changed = False
        for path in paths:
            if (path in self.favorites) != bool(value):
                self.toggle_favorite(path)
                changed = True
        return changed

    def autoplay_extend(self, current_msg):
        """Personalized autoplay from the local library (simplified Mornye idea)."""
        with self.lock:
            tracks = list(self.tracks)
        if len(tracks) < 2:
            return
        title, artist = message_meta(current_msg)
        recent = {h.get("key") for h in self.history[:40]}
        artist_plays = self.stats.get("artists", {})
        track_stats = self.stats.get("tracks", {})
        cur_artist = _norm_key(artist)

        def score(t):
            k = track_key(t["title"], t["artist"])
            s = random.random()
            if _norm_key(t["artist"]) == cur_artist:
                s += 1.5
            s += math.log1p(artist_plays.get(_norm_key(t["artist"]), {}).get("plays", 0)) * 0.6
            ts = track_stats.get(k, {})
            s -= ts.get("skips", 0) * 0.8
            if k in recent:
                s -= 3
            if t["path"] in self.favorites:
                s += 0.7
            return s

        picks = sorted(tracks, key=score, reverse=True)[:5]
        account = current_msg.currentAccount
        for t in reversed(picks):
            insert_after_current(self.build_message(t, account))
        BulletinHelper.show_info("Mornye: автоплей добавил %d трек(ов)" % len(picks))

    # -- history and stats ------------------------------------------------

    def push_history(self, title, artist, path):
        entry = {"key": track_key(title, artist), "title": title, "artist": artist, "path": path, "at": int(time.time())}
        self.history = [entry] + [h for h in self.history if h.get("key") != entry["key"]][:199]
        self._save("history.json", self.history)

    def record_listen(self, title, artist, seconds, counted, skipped):
        if seconds <= 1:
            return
        s = self.stats
        s["seconds"] = s.get("seconds", 0.0) + seconds
        day = time.strftime("%Y-%m-%d")
        s.setdefault("days", {})[day] = s["days"].get(day, 0.0) + seconds
        k = track_key(title, artist)
        t = s.setdefault("tracks", {}).setdefault(k, {"title": title, "artist": artist, "plays": 0, "seconds": 0.0, "skips": 0})
        t["seconds"] += seconds
        a = s.setdefault("artists", {}).setdefault(_norm_key(artist), {"name": artist, "plays": 0, "seconds": 0.0})
        a["seconds"] += seconds
        if counted:
            t["plays"] += 1
            a["plays"] += 1
            s["plays"] = s.get("plays", 0) + 1
        if skipped:
            t["skips"] = t.get("skips", 0) + 1
        self._save("stats.json", s)

    def toggle_favorite(self, path):
        if path in self.favorites:
            self.favorites.discard(path)
        else:
            self.favorites.add(path)
        self._save("favorites.json", sorted(self.favorites))
        return path in self.favorites

    def export_m3u(self, tracks, name):
        folder = os.path.join(self.download_dir(), "Playlists")
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, re.sub(r"[\\/:*?\"<>|]", "_", name) + ".m3u8")
        with open(path, "w", encoding="utf-8") as f:
            f.write("#EXTM3U\n")
            for t in tracks:
                f.write("#EXTINF:%d,%s - %s\n%s\n" % (t.get("duration") or -1, t["artist"], t["title"], t["path"]))
        scan_file(path)
        return path

    # -- saving Telegram audio into the library ---------------------------

    def save_message(self, msg, on_done=None):
        title, artist = message_meta(msg)
        account = msg.currentAccount
        doc = msg.getDocument()
        if doc is None:
            return

        def work():
            path = message_file_path(msg)
            if not path:
                run_on_ui_thread(lambda: FileLoader.getInstance(account).loadFile(doc, msg, 2, 0))
                deadline = time.time() + 600
                while time.time() < deadline:
                    time.sleep(1.0)
                    path = message_file_path(msg)
                    if path and os.path.getsize(path) >= int(doc.size) > 0:
                        break
                    path = None
            if not path:
                run_on_ui_thread(lambda: BulletinHelper.show_error("Mornye: не удалось скачать «%s»" % title))
                return
            folder = self.download_dir()
            ext = os.path.splitext(path)[1] or ".mp3"
            safe = re.sub(r"[\\/:*?\"<>|]", "_", "%s - %s" % (artist, title)).strip()[:150]
            target = os.path.join(folder, safe + ext)
            try:
                if not os.path.exists(target):
                    shutil.copyfile(path, target)
                    self._tag_file(target, title, artist)
                scan_file(target)
                tags = read_tags(target)
                with self.lock:
                    self.tracks = [t for t in self.tracks if t["path"] != target] + [{
                        "path": target, "title": tags["title"] or title, "artist": tags["artist"] or artist,
                        "album": tags["album"] or "", "duration": tags["duration"], "mtime": int(os.path.getmtime(target)),
                    }]
                self._save("library.json", {"tracks": self.tracks, "scanned": time.time()})
                run_on_ui_thread(lambda: BulletinHelper.show_success("Mornye: «%s» сохранён в %s" % (title, folder)))
                if on_done:
                    run_on_ui_thread(lambda: on_done(target))
            except Exception as e:
                err = str(e)
                run_on_ui_thread(lambda: BulletinHelper.show_error("Mornye: ошибка сохранения: %s" % err))

        run_on_queue(work)

    def _tag_file(self, path, title, artist):
        if mutagen is None:
            return
        try:
            f = mutagen.File(path, easy=True)
            if f is None:
                return
            if f.tags is None:
                try:
                    f.add_tags()
                except Exception:
                    pass
            if not f.get("title"):
                f["title"] = title
            if not f.get("artist"):
                f["artist"] = artist
            f.save()
        except Exception:
            pass

    def tracks_by_path(self):
        with self.lock:
            return {t["path"]: t for t in self.tracks}

    def track_for_file(self, path):
        if not path or not os.path.isfile(path):
            return None
        tags = read_tags(path)
        return {"path": path, "title": tags["title"] or os.path.basename(path),
                "artist": tags["artist"] or "Неизвестный исполнитель", "album": tags["album"] or "",
                "duration": tags["duration"], "mtime": int(os.path.getmtime(path))}

    def add_file(self, path):
        track = self.track_for_file(path)
        if track is None:
            return None
        with self.lock:
            self.tracks = [t for t in self.tracks if t["path"] != path] + [track]
            tracks = list(self.tracks)
        self._save("library.json", {"tracks": tracks, "scanned": time.time()})
        return track


_DURATION_IS_DOUBLE = None


def _audio_duration_is_double():
    """Newer Telegram builds store audio duration as double, older as int."""
    global _DURATION_IS_DOUBLE
    if _DURATION_IS_DOUBLE is None:
        try:
            field = TLRPC.TL_documentAttributeAudio().getClass().getField("duration")
            _DURATION_IS_DOUBLE = str(field.getType().getName()) == "double"
        except Exception:
            _DURATION_IS_DOUBLE = False
    return _DURATION_IS_DOUBLE


def scan_file(path):
    try:
        MediaScannerConnection = jclass("android.media.MediaScannerConnection")
        MediaScannerConnection.scanFile(ApplicationLoader.applicationContext, jarray(JString)([path]), None, None)
    except Exception:
        pass


def play_list(java_list, start):
    mc = get_media_controller()
    try:
        mc.setPlaylist(java_list, start, 0, False, None)
        # The non-loading overload forces looping; respect the user's repeat mode.
        set_private_field(mc, "forceLoopCurrentPlaylist", JBoolean.FALSE)
    except Exception:
        mc.setPlaylist(java_list, start, 0)


def insert_after_current(mo):
    """Queue mo right after the current song in the list MediaController walks."""
    mc = get_media_controller()
    try:
        playlist = mc.getPlaylist()
        active = get_private_field(mc, "shuffledPlaylist") if SharedConfig.shuffleMusic else playlist
        num = mc.getPlayingMessageObjectNum()
        if active is None or num < 0 or num >= active.size():
            return
        if SharedConfig.playOrderReversed:
            active.add(num + 1, mo)
        else:
            # "Next" is index - 1: insert before the current item and shift it.
            active.add(num, mo)
            set_private_field(mc, "currentPlaylistNum", num + 1)
        if SharedConfig.shuffleMusic:
            playlist.add(mo)
        pmap = get_private_field(mc, "playlistMap")
        if pmap is not None:
            pmap.put(jclass("java.lang.Integer").valueOf(mo.getId()), mo)
    except Exception as e:
        log("[Mornye] queue insert: %s" % e)


def append_to_queue(mo):
    """Queue mo after the last song in the list MediaController walks."""
    mc = get_media_controller()
    try:
        playlist = mc.getPlaylist()
        active = get_private_field(mc, "shuffledPlaylist") if SharedConfig.shuffleMusic else playlist
        num = mc.getPlayingMessageObjectNum()
        if active is None or num < 0:
            return
        if SharedConfig.playOrderReversed:
            active.add(mo)
        else:
            # The list plays from the end towards index 0.
            active.add(0, mo)
            set_private_field(mc, "currentPlaylistNum", num + 1)
        if SharedConfig.shuffleMusic:
            playlist.add(mo)
        pmap = get_private_field(mc, "playlistMap")
        if pmap is not None:
            pmap.put(jclass("java.lang.Integer").valueOf(mo.getId()), mo)
    except Exception as e:
        log("[Mornye] queue append: %s" % e)


# ---------------------------------------------------------------------------
# LRCLIB lyrics (Mornye's fallback lyrics source)
# ---------------------------------------------------------------------------


def fetch_lyrics_raw(title, artist, duration):
    params = {"track_name": title, "artist_name": artist}
    if duration:
        params["duration"] = int(duration)
    headers = {"User-Agent": USER_AGENT}
    try:
        r = requests.get("https://lrclib.net/api/get", params=params, headers=headers, timeout=12)
        data = r.json() if r.status_code == 200 else None
        if not data:
            r = requests.get("https://lrclib.net/api/search", params={"q": "%s %s" % (artist, title)}, headers=headers, timeout=12)
            items = r.json() if r.status_code == 200 else []
            data = items[0] if items else None
        return data or None
    except Exception as e:
        log("[Mornye] lyrics: %s" % e)
        return None


def fetch_lyrics(title, artist, duration):
    data = fetch_lyrics_raw(title, artist, duration)
    if not data:
        return None
    try:
        if data.get("instrumental"):
            return {"synced": False, "lines": [(0, "♪ Инструментал ♪")]}
        synced = data.get("syncedLyrics")
        if synced:
            lines = []
            for raw in synced.splitlines():
                stamps = re.findall(r"\[(\d{1,3}):(\d{1,2})(?:[.:](\d{1,3}))?\]", raw)
                text = re.sub(r"\[[^\]]*\]", "", raw).strip()
                for mm, ss, frac in stamps:
                    ms = int(mm) * 60000 + int(ss) * 1000 + (int(frac.ljust(3, "0")[:3]) if frac else 0)
                    lines.append((ms, text))
            lines.sort()
            return {"synced": True, "lines": lines}
        plain = data.get("plainLyrics") or ""
        return {"synced": False, "lines": [(0, l) for l in plain.splitlines()]}
    except Exception as e:
        log("[Mornye] lyrics: %s" % e)
        return None
