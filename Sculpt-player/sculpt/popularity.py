# Sculpt Player for exteraGram. Copyright 2026 BroNik (@BroZYTnikkkk).

"""How popular a found author or song is, the way Spotify shows it: an author's listeners or fans, a song's plays or
a share of the top.

First what the extension itself returned (popularity, plays, listeners, fans); then Spotify, when the user signed in
to it for Canvas in exteraGram's player settings (an author's monthly listeners, a song's plays, as Spotify shows
them; read with that sign-in, nothing is changed); then Last.fm with the user's own API key; else Deezer's open API
without a key (an author's fans, a song's rank). Only the name and the author go to those services. Results are
kept for the session."""

import json
import threading
import urllib.error
import urllib.parse
import urllib.request

from .i18n import language, plural, tr
from .common import _java_class, _log

DEEZER = "https://api.deezer.com"
LASTFM = "https://ws.audioscrobbler.com/2.0/"
TIMEOUT = 6
RANK_TOP = 1000000.0  # Deezer's rank runs up to about a million
AGENT = "SculptPlayer/1.0"
SPOTIFY = "com.exteragram.messenger.player.motion.SpotifyCanvasRepository"
PATHFINDER = "https://api-partner.spotify.com/pathfinder/v2/query"
BROWSER = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"
_spotify = {"hashes": None, "scraped_at": 0.0, "told": set()}

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
    failed = False
    try:
        if plugin.get_setting("popularity_spotify", True):
            found = _spotify_lookup(kind, name, artist)
    except Exception as e:
        failed = True  # a failure is not kept: the next screen asks Spotify again
        _tell("spotify %s: %s" % (kind, e))
    try:
        api_key = str(plugin.get_setting("lastfm_key", "") or "").strip()
        if found is None and api_key:
            found = _lastfm(api_key, kind, name, artist)
        if found is None and plugin.get_setting("popularity_deezer", True):
            found = _deezer(kind, name, artist)
    except Exception as e:
        _log("popularity %s: %s" % (kind, type(e).__name__))
    if not failed:
        with _lock:
            _cache[key] = found
    return found


def _tell(text):
    """A failure once per kind of failure: a list of twenty songs would write it twenty times."""
    head = text.split(":", 1)[0]
    if head not in _spotify["told"]:
        _spotify["told"].add(head)
        _log("popularity " + text)


# -- Spotify, with exteraGram's own sign-in (the one its player uses for Canvas)

def _repository_call(name, *args):
    """A static method of exteraGram's SpotifyCanvasRepository, private ones too."""
    Repo = _java_class(SPOTIFY)
    if name == "searchHash":
        method = Repo.getDeclaredMethod(name, jclass_boolean())
    else:
        method = Repo.getDeclaredMethod(name)
    method.setAccessible(True)
    return method.invoke(None, *args)


def jclass_boolean():
    from java import jclass
    return jclass("java.lang.Boolean").TYPE


def _spotify_token():
    if not bool(_repository_call("isLoggedIn")):
        return None
    token = _repository_call("token")  # refreshed by exteraGram itself when it ran out
    return str(token) if token else None


def _spotify_hashes(again=False):
    """The persisted queries' hashes of Spotify's web player for an author's overview and a song, read from its
    public code the way exteraGram reads the search's; once a session, again an hour after a failure."""
    import re
    import time
    if _spotify["hashes"] is not None and not again:
        return _spotify["hashes"]
    if again and time.time() - _spotify["scraped_at"] < 3600:
        return _spotify["hashes"]
    _spotify["scraped_at"] = time.time()
    home = _text("https://open.spotify.com/")
    bundle = re.search(r"/web-player/(web-player\.[0-9a-f]+\.js)", home)
    if not bundle:
        raise RuntimeError("no web player bundle")
    code = _text("https://open.spotifycdn.com/cdn/build/web-player/" + bundle.group(1))
    found = {}
    for operation in ("queryArtistOverview", "getTrack"):
        hit = re.search(r'"%s","query","([0-9a-f]{64})"' % operation, code)
        if hit:
            found[operation] = hit.group(1)
    _spotify["hashes"] = found
    return found


def _text(url):
    request = urllib.request.Request(url, headers={"User-Agent": BROWSER})
    with urllib.request.urlopen(request, timeout=TIMEOUT * 2) as answer:
        return answer.read().decode("utf-8", "replace")


def _pathfinder(token, operation, digest, variables):
    """One query; a server error now and then (Spotify answers 500 at times) is tried once more."""
    import time
    try:
        return _pathfinder_once(token, operation, digest, variables)
    except urllib.error.HTTPError as e:
        if e.code < 500:
            raise
        time.sleep(0.8)
        return _pathfinder_once(token, operation, digest, variables)


