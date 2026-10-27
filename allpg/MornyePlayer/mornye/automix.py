# SPDX-License-Identifier: LGPL-3.0-only
# Mornye Player for exteraGram. Copyright 2026 BroNik (@BroZYTnikkkk).
# Based on Mornye by zarzet (https://github.com/mornyeapp/Mornye), LGPL-3.0-only.

"""AutoMix: beat detection and the mix plan (port of Mornye automix_analysis.dart)."""

import math
import os
import re
import time
from array import array
from .logs import log
from java import jarray, jbyte, jclass
from org.telegram.messenger import ApplicationLoader, FileLoader
from .common import (
    EFFECT_AUTO,
    EFFECT_CROSSFADE,
    _norm_key,
    mutagen,
)


# ---------------------------------------------------------------------------
# AutoMix analysis (port of Mornye lib/services/automix_analysis.dart, LGPL-3.0)
# ---------------------------------------------------------------------------

ANALYSIS_RATE = 11025
ANALYSIS_HOP = 128
ANALYSIS_WINDOW = 24.0


class BeatGrid:
    """A local beat grid, measured in seconds within the decoded window."""

    def __init__(self, bpm=0.0, phase=0.0, confidence=0.0, first_sound=0.0):
        self.bpm = bpm
        self.phase = phase
        self.confidence = confidence
        self.first_sound = first_sound

    @property
    def reliable(self):
        return self.confidence >= 0.55 and 60 <= self.bpm <= 180

    @property
    def period(self):
        return 60.0 / self.bpm if self.bpm > 0 else 0.0

    def beat_at_or_after(self, seconds):
        if self.period <= 0:
            return seconds
        return self.phase + math.ceil((seconds - self.phase) / self.period) * self.period


