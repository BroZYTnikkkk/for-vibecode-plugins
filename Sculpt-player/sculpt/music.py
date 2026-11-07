# Sculpt Player for exteraGram. Copyright 2026 BroNik (@BroZYTnikkkk).

import collections
import hashlib
import json
import os
import re
import threading
import time

from android_utils import run_on_ui_thread
from client_utils import run_on_queue
from file_utils import get_files_dir
from java import jarray, jbyte, jclass, jint
from java.lang import Integer as JInteger, Long as JLong

from .common import ARTIST_SEP, COVER_SIZE, GENERIC_FOLDERS, HISTORY_MAX, LISTEN_SECONDS, LISTEN_TICK_MS, NO_TRACK_NUMBER, QUEUE_MAX, UNKNOWN_ARTIST, _ctx, _log, sculpt_method, MEDIA_CONTROLLER, QUEUE_HEAD, QUEUE_CHUNK

try:
    import mutagen
except Exception:
    mutagen = None

# 2: read with mutagen. Rows fixed by the retriever alone (1) still hold its "?" and are read again.
TAGS_FIXED = 2


# ---------------------------------------------------------------------------
# Media library: the phone's music, favorites, history
# ---------------------------------------------------------------------------


def local_path(message):
    """The file of a track started from the media library (negative id, attachPath set), else None."""
    try:
        if message is None or message.getId() >= 0:
            return None
        path = message.messageOwner.attachPath
        return str(path) if path else None
    except Exception:
        return None


def split_artists(text):
    out = []
    for part in ARTIST_SEP.split(text or ""):
        part = part.strip()
        if part and part.lower() not in (p.lower() for p in out):
            out.append(part)
    return out or [(text or "").strip()]


def sort_text(text):
    """Letters first and ё next to е, so a list reads in the order people expect."""
    return re.sub(r"^\W+", "", (text or "").casefold()).replace("ё", "е")


def first_letter(text):
    key = sort_text(text)
    return key[0].upper() if key and key[0].isalnum() else "#"


def songs_label(count):
    tail = count % 100
    if 11 <= tail <= 14:
        word = "песен"
    elif count % 10 == 1:
        word = "песня"
    elif 2 <= count % 10 <= 4:
        word = "песни"
    else:
        word = "песен"
    return "%d %s" % (count, word)


