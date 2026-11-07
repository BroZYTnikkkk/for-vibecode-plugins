# SPDX-License-Identifier: LGPL-3.0-only
# Mornye extensions in Sculpt Player. Copyright 2026 BroNik (@BroZYTnikkkk).
# Based on Mornye by zarzet (https://github.com/mornyeapp/Mornye), LGPL-3.0-only.

"""LRCLIB lyrics, Mornye's fallback lyrics source, which an extension's host may ask for."""

import requests

from .logs import log

USER_AGENT = "SculptPlayerPlugin/1.0 (exteraGram; https://github.com/mornyeapp/Mornye)"


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
