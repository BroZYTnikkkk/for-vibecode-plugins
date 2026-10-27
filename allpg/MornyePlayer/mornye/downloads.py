# SPDX-License-Identifier: LGPL-3.0-only
# Mornye Player for exteraGram. Copyright 2026 BroNik (@BroZYTnikkkk).
# Based on Mornye by zarzet (https://github.com/mornyeapp/Mornye), LGPL-3.0-only.

"""Download planner and queue (port of Mornye backend/downloads.rs)."""

import json
import os
import re
import requests
import secrets
import shutil
import tempfile
import threading
import time
import unicodedata
from android_utils import log
from .common import mutagen
from .platform_android import PLATFORM
from .ext_runtime import (
    CallContext,
    ExtError,
    _ci,
    sanitize_filename,
)


# -- download planner (port of extensions/src/backend/downloads.rs) -------------

_HOST_TRACK_KEYS = ("album_name", "album_artist", "cover_url", "release_date", "track_number", "total_tracks",
                    "disc_number", "total_discs", "duration_ms", "isrc", "genre", "label", "copyright",
                    "composer", "comment", "explicit", "album_type", "upc")


def _loose(text):
    text = unicodedata.normalize("NFKC", str(text or "")).lower()
    text = re.sub(r"\s*[\(\[].*?(feat|ft\.|with|remaster|version|edit|live|mono|stereo).*?[\)\]]", "", text)
    text = re.sub(r"\s+(feat\.?|ft\.?)\s+.*$", "", text)
    return re.sub(r"[\W_]+", "", text)


def _artist_set(text):
    parts = re.split(r",|&|;|/| x | and | feat\.? | ft\.? ", str(text or "").lower())
    return {_loose(p) for p in parts if _loose(p)}


def titles_match(a, b):
    a, b = _loose(a), _loose(b)
    return bool(a) and bool(b) and (a == b or a in b or b in a)


def artists_match(a, b):
    left, right = _artist_set(a), _artist_set(b)
    if not left or not right:
        return True
    if left & right:
        return True
    return any(x in y or y in x for x in left for y in right)


def _duration_ok(request, result):
    expected = int(request.get("duration_ms") or 0) // 1000
    actual = int(result.get("duration_ms") or 0) // 1000
    return expected <= 0 or actual <= 0 or abs(expected - actual) <= 10


def matches_track(request, result, skip_names):
    """Did the provider return the requested song? (backend/downloads/matching.rs)"""
    isrc = str(request.get("isrc") or "").strip().upper()
    found_isrc = str(result.get("isrc") or "").strip().upper()
    if isrc and found_isrc and isrc == found_isrc:
        return True
    if skip_names:
        return _duration_ok(request, result)
    title = result.get("title") or ""
    artist = result.get("artist") or ""
    if title and not titles_match(request.get("track_name"), title):
        return False
    if artist and not artists_match(request.get("artist_name"), artist):
        return False
    if not _duration_ok(request, result):
        return False
    if isrc and found_isrc and isrc != found_isrc and request.get("album_name") and result.get("album") and \
            not titles_match(request["album_name"], result["album"]):
        return False
    return True


def _audio_container(path):
    try:
        with open(path, "rb") as f:
            head = f.read(12)
    except OSError:
        return ""
    if head[:4] == b"fLaC":
        return "flac"
    if head[4:8] == b"ftyp":
        return "m4a"
    if head[:3] == b"ID3" or (len(head) > 1 and head[0] == 0xFF and head[1] & 0xE0 == 0xE0):
        return "mp3"
    if head[:4] == b"OggS":
        return "ogg"
    if head[:4] == b"RIFF":
        return "wav"
    return ""