def format_time(seconds):
    seconds = max(0, int(seconds))
    if seconds >= 3600:
        return "%d:%02d:%02d" % (seconds // 3600, seconds // 60 % 60, seconds % 60)
    return "%d:%02d" % (seconds // 60, seconds % 60)


def track_number(track):
    try:
        return int(str(track.get("track", "")).split("/")[0])
    except ValueError:
        return NO_TRACK_NUMBER


class CoverCache:
    """Covers read from the files once and kept as small JPEGs, so a list never decodes a whole picture."""

    def __init__(self, directory):
        self.dir = os.path.join(directory, "covers")
        os.makedirs(self.dir, exist_ok=True)
        self.lock = threading.Lock()
        self.wanted = collections.deque()
        self.queued = set()
        self.working = False
        self.on_ready = None
        # called on the covers' thread for every cover read from a file, whoever asked for it
        self.on_extracted = None

    def _name(self, path):
        try:
            mtime = int(os.path.getmtime(path))
        except OSError:
            return None
        return os.path.join(self.dir, hashlib.sha1(("%s|%d" % (path, mtime)).encode("utf-8")).hexdigest())

    def cached(self, path):
        """(known, jpeg path or None): known is False while the file has not been read yet."""
        base = self._name(path)
        if base is None:
            return True, None
        if os.path.exists(base + ".jpg"):
            return True, base + ".jpg"
        if os.path.exists(base + ".none"):
            return True, None
        return False, None

    def get(self, path):
        known, jpg = self.cached(path)
        if not known:
            self.warm([path], first=True)
        return jpg

    def ensure(self, path):
        """Reads the cover now, on the calling thread (the plugins' queue, like the covers' own steps)."""
        try:
            if not self.cached(path)[0]:
                self._extract(path)
        except Exception as e:
            _log("cover %s: %s" % (os.path.basename(path), e))

    def warm(self, paths, first=False):
        with self.lock:
            if first:
                # what is on screen now goes ahead of everything, even if it already waits in the queue
                for path in paths:
                    if path in self.queued:
                        try:
                            self.wanted.remove(path)
                        except ValueError:
                            pass
                    self.queued.add(path)
                    self.wanted.appendleft(path)
            else:
                for path in paths:
                    if path not in self.queued:
                        self.queued.add(path)
                        self.wanted.append(path)
            if self.working or not self.wanted:
                return
            self.working = True
        run_on_queue(self._step)

    def _step(self):
        # One file at a time: other plugins share this queue.
        with self.lock:
            if not self.wanted:
                self.working = False
                return
            path = self.wanted.popleft()
        try:
            if not self.cached(path)[0]:
                self._extract(path)
                extracted = self.on_extracted
                if extracted is not None:
                    extracted(path)
            callback = self.on_ready
            if callback is not None:
                callback(path)
        except Exception as e:
            _log("cover %s: %s" % (os.path.basename(path), e))
        run_on_queue(self._step)

    def _extract(self, path):
        base = self._name(path)
        if base is None:
            return
        retriever = jclass("android.media.MediaMetadataRetriever")()
        data = None
        try:
            retriever.setDataSource(path)
            data = retriever.getEmbeddedPicture()
        except Exception:
            data = None
        finally:
            retriever.release()
        if data is None or not self._save_scaled(data, base + ".jpg"):
            open(base + ".none", "w").close()

    @staticmethod
    def _save_scaled(data, out):
        Factory = jclass("android.graphics.BitmapFactory")
        Options = jclass("android.graphics.BitmapFactory$Options")
        Bitmap = jclass("android.graphics.Bitmap")
        options = Options()
        options.inJustDecodeBounds = True
        Factory.decodeByteArray(data, 0, len(data), options)
        if options.outWidth <= 0 or options.outHeight <= 0:
            return False
        sample = 1
        while min(options.outWidth, options.outHeight) // (sample * 2) >= COVER_SIZE:
            sample *= 2
        options = Options()
        options.inSampleSize = sample
        bitmap = Factory.decodeByteArray(data, 0, len(data), options)
        if bitmap is None:
            return False
        width, height = bitmap.getWidth(), bitmap.getHeight()
        scale = float(COVER_SIZE) / max(1, min(width, height))
        if scale < 1.0:
            small = Bitmap.createScaledBitmap(bitmap, max(1, int(width * scale)), max(1, int(height * scale)), True)
            if small is not bitmap:
                bitmap.recycle()
            bitmap = small
        temp = "%s.%d.tmp" % (out, threading.get_ident())
        stream = jclass("java.io.FileOutputStream")(temp)
        try:
            bitmap.compress(jclass("android.graphics.Bitmap$CompressFormat").JPEG, 88, stream)
        finally:
            stream.close()
            bitmap.recycle()
        os.replace(temp, out)
        return True


class MusicData:
    """Everything the media library knows, independent of any open player."""

    def __init__(self, plugin):
        self.plugin = plugin
        self.dir = os.path.join(get_files_dir(), "sculpt_player")
        os.makedirs(self.dir, exist_ok=True)
        self.covers = CoverCache(self.dir)
        self.tracks = []
        self.by_path = {}
        self.loaded = False
        self.scanning = False
        self.grouped = None
        self.favorites = self._load("favorites.json", {})
        self.history = self._load("history.json", [])
        # MediaController sorts negative ids from the largest down and plays towards larger ids: ids grow in listening order.
        self.id_seq = -2000000000 + int(time.time() * 10) % 500000000
        # the queue started from the library: a new start makes the parts of the last one that are still coming stale
        self.queue_generation = 0
        self.queue_title = ""
        self.queue_total = 0
        self._import_mornye()

    def _load(self, name, default, directory=None):
        try:
            with open(os.path.join(directory or self.dir, name), "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return default

    def _save(self, name, data):
        try:
            temp = os.path.join(self.dir, name + ".tmp")
            with open(temp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
            os.replace(temp, os.path.join(self.dir, name))
        except Exception as e:
            _log("save %s: %s" % (name, e))

    def _import_mornye(self):
        """Once: what was already marked and heard in Mornye Player moves here. After that the two lists live apart."""
        if self.plugin.get_setting("mornye_imported", False):
            return
        self.plugin.set_setting("mornye_imported", True)
        folder = os.path.join(get_files_dir(), "mornye_player")
        now = int(time.time())
        changed = False
        for path in self._load("favorites.json", [], folder):
            if path and path not in self.favorites:
                self.favorites[path] = now
                changed = True
        if changed:
            self._save("favorites.json", self.favorites)
        known = {h["path"] for h in self.history}
        history = list(self.history)
        for entry in self._load("history.json", [], folder):
            path = entry.get("path") if isinstance(entry, dict) else None
            if path and path not in known:
                known.add(path)
                history.append({"path": path, "at": int(entry.get("at", 0))})
        if len(history) != len(self.history):
            self.history = history[:HISTORY_MAX]
            self._save("history.json", self.history)

    # -- permission ---------------------------------------------------------

    @staticmethod
    def permission():
        version = jclass("android.os.Build$VERSION").SDK_INT
        return "android.permission.READ_MEDIA_AUDIO" if version >= 33 else "android.permission.READ_EXTERNAL_STORAGE"

    def has_permission(self):
        return _ctx().checkSelfPermission(self.permission()) == 0

    # -- scanning -----------------------------------------------------------

    def scan(self):
        """The saved list first, so the screen fills at once, then a fresh look at the phone in the background."""
        if self.scanning:
            return
        self.scanning = True

        def work():
            try:
                # what is known already: tags fixed before are not read from the files again
                known = self.by_path
                if not self.loaded:
                    saved = self._load("library.json", [])
                    if saved:
                        known = {t["path"]: t for t in saved}
                        run_on_ui_thread(lambda: self._publish(saved))
                if not self.has_permission():
                    _log("scan: no permission to read music")
                    return
                started = time.monotonic()
                tracks = self._query(known)
                _log("scan: %d songs in %.0f ms, mangled tags: %s" % (
                    len(tracks), (time.monotonic() - started) * 1000, self.fixes or "none"))
                self._save("library.json", tracks)
                run_on_ui_thread(lambda: self._publish(tracks))
                self.covers.warm([t["path"] for t in tracks])
            except Exception as e:
                failure = e
                run_on_ui_thread(lambda: self.plugin.report("scan", failure))
            finally:
                self.scanning = False
                run_on_ui_thread(self._finished)

        run_on_queue(work)

    def _finished(self):
        self.loaded = True
        self._notify()

    def _publish(self, tracks):
        same = tracks == self.tracks
        self.loaded = True
        if same:
            return
        self.tracks = tracks
        self.by_path = {t["path"]: t for t in tracks}
        self.grouped = None
        self._notify()

    def _notify(self):
        player = self.plugin.player
        if player is not None and player.library is not None:
            player.library.data_changed()

    def _query(self, old):
        self.fixes = {}
        Media = jclass("android.provider.MediaStore$Audio$Media")
        strings = jclass("java.lang.String")
        base = ["_data", "title", "artist", "album", "duration", "date_modified"]
        extra = ["album_artist", "track", "date_added", "genre"]
        cursor = None
        # genre and album_artist are columns on newer Android only: drop them one by one when refused
        for count in range(len(extra), -1, -1):
            try:
                cursor = _ctx().getContentResolver().query(Media.EXTERNAL_CONTENT_URI, jarray(strings)(base + extra[:count]),
                                                           "is_music != 0", None, "title")
                extra = extra[:count]
                break
            except Exception:
                continue
        tracks = []
        if cursor is None:
            return tracks
        try:
            while cursor.moveToNext():
                path = cursor.getString(0)
                if not path:
                    continue
                path = str(path)
                if not os.path.exists(path):
                    continue
                artist = cursor.getString(2)
                artist = str(artist) if artist and str(artist) != "<unknown>" else UNKNOWN_ARTIST
                album = str(cursor.getString(3) or "")
                # Android names a file with no album tag after its folder
                if album.lower() in GENERIC_FOLDERS and album == os.path.basename(os.path.dirname(path)):
                    album = ""
                row = {"path": path, "title": str(cursor.getString(1) or os.path.basename(path)), "artist": artist,
                       "album": album, "duration": int(cursor.getLong(4) // 1000), "mtime": int(cursor.getLong(5))}
                for index, column in enumerate(extra):
                    value = cursor.getString(6 + index)
                    if value and str(value) != "<unknown>":
                        row[column] = str(value)
                row["added"] = int(row.pop("date_added", 0) or row["mtime"])
                if "?" in row["title"] + row["artist"] + row["album"]:
                    way = self._fix_mangled(row, old.get(path))
                    self.fixes[way] = self.fixes.get(way, 0) + 1
                tracks.append(row)
        finally:
            cursor.close()
        return tracks

    @staticmethod
    def _fix_mangled(row, cached):
        """MediaStore turns characters it cannot store into "?"; the file's own tags still have them.

        Android's own tag reader loses the same characters (letters outside the basic plane, such as styled
        bold ones), so mutagen reads the tags first and the retriever is only the fallback."""
        if cached and cached.get("mtime") == row["mtime"] and cached.get("tags_fixed") == TAGS_FIXED:
            for key in ("title", "artist", "album"):
                row[key] = cached.get(key) or row[key]
            row["tags_fixed"] = TAGS_FIXED
            return "saved"
        row["tags_fixed"] = TAGS_FIXED
        if mutagen is not None:
            try:
                tags = None
                try:
                    easy = mutagen.File(row["path"], easy=True)
                    tags = easy.tags if easy is not None else None
                except Exception:
                    pass
                if tags is None:
                    # an mp3 whose audio mutagen cannot make sense of still has readable ID3 tags
                    from mutagen.easyid3 import EasyID3
                    tags = EasyID3(row["path"])
                if tags is not None:
                    found = False
                    for key in ("title", "artist", "album"):
                        value = tags.get(key)
                        if value:
                            row[key] = str(value[0])
                            found = True
                    if found:
                        return "mutagen"
            except Exception as e:
                _log("tags %s: %s" % (os.path.basename(row["path"]), e))
        Retriever = jclass("android.media.MediaMetadataRetriever")
        retriever = Retriever()
        try:
            retriever.setDataSource(row["path"])
            for key, code in (("title", Retriever.METADATA_KEY_TITLE), ("artist", Retriever.METADATA_KEY_ARTIST),
                              ("album", Retriever.METADATA_KEY_ALBUM)):
                value = retriever.extractMetadata(code)
                if value:
                    row[key] = str(value)
        except Exception:
            pass
        finally:
            retriever.release()
        return "retriever" if mutagen is not None else "retriever, no mutagen"

    # -- lists --------------------------------------------------------------

    def groups(self):
        """Authors, albums and genres, computed once per scan."""
        if self.grouped is not None:
            return self.grouped
        artists, albums, genres = {}, {}, {}

        def add(table, key, name, track, **more):
            group = table.get(key)
            if group is None:
                group = table[key] = dict(name=name, tracks=[], **more)
            group["tracks"].append(track)

        for track in self.tracks:
            names = split_artists(track["artist"])
            for name in names:
                add(artists, sort_text(name), name, track)
            if track["album"]:
                owner = track.get("album_artist") or names[0]
                add(albums, (sort_text(track["album"]), sort_text(owner)), track["album"], track, artist=owner)
            for genre in re.split(r"\s*[;,/]\s*", track.get("genre", "")):
                if genre.strip():
                    add(genres, sort_text(genre), genre.strip(), track)

        def ordered(table):
            return sorted(table.values(), key=lambda g: sort_text(g["name"]))

        self.grouped = {"artists": ordered(artists), "albums": ordered(albums), "genres": ordered(genres)}
        return self.grouped

    @staticmethod
    def artist_albums(tracks):
        table = {}
        for track in tracks:
            if track["album"]:
                owner = track.get("album_artist") or split_artists(track["artist"])[0]
                group = table.setdefault(sort_text(track["album"]), {"name": track["album"], "artist": owner, "tracks": []})
                group["tracks"].append(track)
        return sorted(table.values(), key=lambda g: sort_text(g["name"]))

    def recently_added(self):
        return sorted(self.tracks, key=lambda t: -t.get("added", 0))

    def history_tracks(self):
        found = (self.by_path.get(h["path"]) for h in self.history)
        return [t for t in found if t is not None]

    def favorite_tracks(self):
        found = (self.by_path.get(p) for p in self.favorites)
        return [t for t in found if t is not None]

    def is_favorite(self, path):
        return path in self.favorites

    def toggle_favorite(self, path):
        if path in self.favorites:
            del self.favorites[path]
        else:
            self.favorites[path] = int(time.time())
        data = dict(self.favorites)
        run_on_queue(lambda: self._save("favorites.json", data))
        return path in self.favorites

    def add_history(self, path):
        entry = {"path": path, "at": int(time.time())}
        self.history = [entry] + [h for h in self.history if h["path"] != path][:HISTORY_MAX - 1]
        data = list(self.history)
        run_on_queue(lambda: self._save("history.json", data))
        self._notify()

    # -- playback -----------------------------------------------------------

    def java_queue(self, tracks):
        """MessageObjects for the tracks, built by sculpt.Queue in one call; None when the DEX is not there."""
        builder = sculpt_method("sculpt.Queue", "build")
        if builder is None:
            return None
        UserConfig = jclass("org.telegram.messenger.UserConfig")
        account = UserConfig.selectedAccount
        user_id = UserConfig.getInstance(account).getClientUserId()
        first = self.id_seq + 1
        self.id_seq += len(tracks)
        strings = jarray(jclass("java.lang.String"))
        # Method.invoke boxes plain Python ints as Long: every int parameter gets its own Integer
        return builder.invoke(None, JInteger(account), JLong(user_id), JInteger(first), JInteger(int(time.time())),
                              strings([t["path"] for t in tracks]), strings([t.get("title") or "" for t in tracks]),
                              strings([t.get("artist") or "" for t in tracks]), jarray(jint)([int(t.get("duration") or 0) for t in tracks]))

    def message_for(self, track):
        """A local MessageObject, the same shape Telegram's attach menu uses."""
        built = self.java_queue([track])
        if built is not None:
            return built.get(0)
        UserConfig = jclass("org.telegram.messenger.UserConfig")
        account = UserConfig.selectedAccount
        TL = "org.telegram.tgnet.TLRPC$"
        path = track["path"]
        message = jclass(TL + "TL_message")()
        self.id_seq += 1
        message.id = self.id_seq
        message.out = True
        user_id = UserConfig.getInstance(account).getClientUserId()
        message.peer_id = jclass(TL + "TL_peerUser")()
        message.peer_id.user_id = user_id
        message.from_id = jclass(TL + "TL_peerUser")()
        message.from_id.user_id = user_id
        message.date = int(time.time())
        message.message = ""
        message.attachPath = path
        media = jclass(TL + "TL_messageMediaDocument")()
        media.flags |= 3
        media.document = jclass(TL + "TL_document")()
        message.media = media
        message.flags |= 768
        document = media.document
        document.id = 0
        document.access_hash = 0
        document.file_reference = jarray(jbyte)(0)
        document.date = message.date
        extension = os.path.splitext(path)[1][1:].lower() or "mp3"
        document.mime_type = "audio/" + ("mpeg" if extension == "mp3" else extension)
        try:
            document.size = os.path.getsize(path)
        except OSError:
            document.size = 0
        document.dc_id = 0
        audio = jclass(TL + "TL_documentAttributeAudio")()
        is_double = str(audio.getClass().getField("duration").getType().getName()) == "double"
        audio.duration = float(track.get("duration") or 0) if is_double else int(track.get("duration") or 0)
        audio.title = track.get("title") or os.path.basename(path)
        audio.performer = track.get("artist") or ""
        audio.flags |= 3
        document.attributes.add(audio)
        name = jclass(TL + "TL_documentAttributeFilename")()
        name.file_name = os.path.basename(path)
        document.attributes.add(name)
        return jclass("org.telegram.messenger.MessageObject")(account, message, False, True)

    def _messages(self, tracks):
        """(ArrayList of MessageObjects, "java" or "python")."""
        items = self.java_queue(tracks)
        if items is not None:
            return items, "java"
        items = jclass("java.util.ArrayList")()
        for track in tracks:
            items.add(self.message_for(track))
        return items, "python"

    def play(self, tracks, index, title="", progress=0.0):
        """The list becomes the queue, starting from the song that was tapped, `progress` (0..1) into it.

        The first songs start the music at once; the rest is built in parts and joins the queue behind them.
        """
        if not tracks:
            return
        queues = getattr(self.plugin, "queues", None)
        if queues is not None:
            queues.library_started(title, tracks, index, progress)
        queue = (tracks[index:] + tracks[:index])[:QUEUE_MAX]
        self.covers.warm([t["path"] for t in queue[:8]], first=True)
        self.queue_generation += 1
        generation = self.queue_generation
        tapped = time.monotonic()

        def head():
            try:
                started = time.monotonic()
                # the covers' worker may be busy with the whole library: the player asks for this cover at once,
                # and does not ask again for a file that is already on the phone
                self.covers.ensure(queue[0]["path"])
                items, way = self._messages(queue[:QUEUE_HEAD])
                first = items.get(0)
                timing = {"songs": items.size(), "way": way, "waited": started - tapped, "built": time.monotonic() - started}
                run_on_ui_thread(lambda: self._start(generation, items, first, title, len(queue), timing, progress))
                if len(queue) > QUEUE_HEAD:
                    run_on_queue(lambda: self._build_rest(generation, queue, QUEUE_HEAD, first.getId()))
            except Exception as e:
                failure = e
                run_on_ui_thread(lambda: self.plugin.report("play", failure))

        run_on_queue(head)

    def _start(self, generation, items, first, title, total, timing, progress=0.0):
        if generation != self.queue_generation:
            return
        queues = getattr(self.plugin, "queues", None)
        try:
            started = time.monotonic()
            # set before the playlist: starting it redraws the player's header, which reads these
            self.queue_title = title
            self.queue_total = total
            if progress > 0.0:
                # MediaController seeks there itself once the file is open
                first.forceSeekTo = float(progress)
            controller = jclass(MEDIA_CONTROLLER).getInstance()
            if queues is not None:
                queues.starting = True
            try:
                controller.setPlaylist(items, first, 0, False, None)
            finally:
                if queues is not None:
                    queues.starting = False
            # This overload forces looping; the repeat button stays in charge.
            self.plugin.media_fields.field("forceLoopCurrentPlaylist").setBoolean(controller, False)
            _log("queue: %d of %d songs via %s, waited %.0f ms, built %.0f ms, setPlaylist %.0f ms" % (
                timing["songs"], total, timing["way"], timing["waited"] * 1000, timing["built"] * 1000,
                (time.monotonic() - started) * 1000))
        except Exception as e:
            self.plugin.report("play", e)

    def _build_rest(self, generation, queue, offset, first_id):
        """One part of the rest of the queue per step: other work on this thread gets its turn in between."""
        if generation != self.queue_generation:
            return
        try:
            items, _ = self._messages(queue[offset:offset + QUEUE_CHUNK])
            run_on_ui_thread(lambda: self._append(generation, items, first_id))
            if offset + QUEUE_CHUNK < len(queue):
                run_on_queue(lambda: self._build_rest(generation, queue, offset + QUEUE_CHUNK, first_id))
        except Exception as e:
            _log("queue part %d failed to build: %s" % (offset, e))
            failure = e
            run_on_ui_thread(lambda: self.plugin.report("queue", failure))

    def _append(self, generation, items, first_id):
        """Songs that come after everything already queued, in the order the list had them.

        MediaController keeps a library queue sorted by id from the largest down and walks it towards index 0,
        so later songs (larger ids) go in front and the current position moves by as many.
        """
        if generation != self.queue_generation:
            _log("queue part dropped: a newer queue started")
            return
        try:
            controller = jclass(MEDIA_CONTROLLER).getInstance()
            table = self.plugin.media_fields.get(controller, "playlistMap")
            if table is None or not table.containsKey(JInteger(first_id)):
                # the queue was replaced from somewhere else in the meantime
                _log("queue part dropped: song %d is no longer queued (map %s)" % (
                    first_id, "missing" if table is None else table.size()))
                return
            config, playlist, active = self._active_list(controller)
            Collections = jclass("java.util.Collections")
            newest_first = jclass("java.util.ArrayList")(items)
            Collections.reverse(newest_first)
            count = items.size()
            number = controller.getPlayingMessageObjectNum()
            if config.shuffleMusic:
                mixed = jclass("java.util.ArrayList")(items)
                Collections.shuffle(mixed)
                playlist.addAll(0, newest_first)
                active.addAll(0, mixed)
                self.plugin.media_fields.set_int(controller, "currentPlaylistNum", number + count)
            elif config.playOrderReversed:
                playlist.addAll(items)
            else:
                playlist.addAll(0, newest_first)
                self.plugin.media_fields.set_int(controller, "currentPlaylistNum", number + count)
            for i in range(count):
                message = items.get(i)
                table.put(JInteger(message.getId()), message)
            _log("queue part: +%d songs, %d queued" % (count, playlist.size()))
            player = self.plugin.player
            if player is not None and player.queue_visible():
                player.queue_screen.refresh_soon()
        except Exception as e:
            _log("queue part failed: %s" % e)
            self.plugin.report("queue", e)

    def _active_list(self, controller):
        config = jclass("org.telegram.messenger.SharedConfig")
        playlist = controller.getPlaylist()
        active = self.plugin.media_fields.get(controller, "shuffledPlaylist") if config.shuffleMusic else playlist
        return config, playlist, active

    def _remember(self, controller, config, playlist, message):
        if config.shuffleMusic:
            playlist.add(message)
        table = self.plugin.media_fields.get(controller, "playlistMap")
        if table is not None:
            table.put(JInteger(message.getId()), message)

    def play_next(self, track):
        controller = jclass("org.telegram.messenger.MediaController").getInstance()
        if controller.getPlayingMessageObject() is None:
            self.play([track], 0)
            return
        message = self.message_for(track)
        config, playlist, active = self._active_list(controller)
        number = controller.getPlayingMessageObjectNum()
        if active is None or number < 0 or number >= active.size():
            return
        if config.playOrderReversed:
            active.add(number + 1, message)
        else:
            # the next song is at index - 1: the new one goes before the current, which shifts by one
            active.add(number, message)
            self.plugin.media_fields.set_int(controller, "currentPlaylistNum", number + 1)
        self._remember(controller, config, playlist, message)

    def play_last(self, track):
        controller = jclass("org.telegram.messenger.MediaController").getInstance()
        if controller.getPlayingMessageObject() is None:
            self.play([track], 0)
            return
        message = self.message_for(track)
        config, playlist, active = self._active_list(controller)
        number = controller.getPlayingMessageObjectNum()
        if active is None or number < 0:
            return
        if config.playOrderReversed:
            active.add(message)
        else:
            # the list plays from its end towards index 0
            active.add(0, message)
            self.plugin.media_fields.set_int(controller, "currentPlaylistNum", number + 1)
        self._remember(controller, config, playlist, message)


class ListenTimer:
    """Counts what is really heard: a song joins the history after 30 seconds, or half of a shorter one."""

    def __init__(self, plugin):
        self.plugin = plugin
        self.running = False
        self.stopped = False
        self.path = None
        self.listened = 0.0
        self.counted = False
        self.last = 0.0

    def kick(self):
        if self.running or self.stopped:
            return
        self.running = True
        self.last = time.monotonic()
        run_on_ui_thread(self.tick, LISTEN_TICK_MS)

    def tick(self):
        try:
            controller = jclass("org.telegram.messenger.MediaController").getInstance()
            message = controller.getPlayingMessageObject()
            if self.stopped or message is None or controller.isMessagePaused():
                self.running = False
                return
            now = time.monotonic()
            path = local_path(message)
            if path != self.path:
                self.path = path
                self.listened = 0.0
                self.counted = False
            else:
                self.listened += min(now - self.last, LISTEN_TICK_MS / 1000.0 + 1.0)
            self.last = now
            if path is not None and not self.counted:
                duration = float(message.getDuration() or 0.0)
                if self.listened >= min(LISTEN_SECONDS, duration / 2.0 if duration > 0 else LISTEN_SECONDS):
                    self.counted = True
                    self.plugin.music.add_history(path)
            run_on_ui_thread(self.tick, LISTEN_TICK_MS)
        except Exception as e:
            self.running = False
            self.plugin.report("listen", e)
