# SPDX-License-Identifier: LGPL-3.0-only
# Sculpt Player for exteraGram. Copyright 2026 BroNik (@BroZYTnikkkk).
# Mornye Link comes from Mornye by zarzet (https://github.com/mornyeapp/Mornye), LGPL-3.0-only.

"""The phone's songs in Mornye on the computer, while Telegram is open: the list and covers go ahead, and a song's
file goes when the computer asks for it. The computer may ask to delete a file too: that is always refused here."""

import base64
import concurrent.futures
import hashlib
import json
import os
import re
import struct
import threading

from android_utils import run_on_ui_thread
from java import jclass

from .i18n import tr
from . import link
from .common import VERSION, _log
from .link_remote import Remote
from .link_stream import device_id, saved_server

SETTING = "link_share"
PAGE = 500
COVER_REQUEST = 4 * 1024 * 1024  # of base64 in one request
LYRICS_LIMIT = 128 * 1024
PUBLISH_DELAY = 2.0  # after the library changes
BACKOFF_MAX = 30
EXTENSIONS = frozenset(("flac", "mp3", "m4a", "mp4", "aac", "ogg", "oga", "opus", "wav", "aif", "aiff", "aifc", "wv", "ape",
                        "dsf", "dff", "mka", "wma", "webm"))
NAME = re.compile(r"^[0-9a-f]{32}\.[a-z0-9]{1,10}$")
EMPTY = "0" * 64  # the version of a list with nothing in it


def device_name():
    return "Sculpt Player (%s)" % jclass("android.os.Build").MODEL


def song_of(track):
    """(the song as the computer lists it, its name), or None for a file the computer would not take."""
    path = track["path"]
    suffix = os.path.splitext(path)[1][1:].lower()
    try:
        size = os.path.getsize(path)
    except OSError:
        return None
    if suffix not in EXTENSIONS or size <= 0:
        return None
    file_id = hashlib.sha256(("%s\n%d" % (path, size)).encode()).hexdigest()[:32]
    song = {"fileId": file_id, "suffix": suffix, "size": size, "artist": str(track.get("artist") or ""),
            "title": str(track.get("title") or os.path.splitext(os.path.basename(path))[0])}
    if track.get("album"):
        song["album"] = str(track["album"])
    if track.get("duration"):
        song["durationMs"] = int(track["duration"]) * 1000
    if track.get("added"):
        song["addedMs"] = int(track["added"]) * 1000
    return song, "%s.%s" % (file_id, suffix)


def plays_while_arriving(path, suffix):
    """An MP4 can be played from its start only when its index comes before the sound."""
    if suffix not in ("m4a", "mp4"):
        return True
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            at = 0
            for _ in range(64):
                if at + 8 > size:
                    return False
                f.seek(at)
                head = f.read(16)
                kind = head[4:8]
                if kind == b"moov":
                    return True
                if kind == b"mdat":
                    return False
                length = struct.unpack(">I", head[:4])[0]
                if length == 1 and len(head) == 16:
                    length = struct.unpack(">Q", head[8:16])[0]
                if length < 8:
                    return False
                at += length
    except OSError:
        pass
    return False