def _pathfinder_once(token, operation, digest, variables):
    body = json.dumps({"variables": variables, "operationName": operation,
                       "extensions": {"persistedQuery": {"version": 1, "sha256Hash": digest}}}).encode("utf-8")
    request = urllib.request.Request(PATHFINDER, data=body, method="POST", headers={
        "Authorization": "Bearer " + token, "App-Platform": "WebPlayer", "User-Agent": BROWSER,
        "Content-Type": "application/json;charset=UTF-8", "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as answer:
        return json.loads(answer.read().decode("utf-8"))


def _search(token, words):
    digest = _repository_call("searchHash", False)
    if not digest:
        raise RuntimeError("no search hash")
    data = _pathfinder(token, "searchTracks", str(digest), {
        "searchTerm": words, "offset": 0, "limit": 10, "numberOfTopResults": 5, "includeAudiobooks": False,
        "includePreReleases": False, "includeAuthors": False})
    items = (((data.get("data") or {}).get("searchV2") or {}).get("tracksV2") or {}).get("items") or []
    return [((i or {}).get("item") or {}).get("data") or {} for i in items]


def _names(track):
    return [((a or {}).get("profile") or {}).get("name") or "" for a in ((track.get("artists") or {}).get("items") or [])], \
        [(a or {}).get("uri") or "" for a in ((track.get("artists") or {}).get("items") or [])]


def _same(a, b):
    import re
    clean = lambda t: re.sub(r"[\W_]+", "", (t or "").casefold())
    return clean(a) == clean(b) and bool(clean(a))


def _spotify_lookup(kind, name, artist):
    token = _spotify_token()
    if not token:
        return None
    hashes = _spotify_hashes()
    first = (artist or "").split(",")[0].strip()
    if kind == "artist":
        uri = None
        for track in _search(token, name):
            names, uris = _names(track)
            for who, where in zip(names, uris):
                if _same(who, name) and where.startswith("spotify:artist:"):
                    uri = where
                    break
            if uri:
                break
        if not uri or "queryArtistOverview" not in hashes:
            return None
        data = _pathfinder(token, "queryArtistOverview", hashes["queryArtistOverview"],
                           {"uri": uri, "locale": "", "preReleaseV2": False})
        stats = ((data.get("data") or {}).get("artistUnion") or {}).get("stats") or {}
        monthly = _number(stats.get("monthlyListeners"))
        if not monthly and data.get("errors"):
            _spotify_hashes(again=True)
            raise RuntimeError("overview: %s" % str(data["errors"])[:120])
        return {"monthly": monthly} if monthly else None
    uri = None
    for track in _search(token, ("%s %s" % (first, name)).strip()):
        names, _ = _names(track)
        if _same(track.get("name"), name) and (not first or any(_same(n, first) for n in names)):
            uri = track.get("uri")
            break
    if not uri or "getTrack" not in hashes:
        return None
    data = _pathfinder(token, "getTrack", hashes["getTrack"], {"uri": uri})
    plays = _number(((data.get("data") or {}).get("trackUnion") or {}).get("playcount"))
    if not plays and data.get("errors"):
        _spotify_hashes(again=True)
        raise RuntimeError("track: %s" % str(data["errors"])[:120])
    return {"plays": plays} if plays else None


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


def _word_count(count):
    """The number the noun agrees with: "11 млн" reads as many ("слушателей"), whatever the exact count is."""
    return count if count < 1000 else 5


def describe(found):
    """The words for a row; None for a share, which is drawn as bars."""
    if not found:
        return None
    if "monthly" in found:
        count = int(found["monthly"])
        return tr("%s в месяц") % ("%s %s" % (compact(count), plural(_word_count(count), tr("слушатель"), tr("слушателя"), tr("слушателей"))))
    if "listeners" in found:
        count = int(found["listeners"])
        return "%s %s" % (compact(count), plural(_word_count(count), tr("слушатель"), tr("слушателя"), tr("слушателей")))
    if "fans" in found:
        count = int(found["fans"])
        return "%s %s" % (compact(count), plural(_word_count(count), tr("фанат"), tr("фаната"), tr("фанатов")))
    if "plays" in found:
        count = int(found["plays"])
        return "%s %s" % (compact(count), plural(_word_count(count), tr("прослушивание"), tr("прослушивания"), tr("прослушиваний")))
    return None


def bars(share):
    """How many of five bars a share fills."""
    return max(1, min(5, int(round(share * 5 + 0.49)))) if share > 0 else 0
