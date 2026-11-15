# Sculpt Player for exteraGram. Copyright 2026 BroNik (@BroZYTnikkkk).

"""How popular a found author or song is, the way Spotify shows it: an author's listeners or fans, a song's plays or
a share of the top.

First what the extension itself returned (popularity, plays, listeners, fans); then, when allowed, Last.fm with the
user's own API key (real listeners and plays), else Deezer's open API without a key (an author's fans, a song's
rank). Only the name and the author go to those services. Results are kept for the session."""

import json
import threading
import urllib.parse
import urllib.request

from .i18n import language, plural, tr
from .common import _log

DEEZER = "https://api.deezer.com"
LASTFM = "https://ws.audioscrobbler.com/2.0/"
TIMEOUT = 6
RANK_TOP = 1000000.0  # Deezer's rank runs up to about a million
AGENT = "SculptPlayer/1.0"

_cache = {}
_lock = threading.Lock()


def from_item(item):
    """What the extension gave: {"listeners"|"fans"|"plays": n} or {"share": 0..1}; None when nothing."""
    for key, name in (("listeners", "listeners"), ("monthly_listeners", "listeners"), ("followers", "fans"),
                      ("fans", "fans"), ("nb_fan", "fans"), ("plays", "plays"), ("play_count", "plays"),
                      ("playcount", "plays"), ("streams", "plays")):
        value = _number(item.get(key))
        if value:
            return {name: value}
    popularity = _number(item.get("popularity"))
    if popularity:
        return {"share": min(1.0, popularity / (100.0 if popularity <= 100 else RANK_TOP))}
    rank = _number(item.get("rank"))
    if rank:
        return {"share": min(1.0, rank / RANK_TOP)}
    return None


def _number(value):
    try:
        number = float(value)
        return number if number > 0 else 0
    except (TypeError, ValueError):
        return 0


def _get(url):
    request = urllib.request.Request(url, headers={"User-Agent": AGENT})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as answer:
        return json.loads(answer.read().decode("utf-8"))


def lookup(plugin, kind, name, artist):
    """Off the UI thread: the popularity of an author ("artist") or a song ("track"); None when unknown."""
    key = (kind, (name or "").casefold(), (artist or "").casefold())
    with _lock:
        if key in _cache:
            return _cache[key]
    found = None
    try:
        api_key = str(plugin.get_setting("lastfm_key", "") or "").strip()
        if api_key:
            found = _lastfm(api_key, kind, name, artist)
        if found is None and plugin.get_setting("popularity_deezer", True):
            found = _deezer(kind, name, artist)
    except Exception as e:
        _log("popularity %s: %s" % (kind, type(e).__name__))
    with _lock:
        _cache[key] = found
    return found


def _lastfm(api_key, kind, name, artist):
    if kind == "artist":
        query = {"method": "artist.getinfo", "artist": name}
    else:
        query = {"method": "track.getinfo", "artist": artist, "track": name}
    query.update({"api_key": api_key, "format": "json", "autocorrect": "1"})
    data = _get(LASTFM + "?" + urllib.parse.urlencode(query))
    if kind == "artist":
        listeners = _number(((data.get("artist") or {}).get("stats") or {}).get("listeners"))
        return {"listeners": listeners} if listeners else None
    plays = _number((data.get("track") or {}).get("playcount"))
    return {"plays": plays} if plays else None


def _deezer(kind, name, artist):
    if kind == "artist":
        data = _get(DEEZER + "/search/artist?" + urllib.parse.urlencode({"q": name, "limit": 1}))
        hits = data.get("data") or []
        if hits and str(hits[0].get("name") or "").casefold() == (name or "").casefold():
            fans = _number(hits[0].get("nb_fan"))
            return {"fans": fans} if fans else None
        return None
    # Deezer's advanced form (artist:"..." track:"...") answers nothing from the open API: the plain words, then
    # the first hit by the same author
    first = (artist or "").split(",")[0].strip()
    data = _get(DEEZER + "/search/track?" + urllib.parse.urlencode({"q": ("%s %s" % (first, name)).strip(), "limit": 5}))
    for hit in data.get("data") or []:
        author = str((hit.get("artist") or {}).get("name") or "").casefold()
        if not first or first.casefold() in author or author in first.casefold():
            rank = _number(hit.get("rank"))
            return {"share": min(1.0, rank / RANK_TOP)} if rank else None
    return None


def compact(number):
    """1 234 567 -> "1,2 млн", in the player's language."""
    number = float(number)
    english = language() == "en"
    if number >= 1e9:
        value, unit = number / 1e9, "B" if english else tr("млрд")
    elif number >= 1e6:
        value, unit = number / 1e6, "M" if english else tr("млн")
    elif number >= 1e3:
        value, unit = number / 1e3, "K" if english else tr("тыс.")
    else:
        return "%d" % number
    text = ("%.1f" % value).rstrip("0").rstrip(".") if value < 10 else "%d" % value
    if not english:
        text = text.replace(".", ",")
    return text + ("" if english else " ") + unit


def describe(found):
    """The words for a row; None for a share, which is drawn as bars."""
    if not found:
        return None
    if "listeners" in found:
        count = int(found["listeners"])
        return "%s %s" % (compact(count), plural(count, tr("слушатель"), tr("слушателя"), tr("слушателей")))
    if "fans" in found:
        count = int(found["fans"])
        return "%s %s" % (compact(count), plural(count, tr("фанат"), tr("фаната"), tr("фанатов")))
    if "plays" in found:
        count = int(found["plays"])
        return "%s %s" % (compact(count), plural(count, tr("прослушивание"), tr("прослушивания"), tr("прослушиваний")))
    return None


def bars(share):
    """How many of five bars a share fills."""
    return max(1, min(5, int(round(share * 5 + 0.49)))) if share > 0 else 0
