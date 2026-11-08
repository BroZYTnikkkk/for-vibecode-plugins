# SPDX-License-Identifier: LGPL-3.0-only
# Sculpt Player for exteraGram. Copyright 2026 BroNik (@BroZYTnikkkk).
# Based on Mornye Player's tags.py; Mornye by zarzet (https://github.com/mornyeapp/Mornye), LGPL-3.0-only.

"""A song's tags for the editor: read them, write them with a cover, ask Android when the file is not ours."""

import os
import shutil

from java import jarray, jbyte, jclass

from .common import _ctx, _log

try:
    import mutagen
except Exception:
    mutagen = None

MAIN_FIELDS = (("title", "Название"), ("artist", "Исполнитель"), ("album", "Альбом"), ("date", "Год"), ("genre", "Жанр"))
ADVANCED_FIELDS = (("albumartist", "Исполнитель альбома"), ("tracknumber", "Номер дорожки"), ("discnumber", "Номер диска"),
                   ("isrc", "ISRC"), ("composer", "Композитор"), ("lyricist", "Автор слов"), ("organization", "Лейбл"),
                   ("copyright", "Копирайт"), ("bpm", "BPM"), ("comment", "Комментарий"))
FIELDS = MAIN_FIELDS + ADVANCED_FIELDS + (("lyrics", "Текст песни"),)
MULTILINE = ("comment", "lyrics")


def _register_keys():
    """mutagen's easy tags have no comment or lyrics for MP3, and no lyrics or composer for M4A: they are added
    here, each in the frame or atom players read."""
    try:
        from mutagen.easyid3 import EasyID3
        from mutagen.id3 import COMM, USLT

        def frame_get(kind):
            def get(id3, key):
                return [str(frame) for frame in id3.getall(kind)][:1]
            return get

        def frame_delete(kind):
            def delete(id3, key):
                id3.delall(kind)
            return delete

        def comm_set(id3, key, value):
            id3.delall("COMM")
            id3.add(COMM(encoding=3, lang="eng", desc="", text=value))

        def uslt_set(id3, key, value):
            id3.delall("USLT")
            id3.add(USLT(encoding=3, lang="eng", desc="", text=value[0] if value else ""))

        if "comment" not in EasyID3.valid_keys:
            EasyID3.RegisterKey("comment", frame_get("COMM"), comm_set, frame_delete("COMM"))
        if "lyrics" not in EasyID3.valid_keys:
            EasyID3.RegisterKey("lyrics", frame_get("USLT"), uslt_set, frame_delete("USLT"))
    except Exception as e:
        _log("tags: mp3 keys: %s" % e)
    try:
        from mutagen.easymp4 import EasyMP4Tags
        for key, atom in (("lyrics", "\xa9lyr"), ("composer", "\xa9wrt")):
            if key not in EasyMP4Tags.Get:
                EasyMP4Tags.RegisterTextKey(key, atom)
    except Exception as e:
        _log("tags: m4a keys: %s" % e)


if mutagen is not None:
    _register_keys()
WRITE_REQUEST = 7301


def read(path):
    """The editable fields as plain strings; empty where the file has none."""
    values = {key: "" for key, _ in FIELDS}
    if mutagen is None or not path or not os.path.isfile(path):
        return values
    try:
        easy = mutagen.File(path, easy=True)
        if easy is not None and easy.tags is not None:
            for key, _ in FIELDS:
                try:
                    found = easy.tags.get(key)
                except Exception:
                    found = None
                if found:
                    values[key] = str(found[0]).strip()
    except Exception as e:
        _log("tags read %s: %s" % (os.path.basename(path), e))
    if not values["lyrics"]:
        values["lyrics"] = _raw_lyrics(path)
    return values


def _raw_lyrics(path):
    """Lyrics under the other names containers keep them: UNSYNCEDLYRICS, USLT frames, the M4A atom."""
    try:
        tags_ = mutagen.File(path).tags
        for key in list(tags_.keys()):
            if str(key).upper().startswith("USLT") or str(key).upper() in ("LYRICS", "UNSYNCEDLYRICS", "\xa9LYR"):
                value = tags_[key]
                value = getattr(value, "text", value)
                return str(value[0] if isinstance(value, (list, tuple)) and value else value).strip()
    except Exception:
        pass
    return ""


def from_item(item):
    """A song an extension found, as the editor's fields."""
    date = str(item.get("release_date") or item.get("year") or "")
    track, total = item.get("track_number"), item.get("total_tracks")
    values = {"title": item.get("name") or "", "artist": item.get("artists") or "", "album": item.get("album_name") or "",
              "albumartist": item.get("album_artist") or "", "date": date[:10], "genre": item.get("genre") or "",
              "tracknumber": ("%s/%s" % (track, total) if track and total else str(track or "")),
              "discnumber": str(item.get("disc_number") or ""), "isrc": item.get("isrc") or "",
              "composer": item.get("composer") or "", "organization": item.get("label") or "",
              "copyright": item.get("copyright") or ""}
    return {key: str(value).strip() for key, value in values.items()}