def request_from_track(track, service="", quality="", use_fallback=True):
    """A Mornye DownloadRequest from an extension track (download_queue_provider.dart)."""
    tid = str(track.get("id") or "")
    spotify_id, qobuz_id, tidal_id = tid, "", ""
    if tid.startswith("qobuz:"):
        qobuz_id = tid[6:]
    if tid.startswith("tidal:"):
        tidal_id = tid[6:]
    request = {
        "isrc": track.get("isrc") or "", "service": service, "source": track.get("provider_id") or "",
        "spotify_id": track.get("spotify_id") or spotify_id, "deezer_id": track.get("deezer_id") or "",
        "tidal_id": track.get("tidal_id") or tidal_id, "qobuz_id": track.get("qobuz_id") or qobuz_id,
        "track_name": track.get("name") or "", "artist_name": track.get("artists") or "",
        "album_name": track.get("album_name") or "", "album_artist": track.get("album_artist") or "",
        "cover_url": track.get("cover_url") or "", "release_date": track.get("release_date") or "",
        "track_number": int(track.get("track_number") or 0), "disc_number": int(track.get("disc_number") or 0),
        "total_tracks": int(track.get("total_tracks") or 0), "total_discs": int(track.get("total_discs") or 0),
        "duration_ms": int(track.get("duration_ms") or 0), "genre": track.get("genre") or "",
        "label": track.get("label") or "", "copyright": track.get("copyright") or "",
        "composer": track.get("composer") or "", "comment": track.get("comment") or "",
        "explicit": bool(track.get("explicit")), "album_type": track.get("album_type") or "",
        "upc": track.get("upc") or "", "quality": quality or "LOSSLESS", "use_fallback": use_fallback,
        "provider_track_id": "",
    }
    return request


def host_track(request):
    track = {k: request.get(k) for k in _HOST_TRACK_KEYS if request.get(k) not in (None, "")}
    track.update({"id": request.get("provider_track_id") or "", "name": request.get("track_name") or "",
                  "artists": request.get("artist_name") or ""})
    return track


def _apply_metadata(request, track, prefer_track):
    pairs = (("album_name", "album_name"), ("album_artist", "album_artist"), ("cover_url", "cover_url"),
             ("release_date", "release_date"), ("isrc", "isrc"), ("genre", "genre"), ("label", "label"),
             ("copyright", "copyright"), ("composer", "composer"), ("track_number", "track_number"),
             ("disc_number", "disc_number"), ("total_tracks", "total_tracks"), ("total_discs", "total_discs"),
             ("upc", "upc"), ("album_type", "album_type"))
    for key, source in pairs:
        value = track.get(source)
        if value in (None, "", 0):
            continue
        if prefer_track or request.get(key) in (None, "", 0):
            request[key] = value


def _preferred_track_id(request, manifest, explicit):
    if str(explicit or "").strip():
        return str(explicit).strip()
    replaces = [str(v).strip().lower() for v in ((manifest.capabilities or {}).get("replacesBuiltInProviders") or [])]
    for provider, key in (("tidal", "tidal_id"), ("qobuz", "qobuz_id"), ("deezer", "deezer_id")):
        if provider in replaces and str(request.get(key) or "").strip():
            return str(request[key]).strip()
    return str(request.get("spotify_id") or "").strip()


def _failure(service, message, kind="", retry=0):
    lowered = (message or "").lower()
    if not kind:
        if "verification_required" in lowered or "verify_required" in lowered:
            kind = "verification_required"
        elif "not found" in lowered or "no results" in lowered:
            kind = "not_found"
        elif "rate limit" in lowered or "429" in lowered:
            kind = "rate_limit"
        elif "timeout" in lowered:
            kind = "timeout"
        elif "permission denied" in lowered or "read-only" in lowered:
            kind = "permission"
        else:
            kind = "unknown"
    return {"success": False, "error": message, "error_type": kind, "service": service, "retry_after_seconds": retry}


def _storage_failure(kind, message):
    if (kind or "").lower() == "permission":
        return True
    message = (message or "").lower()
    return any(s in message for s in ("operation not permitted", "permission denied", "read-only file system",
                                      "failed to create file", "no space left"))