class Share:
    def __init__(self, plugin):
        self.plugin = plugin
        self.lock = threading.Lock()
        self.stopping = threading.Event()
        self.stopping.set()
        self.thread = None
        self.socket = None
        self.files = {}
        self.file_ids = {}
        self.paths = {}
        self.remote = Remote(plugin, self)
        self.sending = set()
        self.run_id = 0
        self.timer = None
        self.on_status = None
        self.desktop_listener = None
        self.status = tr("Песни телефона появятся в Mornye на компьютере, пока Telegram открыт.")
        self.uploads = concurrent.futures.ThreadPoolExecutor(max_workers=2, thread_name_prefix="sculpt-link-up")

    def path_of(self, file_id):
        return self.paths.get(file_id)

    def enabled(self):
        return bool(self.plugin.get_setting(SETTING, False))

    def say(self, text):
        self.status = text
        listener = self.on_status
        if listener is not None:
            run_on_ui_thread(lambda: listener(text))

    # -- on and off

    def start(self):
        with self.lock:
            if self.thread is not None and self.thread.is_alive() and not self.stopping.is_set():
                return
            self.stopping = threading.Event()
            self.thread = threading.Thread(target=self.run, args=(self.stopping,), name="sculpt-link-share", daemon=True)
            self.thread.start()

    def stop(self, clear=False):
        """clear: the computer forgets this phone's songs too. Nothing is deleted anywhere."""
        saved = saved_server(self.plugin)
        self.stopping.set()
        self.run_id += 1
        if self.timer is not None:
            self.timer.cancel()
        sock = self.socket
        if sock is not None:
            sock.close()
        if clear:
            self.say(tr("Выключено. Песни телефона пропадут из Mornye на компьютере."))
        if clear and saved is not None:
            def forget():
                try:
                    link.api_post(saved, "phone/catalog", {"version": EMPTY, "offset": 0, "total": 0, "songs": []})
                except Exception as e:
                    _log("link: clear %s" % type(e).__name__)

            threading.Thread(target=forget, name="sculpt-link-clear", daemon=True).start()

    def library_changed(self):
        """Several scans in a row send one list."""
        if self.socket is None or self.stopping.is_set():
            return
        if self.timer is not None:
            self.timer.cancel()
        self.timer = threading.Timer(PUBLISH_DELAY, self.publish_in_background)
        self.timer.daemon = True
        self.timer.start()

    # -- the connection

    def run(self, stopping):
        delay = 1
        while not stopping.is_set():
            saved = saved_server(self.plugin)
            if saved is None:
                self.say(tr("Сначала подключи компьютер."))
                return
            sock = None
            try:
                sock = link.Socket(saved)
                self.socket = sock
                sock.send({"type": "hello", "deviceId": device_id(self.plugin), "name": device_name(), "platform": "android",
                           "appVersion": VERSION, "protocol": 1})
                delay = 1
                self.say(tr("Подключаюсь к компьютеру…"))
                while not stopping.is_set():
                    message = sock.receive()
                    if message is None:
                        break
                    self.handle(saved, sock, message)
            except link.Forgotten as e:
                self.say(str(e))
                return
            except link.LinkError:
                pass
            except Exception as e:
                _log("link: share %s" % type(e).__name__)
            finally:
                if self.socket is sock:
                    self.socket = None
                if sock is not None:
                    sock.close()
            if stopping.is_set():
                return
            self.say(tr("Нет связи с компьютером. Пробую снова…"))
            stopping.wait(delay)
            delay = min(BACKOFF_MAX, delay * 2)

    def handle(self, saved, sock, message):
        kind, name = message.get("type"), message.get("name")
        if kind != "player.state":
            _log("link: got %s %s" % (kind, name or message.get("action") or ""))
        if kind == "player.state":
            listener = self.desktop_listener
            if listener is not None and isinstance(message.get("state"), dict):
                listener(message["state"])
        elif kind == "welcome":
            if self.enabled():  # the connection may be here only for the remote screen
                self.publish_in_background()
            self.remote.start_loop(sock, self.stopping)
        elif kind == "command":
            self.remote.command(message)
        elif kind == "files.request" and isinstance(name, str):
            with self.lock:
                if name in self.sending:
                    return
                self.sending.add(name)
            self.uploads.submit(self.send_file, saved, sock, name)
        elif kind == "files.lyrics.request" and isinstance(name, str):
            # the computer waits for it only 5 seconds: not behind the songs being sent
            threading.Thread(target=self.send_lyrics, args=(sock, message), name="sculpt-link-lyrics", daemon=True).start()
        elif kind == "files.delete.request":
            # the phone's files are never deleted from the computer
            sock.send({"type": "files.deleted", "requestId": message.get("requestId"), "name": name, "error": "unsupported"})

    def send_file(self, saved, sock, name):
        try:
            path = self.files.get(name) if NAME.match(name) else None
            if path is None:
                _log("link: not in the list (%d songs known): %s" % (len(self.files), name))
                self.say(tr("Компьютер попросил песню, которой нет в списке."))
                sock.send({"type": "files.failed", "name": name, "reason": "not_found"})
                return
            suffix = name.rsplit(".", 1)[1]
            sock.send({"type": "files.sending", "name": name, "file": name, "size": os.path.getsize(path),
                       "streamable": plays_while_arriving(path, suffix)})
            _log("link: sending %s" % name)
            link.upload(saved, name, path)
            _log("link: sent %s" % name)
        except Exception as e:
            _log("link: upload %s: %s" % (type(e).__name__, e))
            self.say(tr("Не удалось отправить песню: %s") % e)
            try:
                sock.send({"type": "files.failed", "name": name, "reason": "unavailable"})
            except Exception:
                pass
        finally:
            with self.lock:
                self.sending.discard(name)

    def send_lyrics(self, sock, message):
        name = message.get("name")
        reply = {"type": "files.lyrics", "requestId": message.get("requestId"), "name": name}
        try:
            from . import tags
            path = self.files.get(name)
            if path is None:
                reply["error"] = "not_found"
            else:
                text = tags.read(path).get("lyrics") or ""
                if len(text.encode()) > LYRICS_LIMIT:
                    reply["error"] = "too_large"
                else:
                    reply["lyrics"] = text
            sock.send(reply)
        except Exception as e:
            _log("link: lyrics %s" % type(e).__name__)

    # -- the list

    def publish_in_background(self):
        self.run_id += 1
        run = self.run_id
        threading.Thread(target=self.publish, args=(run,), name="sculpt-link-list", daemon=True).start()

    def loaded_tracks(self):
        """The library, read first if nothing has asked for it yet; None when it could not be read."""
        music = self.plugin.music
        if not music.loaded:
            done = threading.Event()
            run_on_ui_thread(lambda: music.scan(done.set))
            if not done.wait(120):
                return None
        return list(music.tracks) if music.loaded else None

    def cover_of(self, path, covers_by_id):
        """The cover's id for this song, remembering which file it is; None when the song has no picture."""
        covers = self.plugin.music.covers
        known, cover = covers.cached(path)
        if not known:
            covers.ensure(path)
            known, cover = covers.cached(path)
        if not cover:
            return None
        state = os.stat(cover)
        cover_id = hashlib.sha256(("%s\n%d\n%d" % (cover, state.st_size, int(state.st_mtime))).encode()).hexdigest()[:32]
        covers_by_id[cover_id] = cover
        return cover_id

    def publish(self, run):
        saved = saved_server(self.plugin)
        try:
            tracks = self.loaded_tracks()
            if tracks is None or saved is None or run != self.run_id:
                return
            made = [(song_of(track), track["path"]) for track in tracks]
            made = [(song, name, path) for (result, path) in made if result is not None for song, name in (result,)]
            # first of all: the computer may already be asking for a song from the list it keeps
            self.files = {name: path for _, name, path in made}
            self.file_ids = {path: name.split(".")[0] for _, name, path in made}
            self.paths = {file_id: path for path, file_id in self.file_ids.items()}
            songs, covers = [], {}
            for song, _, path in made:
                if run != self.run_id:
                    return
                cover_id = self.cover_of(path, covers)
                if cover_id is not None:
                    song["coverId"] = cover_id
                songs.append(song)
            lines = "\n".join(json.dumps(s, sort_keys=True, ensure_ascii=False) for s in songs)
            version = hashlib.sha256(lines.encode()).hexdigest() if songs else EMPTY
            held = link.api_get(saved, "phone/catalog")
            if not (isinstance(held, dict) and held.get("version") == version):
                self.send_covers(saved, covers, run)
                self.send_songs(saved, songs, version, run)
            if run == self.run_id:
                self.say(tr("Показано на компьютере: песен %d.") % len(songs))
        except link.LinkError as e:
            _log("link: list refused")
            self.say(str(e))
        except Exception as e:
            _log("link: list %s" % type(e).__name__)
            self.say(tr("Не получилось отправить список песен. Попробую при следующем подключении."))

    def send_covers(self, saved, covers, run):
        if not covers:
            return
        reply = link.api_get(saved, "phone/covers")
        held = set(reply.get("ids") or []) if isinstance(reply, dict) else set()
        batch, size = [], 0
        for cover_id, path in covers.items():
            if cover_id in held or run != self.run_id:
                continue
            with open(path, "rb") as f:
                data = base64.b64encode(f.read()).decode()
            if batch and size + len(data) > COVER_REQUEST:
                link.api_post(saved, "phone/covers", {"covers": batch})
                batch, size = [], 0
            batch.append({"id": cover_id, "ext": "jpg", "data": data})
            size += len(data)
        if batch and run == self.run_id:
            link.api_post(saved, "phone/covers", {"covers": batch})

    def send_songs(self, saved, songs, version, run):
        offset = 0
        while True:
            if run != self.run_id:
                return
            part = songs[offset:offset + PAGE]
            link.api_post(saved, "phone/catalog", {"version": version, "offset": offset, "total": len(songs), "songs": part})
            offset += len(part)
            if offset >= len(songs):
                return