def analyze_pcm(samples):
    """Onset -> autocorrelation -> phase detector on mono 11025 Hz samples.

    The approach follows DAFx-09 "Real-time beat-synchronous analysis of
    musical audio", as in Mornye. The tempo sweep is coarse-to-fine to keep the
    pure Python cost bounded on a phone.
    """
    fps = ANALYSIS_RATE / ANALYSIS_HOP
    hop = ANALYSIS_HOP
    frames = len(samples) // hop
    if frames < fps * 6:
        return BeatGrid()
    onset = [0.0] * frames
    energy = [0.0] * frames
    low = mid = 0.0
    prev_low = prev_mid = prev_high = 0.0
    log = math.log
    for frame in range(frames):
        lo_e = mid_e = hi_e = en = 0.0
        base = frame * hop
        for i in range(base, base + hop):
            value = samples[i]
            low += 0.075 * (value - low)
            mid += 0.45 * (value - mid)
            lo_e += low * low
            d = mid - low
            mid_e += d * d
            h = value - mid
            hi_e += h * h
            en += value * value
        energy[frame] = en / hop
        lo = log(1 + lo_e * 100 / hop)
        mi = log(1 + mid_e * 100 / hop)
        hi = log(1 + hi_e * 100 / hop)
        onset[frame] = max(0.0, lo - prev_low) + max(0.0, mi - prev_mid) + 0.5 * max(0.0, hi - prev_high)
        prev_low, prev_mid, prev_high = lo, mi, hi

    peak_energy = max(energy)
    if peak_energy < 0.00001:
        return BeatGrid()
    threshold = max(0.00001, peak_energy * 0.0001)
    first_audible = next((i for i, e in enumerate(energy) if e > threshold), 0)
    first_sound = first_audible / fps

    # Suppress slow volume changes and constant noise before finding the pulse.
    prefix = [0.0] * (frames + 1)
    for i in range(frames):
        prefix[i + 1] = prefix[i] + onset[i]
    total = 0.0
    for i in range(frames):
        b = max(0, i - 8)
        e = min(frames, i + 9)
        v = max(0.0, onset[i] - (prefix[e] - prefix[b]) / (e - b))
        onset[i] = v
        total += v * v
    if total < 0.000001:
        return BeatGrid(first_sound=first_sound)

    # Normalize against nearby onset energy with a global floor.
    power = [0.0] * (frames + 1)
    for i in range(frames):
        power[i + 1] = power[i] + onset[i] * onset[i]
    floor = total / frames * 0.01
    normalized = [0.0] * frames
    for i in range(frames):
        b = max(0, i - 43)
        e = min(frames, i + 44)
        local = (power[e] - power[b]) / (e - b)
        normalized[i] = min(6.0, onset[i] / math.sqrt(max(floor, local)))
    onset = normalized
    last = frames - 1

    def correlation(lag):
        dot = left = right = 0.0
        start = int(math.ceil(lag))
        for i in range(start, frames):
            source = i - lag
            j = int(source)
            fraction = source - j
            k = j + 1 if j + 1 < last else last
            delayed = onset[j] * (1 - fraction) + onset[k] * fraction
            o = onset[i]
            dot += o * delayed
            left += o * o
            right += delayed * delayed
        return dot / math.sqrt(max(0.000000001, left * right))

    def weighted(bpm):
        score = correlation(fps * 60 / bpm)
        return score * (0.96 + 0.04 * math.exp(-(((bpm - 120) / 45) ** 2)))

    best_bpm = 0.0
    best_score = 0.0
    bpm = 60.0
    while bpm <= 180:
        score = weighted(bpm)
        if score > best_score:
            best_score, best_bpm = score, bpm
        bpm += 0.5
    if best_bpm == 0:
        return BeatGrid(first_sound=first_sound)
    coarse = best_bpm
    for step in range(-25, 26):
        candidate = coarse + step * 0.02
        if candidate < 60 or candidate > 180 or step == 0:
            continue
        score = weighted(candidate)
        if score > best_score:
            best_score, best_bpm = score, candidate

    period = fps * 60 / best_bpm
    best_phase = 0.0
    phase_score = 0.0
    phase = 0.0
    while phase < period:
        score = 0.0
        count = 0
        beat = phase
        while beat < frames - 1:
            score += onset[int(round(beat))]
            count += 1
            beat += period
        score /= max(1, count)
        if score > phase_score:
            phase_score, best_phase = score, phase
        phase += 0.5
    hits = beats = 0
    beat = best_phase
    while beat < frames - 2:
        i = int(round(beat))
        peak = max(onset[i], onset[max(0, i - 1)], onset[i + 1])
        if peak >= phase_score * 0.3:
            hits += 1
        beats += 1
        beat += period
    coverage = hits / max(1, beats)
    return BeatGrid(best_bpm, best_phase / fps, min(best_score, coverage), first_sound)


class MixPlan:
    def __init__(self, start, incoming_start, duration, rate, beat_matched, reason=None, assisted=False, beat_period=0.0):
        self.start = start
        self.incoming_start = incoming_start
        self.duration = duration
        self.rate = rate
        self.beat_matched = beat_matched
        self.reason = reason
        self.assisted = assisted
        self.beat_period = beat_period