class DownloadPlanner:
    """Preflight, availability, provider fallback, staging, matching and publish."""

    def __init__(self, manager, output_dir):
        self.manager = manager
        self.output_dir = output_dir

    def run(self, request, ctx):
        m = self.manager
        session_provider = (request.get("service") or request.get("source") or "").strip()
        ctx.status = "checking_session"
        ctx.report(0.0)
        try:
            if session_provider and m.preflight(session_provider, ctx):
                return _failure(session_provider, "Verification required before download", "verification_required")
        except Exception as e:
            return _failure(session_provider, "Could not start verification for %s: %s" % (session_provider, e))
        ctx.status = "resolving_metadata"
        ctx.report(0.0)
        selected = (request.get("service") or "").strip()
        priority = m.priorities("download")
        source = (request.get("source") or "").strip()
        if not request.get("use_fallback", True):
            selected = selected or source
            if selected:
                priority = [selected]
        elif selected:
            priority = [selected] + [i for i in priority if i.lower() != selected.lower()]

        source_manifest = m.manifest(source) if source and m.is_enabled(source) else None
        source_availability = None
        if source_manifest and source_manifest.has_type("download_provider") and selected != source:
            try:
                availability = self._availability(source, request, ctx)
                if availability.get("skip_fallback") is True:
                    selected = source
                    source_availability = availability
            except Exception:
                pass
        self._enrich(request, ctx)

        attempts = []
        if source and selected == source:
            attempts.append((source, True))
        attempts += [(i, False) for i in priority]
        tried = set()
        last = None
        failures = []
        for ext, direct in attempts:
            ctx.check()
            if not ext or (ext, direct) in tried or (not direct and (ext, True) in tried and ext == source):
                continue
            tried.add((ext, direct))
            if not direct and ext == source and source != selected:
                continue
            if not direct and ext != selected and not m.fallback_allowed(ext):
                continue
            manifest = m.manifest(ext)
            if manifest is None or not m.is_enabled(ext) or not manifest.has_type("download_provider"):
                continue
            account_mode = m.account_download_enabled(ext)
            if direct:
                availability = source_availability or {"available": True}
            else:
                try:
                    if m.preflight(ext, ctx):
                        raise ExtError("verification_required: extension '%s' needs signed-session verification" % ext)
                    availability = self._availability(ext, request, ctx)
                except ExtError as e:
                    if str(e) == "download cancelled":
                        raise
                    response = _failure(ext, str(e))
                    if account_mode:
                        return response
                    if response["error_type"] == "verification_required":
                        return _failure(ext, "Download failed: %s" % e, "verification_required")
                    last = response
                    failures.append("%s: %s" % (ext, response.get("error") or ""))
                    continue
            stop = availability.get("skip_fallback") is True or account_mode
            if availability.get("available") is not True:
                if stop:
                    return self._stopped(ext, availability, "")
                last = _failure(ext, availability.get("reason") or "not available", "not_found")
                failures.append("%s: not available (%s)" % (ext, availability.get("reason") or "no reason"))
                continue
            attempt = dict(request)
            attempt["download_provider"] = ext
            attempt["provider_track_id"] = _preferred_track_id(request, manifest, availability.get("track_id")) if direct \
                else str(availability.get("track_id") or "")
            final, response = self._resolved(attempt, manifest, availability, ctx)
            if final:
                return response
            message, kind = response.get("error") or "", response.get("error_type") or ""
            m.log(ext, "WARN", "Provider %s failed during download: %s" % (ext, message or "no reason supplied"))
            if account_mode or kind == "verification_required":
                return _failure(ext, "Download failed: %s" % message, kind, response.get("retry_after_seconds") or 0)
            if _storage_failure(kind, message):
                return _failure(ext, "Download failed: %s" % message, "permission")
            if stop:
                return self._stopped(ext, availability, message)
            if direct and manifest.stop_fallback:
                return _failure(ext, "Download failed: %s" % message, kind)
            last = response
            failures.append("%s: %s" % (ext, message or "no reason supplied"))
        if last:
            kind = last.get("error_type") or "not_found"
            return _failure(selected or last.get("service") or "", "All providers failed. %s" % " | ".join(failures),
                            "not_found" if kind == "unknown" else kind, last.get("retry_after_seconds") or 0)
        return _failure("", "No extension download providers available", "not_found")

    @staticmethod
    def _stopped(ext, availability, message):
        reason = (availability.get("reason") or "").strip() or message or "extension requested no further fallback"
        return _failure(ext, "Fallback stopped by %s: %s" % (ext, reason), "extension_error")

    def _availability(self, ext, request, ctx):
        options = {"spotify_id": request.get("spotify_id") or "", "deezer_id": request.get("deezer_id") or "",
                   "tidal_id": request.get("tidal_id") or "", "qobuz_id": request.get("qobuz_id") or "",
                   "duration_ms": int(request.get("duration_ms") or 0), "track": host_track(request)}
        value = self.manager.provider_call(ext, "checkAvailability", [request.get("isrc") or "", request.get("track_name") or "",
                                                                      request.get("artist_name") or "", options], 30000, ctx)
        if value.get("available") is not True:
            self.manager.log(ext, "WARN", "Provider %s failed during availability: %s" % (ext, value.get("reason") or "no reason supplied"))
        return value

    def _enrich(self, request, ctx):
        m = self.manager
        source = request.get("source") or ""
        sm = m.manifest(source) if source else None
        if sm and m.is_enabled(source) and sm.has_type("metadata_provider"):
            track = host_track(request)
            track.update({"id": request.get("spotify_id") or "", "provider_id": source,
                          "spotify_id": request.get("spotify_id") or "", "tidal_id": request.get("tidal_id") or "",
                          "qobuz_id": request.get("qobuz_id") or "", "deezer_id": request.get("deezer_id") or ""})
            try:
                enriched = m.provider_call(source, "enrichTrack", [track], 30000, ctx)
                if isinstance(enriched, dict):
                    _apply_metadata(request, enriched, True)
            except ExtError as e:
                if str(e) == "download cancelled":
                    raise
        if request.get("track_name") and request.get("artist_name") and \
                not (request.get("album_name") and request.get("release_date") and request.get("isrc")):
            for track in m.search_metadata("%s %s" % (request["track_name"], request["artist_name"]), 5):
                if titles_match(request["track_name"], track.get("name")) and artists_match(request["artist_name"], track.get("artists")) \
                        and _duration_ok(request, track):
                    _apply_metadata(request, track, False)
                    break

    def _resolved(self, request, manifest, availability, ctx):
        m = self.manager
        quality_source = None
        for ext in (request.get("service"), request.get("source")):
            sm = m.manifest((ext or "").strip())
            if sm is not None and sm.find_quality((request.get("quality") or "").strip()):
                quality_source = sm
                break
        try:
            quality = manifest.resolve_download_quality(request.get("quality") or "", quality_source)
        except ExtError as e:
            return False, _failure(manifest.name, str(e), "quality_unavailable")
        request = dict(request)
        request["quality"] = quality
        return self._attempt(request, manifest, availability, ctx)

    def _filename(self, request, ext):
        artist = request.get("artist_name") or "Unknown"
        title = request.get("track_name") or "Track"
        return sanitize_filename("%s - %s" % (artist, title))[:180] + ext

    def _attempt(self, request, manifest, availability, ctx):
        m = self.manager
        os.makedirs(self.output_dir, exist_ok=True)
        downloads = os.path.join(m.data_dir(manifest.name), "downloads")
        os.makedirs(downloads, exist_ok=True)
        for name in os.listdir(downloads):
            if name.startswith(".mornye-download-"):
                shutil.rmtree(os.path.join(downloads, name), ignore_errors=True)
        for existing_ext in (".flac", ".m4a", ".mp3", ".opus", ".ogg"):
            existing = os.path.join(self.output_dir, self._filename(request, existing_ext))
            if os.path.isfile(existing) and os.path.getsize(existing) > 0:
                return True, {"success": True, "already_exists": True, "file_path": existing, "service": manifest.name,
                              "message": "File already exists"}
        staging = tempfile.mkdtemp(prefix=".mornye-download-%s-" % secrets.token_hex(4), dir=downloads)
        try:
            ctx.grants = [staging]
            staging_path = os.path.join(staging, self._filename(request, ".flac"))
            prepared = dict(availability.get("prepared_context") or {})
            prepared["host_track"] = host_track(request)
            ctx.status = "resolving_stream"
            ctx.report(0.0)
            result = m.download_call(manifest.name, request.get("provider_track_id") or "", request["quality"], staging_path, ctx,
                                     prepared, 60000)
            ctx.check()
            if result.get("success") is not True:
                message = result.get("error_message") or "extension download failed without an error message"
                kind = (result.get("error_type") or "").strip()
                if kind.lower() in ("", "unknown", "runtime_error", "api_error", "download_error", "extension_error"):
                    kind = _failure("", message)["error_type"]
                    kind = "extension_error" if kind == "unknown" else kind
                return False, _failure(manifest.name, message, kind, result.get("retry_after_seconds") or 0)
            skip_names = (request.get("source") or "").lower() == manifest.name.lower() or \
                bool(_ci(manifest.track_matching or {}, "customMatching", False))
            if not matches_track(request, result, skip_names):
                return False, _failure(manifest.name, "provider %s returned a different track" % manifest.name, "not_found")
            returned = str(result.get("file_path") or "").strip()
            exists = result.get("already_exists") is True or returned.startswith("EXISTS:")
            if returned.startswith("EXISTS:"):
                returned = returned[7:]
            returned = os.path.normpath(returned)
            if not exists and not returned.startswith(os.path.normpath(staging) + os.sep):
                return False, _failure(manifest.name, "provider output is outside its download staging directory", "file_error")
            if not os.path.isfile(returned) or os.path.getsize(returned) <= 0:
                return False, _failure(manifest.name, "provider returned no audio file", "file_error")
            ctx.status = "finalizing"
            ctx.report(1.0)
            source_path = returned
            container = _audio_container(source_path)
            if result.get("requires_container_conversion") is True or str(result.get("decryption", {}).get("strategy") or "") == "ffmpeg.mov_key":
                if result.get("decryption"):
                    return False, _failure(manifest.name, "this stream needs FFmpeg decryption, which the plugin cannot do", "unsupported")
                converted = os.path.join(staging, "converted.m4a")
                if PLATFORM.remux(source_path, converted, "m4a"):
                    source_path, container = converted, "m4a"
            ext = {"flac": ".flac", "m4a": ".m4a", "mp3": ".mp3", "ogg": ".ogg", "wav": ".wav"}.get(container) or \
                os.path.splitext(returned)[1] or ".flac"
            final_path = os.path.join(self.output_dir, self._filename(request, ext))
            if os.path.exists(final_path):
                final_path = os.path.join(self.output_dir, self._filename(request, " (%s)%s" % (manifest.name, ext)))
            shutil.move(source_path, final_path)
            response = {"success": True, "already_exists": exists, "file_path": final_path, "service": manifest.name,
                        "message": "Downloaded from %s" % manifest.name, "container": container,
                        "bit_depth": result.get("bit_depth"), "sample_rate": result.get("sample_rate")}
            for key, value in (("title", request.get("track_name")), ("artist", request.get("artist_name")),
                               ("album", request.get("album_name")), ("album_artist", request.get("album_artist")),
                               ("release_date", request.get("release_date")), ("cover_url", request.get("cover_url")),
                               ("isrc", request.get("isrc") or result.get("isrc")), ("genre", request.get("genre")),
                               ("track_number", request.get("track_number")), ("disc_number", request.get("disc_number"))):
                response[key] = value or result.get(key) or ""
            if result.get("lyrics_lrc"):
                response["lyrics_lrc"] = result["lyrics_lrc"]
            if response["isrc"]:
                with m.lock:
                    m.isrc_index[str(response["isrc"]).upper()] = final_path
                m.save_isrc_index()
            return True, response
        finally:
            ctx.grants = []
            shutil.rmtree(staging, ignore_errors=True)


