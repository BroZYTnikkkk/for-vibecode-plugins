# SPDX-License-Identifier: LGPL-3.0-only
# Mornye Player for exteraGram. Copyright 2026 BroNik (@BroZYTnikkkk).
# Based on Mornye by zarzet (https://github.com/mornyeapp/Mornye), LGPL-3.0-only.

"""Song metadata: reading and editing tags, embedded and sidecar lyrics."""

import os
import re
from android_utils import log
from java import jclass
from org.telegram.messenger import ApplicationLoader
from .common import mutagen

EDITABLE = ("title", "artist", "album", "albumartist", "date", "genre", "tracknumber", "discnumber", "lyrics")
_LRC_STAMP = re.compile(r"\[(\d{1,3}):(\d{1,2})(?:[.:](\d{1,3}))?\]")


def parse_lrc(text):
    """LRC or plain text -> {"synced", "lines": [(ms, text)]}, or None when empty."""
    text = (text or "").replace("\r\n", "\n").strip()
    if not text:
        return None
    timed = []
    for raw in text.split("\n"):
        stamps = _LRC_STAMP.findall(raw)
        words = _LRC_STAMP.sub("", raw).strip()
        for mm, ss, frac in stamps:
            timed.append((int(mm) * 60000 + int(ss) * 1000 + (int(frac.ljust(3, "0")[:3]) if frac else 0), words))
    if timed:
        timed.sort()
        return {"synced": True, "lines": timed}
    return {"synced": False, "lines": [(0, line) for line in text.split("\n")]}


def _open(path):
    if mutagen is None or not path or not os.path.isfile(path):
        return None
    try:
        return mutagen.File(path)
    except Exception:
        return None


def _id3(audio):
    tags = getattr(audio, "tags", None)
    return tags if tags is not None and hasattr(tags, "getall") else None


def embedded_lyrics(path):
    """Lyrics from the file's own tags, then from a .lrc file next to it."""
    audio = _open(path)
    if audio is not None and audio.tags is not None:
        try:
            id3 = _id3(audio)
            if id3 is not None:
                for frame in id3.getall("SYLT"):
                    # format 2 = milliseconds
                    if getattr(frame, "format", 2) == 2 and frame.text:
                        return {"synced": True, "lines": sorted((int(ms), str(t).strip()) for t, ms in frame.text)}
                for frame in id3.getall("USLT"):
                    found = parse_lrc(str(frame.text))
                    if found:
                        return found
            else:
                for key in ("lyrics", "LYRICS", "unsyncedlyrics", "UNSYNCEDLYRICS", "\xa9lyr"):
                    value = audio.tags.get(key)
                    if value:
                        found = parse_lrc(value[0] if isinstance(value, list) else str(value))
                        if found:
                            return found
        except Exception as e:
            log("[Mornye] lyrics tags %s: %s" % (os.path.basename(path), e))
    if path:
        sidecar = os.path.splitext(path)[0] + ".lrc"
        if os.path.isfile(sidecar):
            try:
                with open(sidecar, encoding="utf-8", errors="replace") as f:
                    return parse_lrc(f.read())
            except OSError:
                pass
    return None


def read_editable(path):
    """The editable fields as plain strings."""
    out = {k: "" for k in EDITABLE}
    audio = _open(path)
    if audio is None:
        return out
    try:
        easy = mutagen.File(path, easy=True)
        if easy is not None and easy.tags is not None:
            for key in EDITABLE[:-1]:
                value = easy.tags.get(key)
                if value:
                    out[key] = str(value[0])
    except Exception:
        pass
    found = embedded_lyrics(path)
    if found:
        if found["synced"]:
            out["lyrics"] = "\n".join("[%02d:%02d.%02d]%s" % (ms // 60000, ms // 1000 % 60, ms // 10 % 100, t)
                                      for ms, t in found["lines"])
        else:
            out["lyrics"] = "\n".join(t for _, t in found["lines"])
    return out


def write_tags(path, values):
    """Write the given fields; raises PermissionError when Android refuses the file."""
    easy = mutagen.File(path, easy=True)
    if easy is None:
        raise ValueError("unsupported audio file")
    if easy.tags is None:
        easy.add_tags()
    for key in EDITABLE[:-1]:
        if key not in values:
            continue
        value = str(values[key] or "").strip()
        try:
            if value:
                easy.tags[key] = [value]
            elif key in easy.tags:
                del easy.tags[key]
        except Exception as e:
            log("[Mornye] tag %s: %s" % (key, e))
    easy.save()
    if "lyrics" in values:
        _write_lyrics(path, str(values["lyrics"] or ""))


def _write_lyrics(path, text):
    audio = mutagen.File(path)
    id3 = _id3(audio)
    if id3 is not None:
        from mutagen.id3 import USLT
        id3.delall("USLT")
        if text.strip():
            id3.add(USLT(encoding=3, lang="XXX", desc="", text=text))
    elif audio.tags is not None:
        key = "\xa9lyr" if type(audio).__name__ == "MP4" else "LYRICS"
        if text.strip():
            audio.tags[key] = [text]
        elif key in audio.tags:
            del audio.tags[key]
    audio.save()


def request_write_access(activity, path):
    """Ask Android (11+) for permission to modify a file the app does not own. True if the prompt opened."""
    try:
        Build = jclass("android.os.Build")
        if Build.VERSION.SDK_INT < 30 or activity is None:
            return False
        MediaStore = jclass("android.provider.MediaStore")
        resolver = ApplicationLoader.applicationContext.getContentResolver()
        external = MediaStore.Audio.Media.getContentUri("external")
        cursor = resolver.query(external, [MediaStore.MediaColumns._ID], MediaStore.MediaColumns.DATA + "=?", [path], None)
        if cursor is None:
            return False
        try:
            if not cursor.moveToFirst():
                return False
            uri = jclass("android.content.ContentUris").withAppendedId(external, cursor.getLong(0))
        finally:
            cursor.close()
        uris = jclass("java.util.ArrayList")()
        uris.add(uri)
        pending = MediaStore.createWriteRequest(resolver, uris)
        activity.startIntentSenderForResult(pending.getIntentSender(), 7301, None, 0, 0, 0)
        return True
    except Exception as e:
        log("[Mornye] write request: %s" % e)
        return False