def create_mix_plan(out_len, in_len, outro=None, intro=None, outro_offset=0.0, manual=0, effect=EFFECT_AUTO, automix=True):
    """Port of AutoMixPlan.create. Durations are in seconds."""
    if out_len < 20 or in_len < 20:
        return None
    maximum = min(60.0, min(out_len / 2, in_len / 2))
    fade = min(max(float(manual) if manual else 5.0, 3.0), maximum)
    start = out_len - fade
    incoming_start = 0.0
    rate = 1.0
    matched = False
    reason = None
    if not automix or effect == EFFECT_CROSSFADE:
        reason = "crossfade"
    elif outro is None or intro is None:
        reason = "analysis unavailable"
    elif not outro.reliable or not intro.reliable:
        reason = "unreliable beats"
    else:
        candidates = sorted(
            (outro.bpm / (intro.bpm * factor) for factor in (0.5, 1.0, 2.0)),
            key=lambda c: abs(c - 1),
        )
        candidate = candidates[0]
        first_beat = intro.beat_at_or_after(intro.first_sound)
        if abs(candidate - 1) > 0.08:
            reason = "incompatible tempo"
        elif first_beat > min(12.0, in_len * 0.1):
            reason = "long intro"
        else:
            rate = candidate
            if not manual:
                fade = min(max(8 * outro.period, 3.0), min(8.0, maximum))
            phase = outro_offset + outro.phase
            start = phase + math.floor((out_len - fade - phase) / outro.period) * outro.period
            incoming_start = first_beat
            matched = True
    assisted = (
        not matched
        and automix
        and effect == EFFECT_AUTO
        and outro is not None
        and intro is not None
        and 60 <= outro.bpm <= 180
        and 60 <= intro.bpm <= 180
        and outro.confidence >= 0.25
        and intro.confidence >= 0.25
    )
    return MixPlan(start, incoming_start, fade, rate, matched, reason, assisted, outro.period if matched else 0.0)


def mix_envelope(elapsed, duration, rate):
    """Equal-power gain ramps; tempo returns gradually after the outgoing song ends."""
    t = min(max(elapsed / duration, 0.0), 1.0) if duration > 0 else 1.0
    recovery = min(max((elapsed - duration) / 8.0, 0.0), 1.0)
    smooth = recovery * recovery * (3 - 2 * recovery)
    return (
        math.cos(t * math.pi / 2),
        math.sin(t * math.pi / 2),
        rate + (1 - rate) * smooth,
        recovery >= 1 or (t >= 1 and rate == 1),
    )


# ---------------------------------------------------------------------------
# Audio file helpers
# ---------------------------------------------------------------------------


def decode_window(path, offset_s, length_s):
    """Decode a short PCM window to mono floats at 11025 Hz.

    Returns (samples, actual_offset_seconds) or (None, 0) on failure.
    """
    MediaExtractor = jclass("android.media.MediaExtractor")
    MediaCodec = jclass("android.media.MediaCodec")
    extractor = MediaExtractor()
    codec = None
    try:
        extractor.setDataSource(path)
        track = -1
        fmt = None
        for i in range(extractor.getTrackCount()):
            f = extractor.getTrackFormat(i)
            mime = f.getString("mime")
            if mime and str(mime).startswith("audio/"):
                track, fmt = i, f
                break
        if track < 0:
            return None, 0.0
        extractor.selectTrack(track)
        mime = str(fmt.getString("mime"))
        sample_rate = fmt.getInteger("sample-rate")
        channels = fmt.getInteger("channel-count")
        encoding = 2
        start_us = int(max(0.0, offset_s) * 1e6)
        end_us = start_us + int(length_s * 1e6)
        extractor.seekTo(start_us, MediaExtractor.SEEK_TO_PREVIOUS_SYNC)
        codec = MediaCodec.createDecoderByType(mime)
        codec.configure(fmt, None, None, 0)
        codec.start()
        info = MediaCodec.BufferInfo()
        out = []
        acc = 0.0
        first_pts = -1
        input_done = False
        deadline = time.time() + 25
        while time.time() < deadline:
            if not input_done:
                in_index = codec.dequeueInputBuffer(10000)
                if in_index >= 0:
                    buf = codec.getInputBuffer(in_index)
                    size = extractor.readSampleData(buf, 0)
                    if size < 0 or extractor.getSampleTime() > end_us:
                        codec.queueInputBuffer(in_index, 0, 0, 0, MediaCodec.BUFFER_FLAG_END_OF_STREAM)
                        input_done = True
                    else:
                        codec.queueInputBuffer(in_index, 0, size, extractor.getSampleTime(), 0)
                        extractor.advance()
            out_index = codec.dequeueOutputBuffer(info, 10000)
            if out_index == MediaCodec.INFO_OUTPUT_FORMAT_CHANGED:
                of = codec.getOutputFormat()
                sample_rate = of.getInteger("sample-rate")
                channels = of.getInteger("channel-count")
                if of.containsKey("pcm-encoding"):
                    encoding = of.getInteger("pcm-encoding")
                continue
            if out_index < 0:
                continue
            if info.size > 0 and info.presentationTimeUs >= start_us - 50000:
                if first_pts < 0:
                    first_pts = info.presentationTimeUs
                buf = codec.getOutputBuffer(out_index)
                buf.position(info.offset)
                chunk = _read_buffer(buf, info.size)
                if encoding == 4:
                    pcm = array("f")
                    pcm.frombytes(chunk)
                    scale = 1.0
                else:
                    pcm = array("h")
                    pcm.frombytes(chunk[: len(chunk) - (len(chunk) % 2)])
                    scale = 1.0 / 32768.0
                frames = len(pcm) // max(1, channels)
                step = sample_rate / ANALYSIS_RATE
                idx = acc
                if channels >= 2:
                    while idx < frames:
                        f = int(idx) * channels
                        out.append((pcm[f] + pcm[f + 1]) * 0.5 * scale)
                        idx += step
                else:
                    while idx < frames:
                        out.append(pcm[int(idx)] * scale)
                        idx += step
                acc = idx - frames
            codec.releaseOutputBuffer(out_index, False)
            if (info.flags & MediaCodec.BUFFER_FLAG_END_OF_STREAM) != 0:
                break
            if len(out) >= int(length_s * ANALYSIS_RATE):
                break
        return out, (first_pts / 1e6 if first_pts >= 0 else offset_s)
    except Exception as e:
        log("[Mornye] decode failed: %s" % e)
        return None, 0.0
    finally:
        try:
            if codec is not None:
                codec.stop()
                codec.release()
        except Exception:
            pass
        try:
            extractor.release()
        except Exception:
            pass