def tag_download(path, info):
    """Write title/artist/album/cover tags after a download (Mornye embeds them too)."""
    if mutagen is None:
        return
    try:
        audio = mutagen.File(path, easy=True)
        if audio is None:
            return
        if audio.tags is None:
            try:
                audio.add_tags()
            except Exception:
                pass
        for key, field in (("title", "title"), ("artist", "artist"), ("album", "album"), ("albumartist", "album_artist"),
                           ("date", "release_date"), ("genre", "genre"), ("isrc", "isrc")):
            value = info.get(field)
            if value:
                try:
                    audio[key] = str(value)
                except Exception:
                    pass
        if info.get("track_number"):
            try:
                audio["tracknumber"] = str(info["track_number"])
            except Exception:
                pass
        audio.save()
    except Exception as e:
        log("[Mornye] tags: %s" % e)
    cover = None
    if info.get("cover_url"):
        try:
            r = requests.get(info["cover_url"], timeout=20)
            if r.ok and r.content[:3] in (b"\xff\xd8\xff", b"\x89PN"):
                cover = r.content
        except Exception:
            cover = None
    if not cover:
        return
    mime = "image/png" if cover[:3] == b"\x89PN" else "image/jpeg"
    try:
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
            from mutagen.id3 import ID3, APIC
            audio = ID3(path)
            audio.delall("APIC")
            audio.add(APIC(encoding=3, mime=mime, type=3, desc="Cover", data=cover))
            audio.save()
        elif lower.endswith((".m4a", ".mp4")):
            from mutagen.mp4 import MP4, MP4Cover
            audio = MP4(path)
            audio["covr"] = [MP4Cover(cover, MP4Cover.FORMAT_PNG if mime == "image/png" else MP4Cover.FORMAT_JPEG)]
            audio.save()
    except Exception as e:
        log("[Mornye] cover tag: %s" % e)


