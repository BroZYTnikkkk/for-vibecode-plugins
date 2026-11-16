# SPDX-License-Identifier: LGPL-3.0-only
# Sculpt Player for exteraGram. Copyright 2026 BroNik (@BroZYTnikkkk).
# Mornye Link comes from Mornye by zarzet (https://github.com/mornyeapp/Mornye), LGPL-3.0-only.

"""Songs that live on the computer. MediaController plays only files, so each gets an empty marker file: Telegram
starts it like any song on the phone, and LinkSourceHook swaps the file for an address of sculpt.LinkProxy."""

import json
import os
import urllib.parse
import uuid

from java.lang import Integer as JInteger

from . import link
from .common import _ctx, _log, sculpt_method

SERVER_KEY = "link_server"
DEVICE_KEY = "link_device"
MARK = ".mp3"  # the name Telegram sees; the player recognizes the real format from the sound itself


def saved_server(plugin):
    try:
        value = json.loads(plugin.get_setting(SERVER_KEY, "") or "null")
    except ValueError:
        return None
    return value if isinstance(value, dict) and value.get("apiKey") else None


def device_id(plugin):
    value = plugin.get_setting(DEVICE_KEY, "")
    if not value:
        value = str(uuid.uuid4())
        plugin.set_setting(DEVICE_KEY, value)
    return value


def folder():
    return os.path.join(str(_ctx().getCacheDir().getAbsolutePath()), "sculpt_link")


def marker(song_id):
    """The empty file standing for this song."""
    where = folder()
    os.makedirs(where, exist_ok=True)
    path = os.path.join(where, song_id.encode().hex() + MARK)
    if not os.path.exists(path):
        open(path, "ab").close()
    return path


def tracks_of(songs):
    """The computer's songs in the form the rest of the plugin plays."""
    return [{"path": marker(str(s["id"])), "title": str(s.get("title") or ""), "artist": str(s.get("artist") or ""),
             "album": str(s.get("album") or ""), "duration": int(s.get("duration") or 0)} for s in songs if s.get("id")]


def stream_url(plugin, path):
    """Where the sound of this marker file comes from; None for any other file."""
    where, name = os.path.split(path)
    if not name.endswith(MARK) or where != folder():
        return None
    saved = saved_server(plugin)
    start = sculpt_method("sculpt.LinkProxy", "start")
    if saved is None or start is None:
        _log("link: nothing to stream from")
        return None
    song_id = bytes.fromhex(name[:-len(MARK)]).decode()
    base = start.invoke(None, saved["host"], JInteger(int(saved["port"])), saved["fingerprint"], link.stream_query(saved["apiKey"]))
    return "%s%s" % (base, urllib.parse.quote(song_id, safe=""))


def stop():
    method = sculpt_method("sculpt.LinkProxy", "stop")
    if method is not None:
        method.invoke(None)