def fetch_cover(url):
    """The cover's bytes, only when they are a JPEG or a PNG."""
    import requests
    try:
        response = requests.get(url, timeout=20)
        if response.ok and response.content[:3] in (b"\xff\xd8\xff", b"\x89PN"):
            return response.content
    except Exception as e:
        _log("cover download: %s" % e)
    return None


def _write(path, values, cover):
    easy = mutagen.File(path, easy=True)
    if easy is None:
        raise ValueError("Этот формат файла не поддерживает теги.")
    if easy.tags is None:
        easy.add_tags()
    for key, value in values.items():
        value = str(value or "").strip()
        try:
            if value:
                easy.tags[key] = [value]
            elif key in easy.tags:
                del easy.tags[key]
        except Exception as e:
            _log("tag %s: %s" % (key, e))  # some containers have no place for a field (ISRC in M4A)
    easy.save()
    if "lyrics" in values and path.lower().endswith((".flac", ".ogg", ".opus")):
        # the text is written as LYRICS: an older copy under the other name would come back
        audio = mutagen.File(path)
        if audio is not None and audio.tags is not None and "UNSYNCEDLYRICS" in [str(k).upper() for k in audio.tags.keys()]:
            del audio["UNSYNCEDLYRICS"]
            audio.save()
    if cover:
        _write_cover(path, cover)


def _write_cover(path, cover):
    mime = "image/png" if cover[:3] == b"\x89PN" else "image/jpeg"
    lower = path.lower()
    if lower.endswith(".flac"):
        from mutagen.flac import FLAC, Picture
        audio = FLAC(path)
        picture = Picture()
        picture.type, picture.mime, picture.data = 3, mime, cover
        audio.clear_pictures()
        audio.add_picture(picture)
        audio.save()
    elif lower.endswith(".mp3"):
        from mutagen.id3 import APIC, ID3
        audio = ID3(path)
        audio.delall("APIC")
        audio.add(APIC(encoding=3, mime=mime, type=3, desc="Cover", data=cover))
        audio.save()
    elif lower.endswith((".m4a", ".mp4", ".aac")):
        from mutagen.mp4 import MP4, MP4Cover
        audio = MP4(path)
        audio["covr"] = [MP4Cover(cover, MP4Cover.FORMAT_PNG if mime == "image/png" else MP4Cover.FORMAT_JPEG)]
        audio.save()
    elif lower.endswith((".ogg", ".opus")):
        import base64
        from mutagen.flac import Picture
        audio = mutagen.File(path)
        picture = Picture()
        picture.type, picture.mime, picture.data = 3, mime, cover
        audio["metadata_block_picture"] = [base64.b64encode(picture.write()).decode("ascii")]
        audio.save()


def _refused(error):
    while error is not None:
        if isinstance(error, PermissionError) or getattr(error, "errno", None) in (1, 13):
            return True
        error = error.__cause__ or error.__context__
    return False


def _media_uri(path):
    MediaStore = jclass("android.provider.MediaStore")
    external = MediaStore.Audio.Media.getContentUri("external")
    String = jclass("java.lang.String")
    cursor = _ctx().getContentResolver().query(external, jarray(String)(["_id"]), "_data=?", jarray(String)([path]), None)
    if cursor is None:
        return None
    try:
        return jclass("android.content.ContentUris").withAppendedId(external, cursor.getLong(0)) if cursor.moveToFirst() else None
    finally:
        cursor.close()


def save(path, values, cover=None):
    """Writes the tags (and the cover). A file another app owns is written through MediaStore, which Android allows
    only after it asked the person (request_access); until then this raises PermissionError."""
    if mutagen is None:
        raise RuntimeError("Нет библиотеки mutagen: теги не записать.")
    try:
        _write(path, values, cover)
        return
    except Exception as e:
        if not _refused(e):
            raise
    uri = _media_uri(path)
    if uri is None:
        raise PermissionError(path)
    temp = os.path.join(str(_ctx().getCacheDir().getAbsolutePath()), "sculpt-tags" + os.path.splitext(path)[1])
    shutil.copyfile(path, temp)
    try:
        _write(temp, values, cover)
        try:
            out = _ctx().getContentResolver().openOutputStream(uri, "wt")
        except Exception as e:
            raise PermissionError(str(e))
        try:
            with open(temp, "rb") as f:
                while True:
                    chunk = f.read(256 * 1024)
                    if not chunk:
                        break
                    out.write(jarray(jbyte)(chunk))
        finally:
            out.close()
    finally:
        try:
            os.remove(temp)
        except OSError:
            pass


def request_access(path):
    """Android 11+ asks the person whether this app may change a file another app made. True when it asked."""
    try:
        activity = jclass("org.telegram.ui.LaunchActivity").instance
        if activity is None or jclass("android.os.Build$VERSION").SDK_INT < 30:
            return False
        uri = _media_uri(path)
        if uri is None:
            return False
        uris = jclass("java.util.ArrayList")()
        uris.add(uri)
        pending = jclass("android.provider.MediaStore").createWriteRequest(_ctx().getContentResolver(), uris)
        activity.startIntentSenderForResult(pending.getIntentSender(), WRITE_REQUEST, None, 0, 0, 0)
        return True
    except Exception as e:
        _log("write request: %s" % e)
        return False