def _read_buffer(byte_buffer, size):
    arr = jarray(jbyte)(size)
    byte_buffer.get(arr)
    try:
        return bytes(arr)
    except Exception:
        return bytes((b & 0xFF) for b in arr)


def audio_quality_label(path):
    """Codec · bitrate · sample rate · channels, like Mornye's quality badge."""
    try:
        MediaExtractor = jclass("android.media.MediaExtractor")
        ex = MediaExtractor()
        ex.setDataSource(path)
        try:
            for i in range(ex.getTrackCount()):
                f = ex.getTrackFormat(i)
                mime = str(f.getString("mime") or "")
                if not mime.startswith("audio/"):
                    continue
                codec = {
                    "audio/mpeg": "MP3", "audio/mp4a-latm": "AAC", "audio/flac": "FLAC",
                    "audio/raw": "WAV", "audio/opus": "Opus", "audio/vorbis": "Vorbis",
                    "audio/alac": "ALAC",
                }.get(mime, mime.split("/")[-1].upper())
                parts = [codec]
                rate = f.getInteger("sample-rate") if f.containsKey("sample-rate") else 0
                ch = f.getInteger("channel-count") if f.containsKey("channel-count") else 0
                dur = f.getLong("durationUs") / 1e6 if f.containsKey("durationUs") else 0
                if f.containsKey("bitrate"):
                    parts.append("%d kbps" % (f.getInteger("bitrate") // 1000))
                elif dur > 0 and codec not in ("FLAC", "WAV", "ALAC"):
                    parts.append("~%d kbps" % (os.path.getsize(path) * 8 / dur / 1000))
                if f.containsKey("bits-per-sample"):
                    parts.append("%d-bit" % f.getInteger("bits-per-sample"))
                if rate:
                    parts.append(("%.1f kHz" % (rate / 1000.0)).replace(".0 ", " "))
                if ch:
                    parts.append({1: "моно", 2: "стерео"}.get(ch, "%d кан." % ch))
                return " · ".join(parts)
        finally:
            ex.release()
    except Exception:
        pass
    return None


def read_tags(path):
    tags = {"title": None, "artist": None, "album": None, "duration": 0, "track_gain": None, "album_gain": None,
            "albumartist": None, "composer": None, "genre": None, "tracknumber": None, "date": None}
    if mutagen is not None:
        try:
            f = mutagen.File(path, easy=True)
            if f is not None:
                def first(key):
                    v = f.get(key) if hasattr(f, "get") else None
                    return str(v[0]) if v else None
                tags["title"] = first("title")
                tags["artist"] = first("artist")
                tags["album"] = first("album")
                for key in ("albumartist", "composer", "genre", "tracknumber", "date"):
                    tags[key] = first(key)
                if getattr(f, "info", None) is not None:
                    tags["duration"] = int(getattr(f.info, "length", 0) or 0)
            raw = mutagen.File(path)
            if raw is not None and raw.tags is not None:
                for key in list(raw.tags.keys()):
                    name = str(key).lower()
                    if "replaygain_track_gain" in name or "replaygain_album_gain" in name:
                        m = re.search(r"-?\d+(\.\d+)?", _first_text(raw.tags[key]))
                        if m:
                            tags["track_gain" if "track" in name else "album_gain"] = float(m.group(0))
        except Exception:
            pass
    if not tags["title"] or not tags["duration"]:
        try:
            MMR = jclass("android.media.MediaMetadataRetriever")
            r = MMR()
            r.setDataSource(path)
            tags["title"] = tags["title"] or r.extractMetadata(MMR.METADATA_KEY_TITLE)
            tags["artist"] = tags["artist"] or r.extractMetadata(MMR.METADATA_KEY_ARTIST)
            tags["album"] = tags["album"] or r.extractMetadata(MMR.METADATA_KEY_ALBUM)
            d = r.extractMetadata(MMR.METADATA_KEY_DURATION)
            if d and not tags["duration"]:
                tags["duration"] = int(int(str(d)) / 1000)
            r.release()
        except Exception:
            pass
    if not tags["title"]:
        tags["title"] = os.path.splitext(os.path.basename(path))[0]
    tags["title"] = str(tags["title"]) if tags["title"] else None
    tags["artist"] = str(tags["artist"]) if tags["artist"] else None
    tags["album"] = str(tags["album"]) if tags["album"] else None
    return tags


def _first_text(value):
    if hasattr(value, "text"):
        value = value.text
    if isinstance(value, (list, tuple)):
        value = value[0] if value else ""
    if isinstance(value, bytes):
        value = value.decode("utf-8", "ignore")
    return str(value)


def replaygain_volume(track_gain, album_gain, preamp_db=0.0, prefer_album=False):
    """Mornye rule: normalization only attenuates and cannot clip."""
    gain = (album_gain if album_gain is not None else track_gain) if prefer_album else (
        track_gain if track_gain is not None else album_gain)
    if gain is None:
        return 1.0
    return min(1.0, max(0.0, 10 ** ((gain + preamp_db) / 20.0)))


def java_class(name):
    """java.lang.Class for reflection; find_class returns a Python wrapper on exteraGram 13."""
    loader = ApplicationLoader.applicationContext.getClassLoader()
    return jclass("java.lang.Class").forName(name, False, loader)


def message_file_path(msg):
    """Local file for a MessageObject, or None if it is not on the device."""
    try:
        attach = msg.messageOwner.attachPath
        if attach and os.path.exists(str(attach)):
            return str(attach)
        f = FileLoader.getInstance(msg.currentAccount).getPathToMessage(msg.messageOwner)
        if f is not None and f.exists():
            return str(f.getAbsolutePath())
    except Exception:
        pass
    return None


def message_meta(msg):
    title = artist = None
    try:
        title = msg.getMusicTitle()
        artist = msg.getMusicAuthor()
    except Exception:
        pass
    return (str(title) if title else "Без названия"), (str(artist) if artist else "Неизвестный исполнитель")


def track_key(title, artist):
    return "%s|%s" % (_norm_key(artist), _norm_key(title))