class DownloadQueue:
    """Mornye-style download queue: items with status and progress, two at a time."""

    def __init__(self, manager, output_dir_fn, on_change=None, on_done=None):
        self.manager = manager
        self.output_dir_fn = output_dir_fn
        self.on_change = on_change
        self.on_done = on_done
        self.items = []
        self.lock = threading.Lock()
        self.wake = threading.Condition(self.lock)
        self.running = 0
        self.workers = []
        self.path = os.path.join(manager.root, "downloads.json")
        self.saved_sig = None
        self.save_lock = threading.Lock()
        self._load()
        for _ in range(2):
            t = threading.Thread(target=self._loop, name="mornye-dl", daemon=True)
            t.start()
            self.workers.append(t)

    def _request(self, track, service=None, quality=None):
        m = self.manager
        if service is None:
            source = track.get("provider_id") or ""
            manifest = m.manifest(source) if source else None
            if manifest is not None and m.is_enabled(source) and manifest.has_type("download_provider"):
                service = source
            else:
                service = m.default_service()
        quality = quality or m.state.get("quality") or "LOSSLESS"
        manifest = m.manifest(service) if service else None
        if manifest is not None and manifest.quality_options and manifest.find_quality(quality) is None:
            # Mornye picks quality from the service's own options; a lossy-only service
            # gets its closest option (or its best one) instead of failing on LOSSLESS.
            try:
                quality = manifest.resolve_download_quality(quality, None)
            except ExtError:
                quality = str(manifest.quality_options[0].get("id") or quality).strip()
        return request_from_track(track, service, quality, m.state.get("auto_fallback", True))

    def add(self, track, service=None, quality=None):
        request = self._request(track, service, quality)
        item = {"id": secrets.token_hex(6), "request": request, "track": track, "title": request["track_name"],
                "artist": request["artist_name"], "cover": request["cover_url"], "status": "queued",
                "progress": 0.0, "stage": "", "error": "", "error_type": "", "path": "", "ctx": None, "added": time.time()}
        with self.lock:
            self.items.append(item)
            self.wake.notify()
        self._changed()
        return item

    def cancel(self, item_id):
        with self.lock:
            for item in self.items:
                if item["id"] == item_id:
                    if item["status"] == "queued":
                        item["status"] = "cancelled"
                    elif item["ctx"] is not None:
                        item["ctx"].cancel()
        self._changed()

    def retry(self, item_id):
        with self.lock:
            for item in self.items:
                if item["id"] == item_id and item["status"] in ("failed", "cancelled"):
                    if item.get("track"):
                        item["request"] = self._request(item["track"])
                    item.update({"status": "queued", "progress": 0.0, "error": "", "error_type": ""})
                    self.wake.notify()
        self._changed()

    def remove(self, item_id):
        with self.lock:
            for item in self.items:
                if item["id"] == item_id and item["status"] == "running" and item["ctx"] is not None:
                    item["ctx"].cancel()
            self.items = [i for i in self.items if i["id"] != item_id or i["status"] == "running"]
        self._changed()

    def clear_finished(self):
        with self.lock:
            self.items = [i for i in self.items if i["status"] in ("queued", "running")]
        self._changed()

    def snapshot(self):
        with self.lock:
            return [{k: v for k, v in i.items() if k not in ("ctx", "request", "track")} for i in self.items]

    def _load(self):
        """Restore the list after a restart; unfinished items go back in the queue."""
        try:
            with open(self.path, encoding="utf-8") as f:
                items = json.load(f)
        except Exception:
            return
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict) or not isinstance(item.get("request"), dict):
                continue
            if item.get("status") in ("queued", "running"):
                item.update({"status": "queued", "progress": 0.0, "stage": ""})
            item["ctx"] = None
            self.items.append(item)

    def _save(self):
        # Workers save from their own threads; one writer at a time, newest list wins.
        with self.save_lock:
            with self.lock:
                sig = tuple((i["id"], i["status"]) for i in self.items)
                if sig == self.saved_sig:
                    return
                data = [{k: v for k, v in i.items() if k != "ctx"} for i in self.items[-200:]]
            try:
                tmp = "%s.%s.tmp" % (self.path, threading.get_ident())
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False)
                os.replace(tmp, self.path)
                self.saved_sig = sig
            except Exception as e:
                log("[Mornye] save downloads: %s" % e)

    def _changed(self):
        self._save()
        if self.on_change:
            try:
                self.on_change()
            except Exception:
                pass

    def _loop(self):
        while True:
            with self.lock:
                item = None
                while item is None:
                    item = next((i for i in self.items if i["status"] == "queued"), None)
                    if item is None:
                        self.wake.wait()
                item["status"] = "running"

                def progress(fraction, stage, item=item):
                    item["progress"] = fraction
                    item["stage"] = stage
                    self._changed()

                item["ctx"] = CallContext(item["id"], on_progress=progress)
            self._changed()
            try:
                result = DownloadPlanner(self.manager, self.output_dir_fn()).run(dict(item["request"]), item["ctx"])
            except Exception as e:
                result = _failure("", "download cancelled" if item["ctx"].cancelled else str(e),
                                  "cancelled" if item["ctx"].cancelled else "")
            with self.lock:
                item["ctx"] = None
                if result.get("success"):
                    item.update({"status": "done", "progress": 1.0, "path": result.get("file_path") or ""})
                else:
                    if result.get("error_type") != "cancelled":
                        log("[Mornye] download failed (%s, %s): %s" % (result.get("service") or "-", result.get("error_type") or "-",
                                                                      result.get("error") or ""))
                    item.update({"status": "cancelled" if result.get("error_type") == "cancelled" else "failed",
                                 "error": result.get("error") or "", "error_type": result.get("error_type") or "",
                                 "service": result.get("service") or ""})
            if result.get("success") and not result.get("already_exists"):
                tag_download(result["file_path"], result)
            self._changed()
            if self.on_done:
                try:
                    self.on_done(item, result)
                except Exception as e:
                    log("[Mornye] download callback: %s" % e)
