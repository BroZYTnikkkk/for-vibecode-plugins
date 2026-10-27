# SPDX-License-Identifier: LGPL-3.0-only
# Mornye Player for exteraGram. Copyright 2026 BroNik (@BroZYTnikkkk).
# Based on Mornye by zarzet (https://github.com/mornyeapp/Mornye), LGPL-3.0-only.

"""Audio effects, player hooks and the playback engine (crossfade, AutoMix, sleep timer)."""

import math
import time
from base_plugin import MethodHook
from client_utils import get_media_controller, run_on_queue
from hook_utils import get_private_field, set_private_field
from ui.bulletin import BulletinHelper
from android.os import Handler, Looper
from android_utils import OnLongClickListener, R, log, run_on_ui_thread
from java import jclass, jfloat
from org.telegram.messenger import SharedConfig
from org.telegram.ui.ActionBar import Theme
from .common import (
    EFFECT_AUTO,
    EFFECT_CROSSFADE,
    EFFECT_ECHO,
    EFFECT_MUFFLED,
    EFFECT_PITCH,
    EQ_CENTERS,
    EQ_PRESETS,
    MIX_AUTOMIX,
    MIX_CROSSFADE,
    MIX_DURATIONS,
    MIX_OFF,
    PREAMP_VALUES,
    SKIP_FADES,
    STRENGTH_VALUES,
    _identity,
)
from .automix import (
    ANALYSIS_WINDOW,
    MixPlan,
    analyze_pcm,
    create_mix_plan,
    decode_window,
    message_file_path,
    message_meta,
    mix_envelope,
    read_tags,
    replaygain_volume,
)


# ---------------------------------------------------------------------------
# Equalizer and effects bound to one audio session
# ---------------------------------------------------------------------------


def eq_gain_at(gains, hz):
    """Log-frequency interpolation across the 10 Mornye bands."""
    if hz <= EQ_CENTERS[0]:
        return gains[0]
    for i in range(1, len(EQ_CENTERS)):
        if hz <= EQ_CENTERS[i]:
            fraction = math.log(hz / EQ_CENTERS[i - 1]) / math.log(EQ_CENTERS[i] / EQ_CENTERS[i - 1])
            return gains[i - 1] + (gains[i] - gains[i - 1]) * fraction
    return gains[-1]


def eq_effective(gains, bass, treble):
    """Tone controls merge into the graphic curve (Mornye EqualizerSettings)."""
    return [
        max(-24.0, min(24.0, gains[i] + bass / (1 + (EQ_CENTERS[i] / 180.0) ** 2) + treble / (1 + (5000.0 / EQ_CENTERS[i]) ** 2)))
        for i in range(len(gains))
    ]


class SessionFx:
    def __init__(self, session):
        self.session = session
        self.eq = self.bass = self.virt = self.loud = self.reverb = None
        self.base_levels = None
        try:
            self.eq = jclass("android.media.audiofx.Equalizer")(1000, session)
        except Exception as e:
            log("[Mornye] Equalizer unavailable: %s" % e)
        try:
            self.bass = jclass("android.media.audiofx.BassBoost")(1000, session)
        except Exception:
            pass
        try:
            self.virt = jclass("android.media.audiofx.Virtualizer")(1000, session)
        except Exception:
            pass
        try:
            self.loud = jclass("android.media.audiofx.LoudnessEnhancer")(session)
        except Exception:
            pass

    def band_centers(self):
        if self.eq is None:
            return []
        return [self.eq.getCenterFreq(b) / 1000.0 for b in range(self.eq.getNumberOfBands())]

    def apply(self, cfg):
        eq_on = cfg["eq_enabled"]
        if self.eq is not None:
            try:
                lo, hi = self.eq.getBandLevelRange()
                levels = []
                for hz in self.band_centers():
                    db = eq_gain_at(cfg["eq_gains"], max(20.0, hz)) if eq_on else 0.0
                    levels.append(int(max(lo, min(hi, db * 100))))
                self.base_levels = levels
                for b, level in enumerate(levels):
                    self.eq.setBandLevel(b, level)
                self.eq.setEnabled(bool(eq_on))
            except Exception as e:
                log("[Mornye] EQ apply failed: %s" % e)
        if self.bass is not None:
            try:
                self.bass.setStrength(int(cfg["bass_strength"]))
                self.bass.setEnabled(cfg["bass_strength"] > 0)
            except Exception:
                pass
        if self.virt is not None:
            try:
                self.virt.setStrength(int(cfg["virt_strength"]))
                self.virt.setEnabled(cfg["virt_strength"] > 0)
            except Exception:
                pass
        if self.loud is not None:
            try:
                boost = max(0, int(cfg["loudness_mb"]))
                self.loud.setTargetGain(boost)
                self.loud.setEnabled(boost > 0)
            except Exception:
                pass

    def shape_outgoing(self, cut_low, cut_high):
        """AutoMix FX on the outgoing deck: 0..1 amounts of bass/treble cut."""
        if self.eq is None:
            return
        try:
            lo, hi = self.eq.getBandLevelRange()
            base = self.base_levels or [0] * self.eq.getNumberOfBands()
            for b, hz in enumerate(self.band_centers()):
                level = base[b] if b < len(base) else 0
                if cut_low > 0 and hz < 260:
                    level = level + (lo - level) * cut_low
                if cut_high > 0 and hz > 1200:
                    level = level + (lo - level) * cut_high
                self.eq.setBandLevel(b, int(max(lo, min(hi, level))))
            if cut_low > 0 or cut_high > 0:
                self.eq.setEnabled(True)
        except Exception:
            pass

    def set_echo(self, amount):
        try:
            if self.reverb is None and amount > 0:
                PresetReverb = jclass("android.media.audiofx.PresetReverb")
                self.reverb = PresetReverb(0, self.session)
                self.reverb.setPreset(PresetReverb.PRESET_LARGEHALL)
            if self.reverb is not None:
                self.reverb.setEnabled(amount > 0.05)
        except Exception:
            self.reverb = None

    def release(self):
        for fx in (self.eq, self.bass, self.virt, self.loud, self.reverb):
            try:
                if fx is not None:
                    fx.release()
            except Exception:
                pass
        self.eq = self.bass = self.virt = self.loud = self.reverb = None


# ---------------------------------------------------------------------------
# Hooks
# ---------------------------------------------------------------------------


class VolumeHook(MethodHook):
    """Multiplies every VideoPlayer.setVolume by the plugin's per-player gain."""

    def __init__(self, plugin):
        self.plugin = plugin

    def before_hooked_method(self, param):
        try:
            gain = self.plugin.gains.get(_identity(param.thisObject))
            if gain is None:
                return
            value = param.args[0]
            value = float(value.floatValue()) if hasattr(value, "floatValue") else float(value)
            param.args[0] = jfloat(max(0.0, min(1.0, value * gain)))
        except Exception:
            pass


class PlayMessageHook(MethodHook):
    def __init__(self, plugin):
        self.plugin = plugin

    def after_hooked_method(self, param):
        try:
            self.plugin.engine.on_track_started()
        except Exception as e:
            log("[Mornye] track start: %s" % e)


class SkipHook(MethodHook):
    def __init__(self, plugin, previous=False):
        self.plugin = plugin
        self.previous = previous

    def before_hooked_method(self, param):
        try:
            self.plugin.engine.on_manual_skip(self.previous)
        except Exception as e:
            log("[Mornye] skip: %s" % e)

    def after_hooked_method(self, param):
        engine = self.plugin.engine
        if not engine.transition_running:
            engine.pending_incoming = False
            engine.ensure_ticking()


class PlayerAlertHook(MethodHook):
    def __init__(self, plugin):
        self.plugin = plugin

    def after_hooked_method(self, param):
        try:
            button = get_private_field(param.thisObject, "optionsButton")
            if button is None:
                return
            plugin = self.plugin

            def on_long(view):
                plugin.open_app()
                return True

            button.setOnLongClickListener(OnLongClickListener(on_long))
        except Exception as e:
            log("[Mornye] player alert: %s" % e)


# ---------------------------------------------------------------------------
# Playback engine: crossfade, AutoMix, normalization, effects, stats
# ---------------------------------------------------------------------------


class Fade:
    def __init__(self, old_player, old_fx, new_player, plan, out_gain, effect, pitch_semitones):
        self.old = old_player
        self.old_key = _identity(old_player)
        self.old_fx = old_fx
        self.new = new_player
        self.new_key = _identity(new_player) if new_player is not None else 0
        self.plan = plan
        self.out_gain = out_gain
        self.started = time.time()
        self.effect = effect
        self.pitch = pitch_semitones
        self.aligned = not plan.beat_matched
        self.old_released = False
        self.done = False
        self.manual = False


class Engine:
    def __init__(self, plugin):
        self.plugin = plugin
        self.gains = plugin.gains
        self.norm = {}
        self.handler = Handler(Looper.getMainLooper())
        self.tick_runnable = R(self._tick)
        self.ticking = False
        self.in_tick = False
        self.current_key = 0
        self.plan = None
        self.plan_key = 0
        self.plan_next = None
        self.fades = []
        self.session_fx = {}
        self.transition_running = False
        self.pending_incoming = False
        self.listen_started = None
        self.listen_seconds = 0.0
        self.listen_counted = False
        self.listen_meta = None
        self.autoplay_done_for = 0
        self.sleep_at = 0.0
        self.sleep_end_of_track = False
        self.analysis_cache = {}

    # -- helpers -----------------------------------------------------------

    def mc(self):
        return get_media_controller()

    def main_player(self):
        try:
            return get_private_field(self.mc(), "audioPlayer")
        except Exception:
            return None

    def user_paused(self):
        # isMessagePaused() is also true while the next song downloads.
        try:
            return bool(get_private_field(self.mc(), "isPaused"))
        except Exception:
            return self.mc().isMessagePaused()

    def exo(self, player):
        try:
            return get_private_field(player, "player")
        except Exception:
            return None

    def cfg(self):
        p = self.plugin
        preset = p.get_setting("eq_preset", 0)
        if preset < len(EQ_PRESETS):
            gains = list(EQ_PRESETS[preset][1])
        else:
            gains = p.custom_eq()
        bass_db = (p.get_setting("eq_bass", 4) - 4) * 2
        treble_db = (p.get_setting("eq_treble", 4) - 4) * 2
        effective = eq_effective(gains, bass_db, treble_db)
        headroom = max(0.0, min(24.0, max(effective))) if p.get_setting("eq_enabled", False) else 0.0
        return {
            "eq_enabled": p.get_setting("eq_enabled", False),
            "eq_gains": effective,
            "headroom": headroom,
            "bass_strength": STRENGTH_VALUES[p.get_setting("bass_boost", 0)],
            "virt_strength": STRENGTH_VALUES[p.get_setting("virtualizer", 0)],
            "loudness_mb": p.get_setting("loudness_boost", 0) * 300,
        }

    def base_gain(self, key):
        """Normalization and EQ headroom for one player."""
        g = self.norm.get(key, 1.0)
        headroom = self.cfg()["headroom"]
        if headroom > 0:
            g *= 10 ** (-headroom / 20.0)
        return g

    def _schedule(self, delay):
        # One pending tick at most: the same Runnable is never queued twice.
        self.handler.removeCallbacks(self.tick_runnable)
        self.handler.postDelayed(self.tick_runnable, int(delay))
        self.ticking = True

    def ensure_ticking(self, delay=0):
        if not self.ticking and not self.in_tick:
            self._schedule(delay)

    def stop(self):
        self.handler.removeCallbacks(self.tick_runnable)
        self.ticking = False
        for fade in list(self.fades):
            self._finish_fade(fade, release=True)
        self.fades = []
        for fx in self.session_fx.values():
            fx.release()
        self.session_fx.clear()
        self.gains.clear()
        try:
            self.mc().setPlayerVolume()
        except Exception:
            pass

    def reapply_fx(self):
        cfg = self.cfg()
        for fx in self.session_fx.values():
            fx.apply(cfg)
        player = self.main_player()
        if player is not None:
            key = _identity(player)
            if not any(f.new_key == key and not f.done for f in self.fades):
                self.gains[key] = self.base_gain(key)
            try:
                self.mc().setPlayerVolume()
            except Exception:
                pass

    # -- track lifecycle --------------------------------------------------

    def on_track_started(self):
        player = self.main_player()
        mc = self.mc()
        msg = mc.getPlayingMessageObject()
        if player is None or msg is None or not msg.isMusic():
            return
        key = _identity(player)
        if key == self.current_key:
            self.ensure_ticking()  # resume of the same song
            return
        self._commit_listen()
        self.current_key = key
        self.plan = None
        self.plan_key = 0
        if self.pending_incoming:
            # Incoming deck of a fade: silent until the envelope takes over.
            self.gains[key] = 0.0
            try:
                player.setVolume(0.0)
            except Exception:
                pass
            for fade in self.fades:
                if fade.manual and fade.new is None and not fade.done:
                    fade.new = player
                    fade.new_key = key
        else:
            self.gains[key] = self.base_gain(key)
        exo = self.exo(player)
        if exo is not None and self.plugin.get_setting("skip_silence", False):
            try:
                exo.setSkipSilenceEnabled(True)
            except Exception:
                pass
        title, artist = message_meta(msg)
        self.listen_meta = (title, artist, msg.getDuration())
        self.listen_started = time.time()
        self.listen_seconds = 0.0
        self.listen_counted = False
        path = message_file_path(msg)
        if path and self.plugin.get_setting("normalize", True):
            run_on_queue(lambda: self._load_gain(key, path))
        run_on_queue(lambda: self.plugin.library.push_history(title, artist, path))
        self.ensure_ticking(150)

    def _load_gain(self, key, path):
        tags = read_tags(path)
        preamp = PREAMP_VALUES[self.plugin.get_setting("rg_preamp", 4)]
        vol = replaygain_volume(tags["track_gain"], tags["album_gain"], preamp, self.plugin.get_setting("rg_album", False))
        self.norm[key] = vol

        def apply():
            if key in self.gains and not any(f.new_key == key and not f.done for f in self.fades):
                self.gains[key] = self.base_gain(key)
                try:
                    self.mc().setPlayerVolume()
                except Exception:
                    pass

        run_on_ui_thread(apply)

    def _commit_listen(self):
        if self.listen_meta is None:
            return
        title, artist, duration = self.listen_meta
        seconds = self.listen_seconds
        skipped = seconds < 30 and duration > 60
        self.plugin.library.record_listen(title, artist, seconds, counted=self.listen_counted, skipped=skipped)
        self.listen_meta = None

    # -- next track -------------------------------------------------------

    def peek_next(self):
        mc = self.mc()
        if SharedConfig.repeatMode == 2:
            return None
        try:
            lst = get_private_field(mc, "shuffledPlaylist") if SharedConfig.shuffleMusic else mc.getPlaylist()
            num = mc.getPlayingMessageObjectNum()
        except Exception:
            return None
        if lst is None:
            return None
        size = lst.size()
        if size < 2 or num < 0 or num >= size:
            return None
        nxt = num + (1 if SharedConfig.playOrderReversed else -1)
        if nxt < 0 or nxt >= size:
            if SharedConfig.repeatMode != 1:
                return None
            nxt = 0 if nxt >= size else size - 1
        msg = lst.get(nxt)
        if msg is None or not msg.isMusic():
            return None
        return msg

    def is_last_in_queue(self):
        mc = self.mc()
        try:
            lst = mc.getPlaylist()
            num = mc.getPlayingMessageObjectNum()
            size = lst.size()
        except Exception:
            return False
        if SharedConfig.repeatMode != 0 or SharedConfig.shuffleMusic:
            return False
        return (num == 0 and not SharedConfig.playOrderReversed) or (num == size - 1 and SharedConfig.playOrderReversed)

    # -- planning ---------------------------------------------------------

    def mix_mode(self):
        return self.plugin.get_setting("mix_mode", MIX_CROSSFADE)

    def _request_plan(self, player, msg, duration_s):
        key = _identity(player)
        nxt = self.peek_next()
        if nxt is None:
            return  # checked again on the next tick: autoplay may add songs
        mode = self.mix_mode()
        manual = MIX_DURATIONS[self.plugin.get_setting("mix_duration", 0)]
        effect = self.plugin.get_setting("automix_effect", EFFECT_AUTO)
        next_len = float(nxt.getDuration() or 0)
        # A plain crossfade plan is ready immediately; AutoMix refines it.
        base = create_mix_plan(duration_s, next_len, manual=manual, effect=effect, automix=False)
        if base is None:
            return
        self.plan, self.plan_key, self.plan_next = base, key, nxt.getId()
        if mode != MIX_AUTOMIX or effect == EFFECT_CROSSFADE:
            return
        cur_path = message_file_path(msg)
        next_path = message_file_path(nxt)
        if not cur_path or not next_path:
            return
        next_id = nxt.getId()

        def work():
            try:
                lookback = ANALYSIS_WINDOW if not manual else manual + ANALYSIS_WINDOW / 2
                outro_key = (cur_path, "outro", manual)
                intro_key = (next_path, "intro")
                if outro_key not in self.analysis_cache:
                    samples, offset = decode_window(cur_path, max(0.0, duration_s - lookback), ANALYSIS_WINDOW)
                    self.analysis_cache[outro_key] = (analyze_pcm(samples) if samples else None, offset)
                if intro_key not in self.analysis_cache:
                    samples, _ = decode_window(next_path, 0.0, ANALYSIS_WINDOW)
                    self.analysis_cache[intro_key] = (analyze_pcm(samples) if samples else None, 0.0)
                if len(self.analysis_cache) > 40:
                    self.analysis_cache.pop(next(iter(self.analysis_cache)))
                outro, offset = self.analysis_cache[outro_key]
                intro, _ = self.analysis_cache[intro_key]
                plan = create_mix_plan(duration_s, next_len, outro, intro, offset, manual, effect, automix=True)

                def adopt():
                    if plan is not None and self.plan_key == key and self.plan_next == next_id and not self.transition_running:
                        player_now = self.main_player()
                        pos = player_now.getCurrentPosition() / 1000.0 if player_now is not None else 0
                        if plan.start > pos + 0.3:
                            self.plan = plan
                            log("[Mornye] AutoMix plan: %s, bpm %.1f/%.1f, rate %.3f, fade %.1fs (%s)" % (
                                "beat matched" if plan.beat_matched else "crossfade",
                                outro.bpm if outro else 0, intro.bpm if intro else 0,
                                plan.rate, plan.duration, plan.reason or "ok"))

                run_on_ui_thread(adopt)
            except Exception as e:
                log("[Mornye] AutoMix analysis failed: %s" % e)

        run_on_queue(work)

    # -- transitions ------------------------------------------------------

    def _steal_and_advance(self, advance):
        """Detach the live player from MediaController, then let it move on.

        MediaController releases audioPlayer inside playMessage(); clearing
        the field first keeps the old deck alive for our own fade.
        """
        mc = self.mc()
        old = self.main_player()
        if old is None:
            advance()
            return None, None
        try:
            old.allowMultipleInstances = True
        except Exception:
            pass
        self._detach_reporter(mc, mc.getPlayingMessageObject())
        set_private_field(mc, "audioPlayer", None)
        self.transition_running = True
        self.pending_incoming = True
        try:
            advance()
        finally:
            self.pending_incoming = False
            self.transition_running = False
        new = self.main_player()
        if new is not None and _identity(new) == _identity(old):
            new = None
        return old, new

    def _detach_reporter(self, mc, msg):
        """Do what cleanupPlayer() would do for the deck we are taking over."""
        try:
            reporter = get_private_field(mc, "reporter")
            if reporter is not None:
                reporter.destroy()
                set_private_field(mc, "reporter", None)
        except Exception:
            pass
        try:
            if msg is not None:
                Theme.unrefAudioVisualizeDrawable(msg)
        except Exception:
            pass

    def start_transition(self, plan):
        mc = self.mc()
        old_key = _identity(self.main_player())
        out_gain = self.gains.get(old_key, self.base_gain(old_key))
        effect = self.plugin.get_setting("automix_effect", EFFECT_AUTO) if self.mix_mode() == MIX_AUTOMIX else EFFECT_CROSSFADE
        old, new = self._steal_and_advance(mc.playNextMessage)
        if old is None:
            return
        old_fx = self.session_fx.get(self._session_of(old))
        fade = Fade(old, old_fx, new, plan, out_gain, effect, self.plugin.get_setting("automix_pitch", 2) - 6 if effect == EFFECT_PITCH else 0)
        if new is not None:
            self.gains[fade.new_key] = 0.0
            if plan.incoming_start > 0.05:
                try:
                    new.seekTo(int(plan.incoming_start * 1000))
                except Exception:
                    pass
            if abs(plan.rate - 1) > 0.0005:
                self._set_rate(new, plan.rate)
        self.fades.append(fade)
        self.plan = None
        self.ensure_ticking()

    def on_manual_skip(self, previous=False):
        if self.transition_running:
            return
        seconds = SKIP_FADES[self.plugin.get_setting("skip_fade", 0)]
        mc = self.mc()
        player = self.main_player()
        msg = mc.getPlayingMessageObject()
        if seconds <= 0 or player is None or msg is None or not msg.isMusic() or self.user_paused():
            return
        if mc.getPlaylist().isEmpty():
            return
        if previous and msg.audioProgressSec > 10:
            return  # "previous" only rewinds the current song here
        # Let the original call run, but fade the outgoing deck ourselves.
        key = _identity(player)
        out_gain = self.gains.get(key, self.base_gain(key))
        old_fx = self.session_fx.get(self._session_of(player))
        try:
            player.allowMultipleInstances = True
        except Exception:
            pass
        self._detach_reporter(mc, msg)
        set_private_field(mc, "audioPlayer", None)
        fade = Fade(player, old_fx, None, MixPlan(0, 0, seconds, 1.0, False), out_gain, EFFECT_CROSSFADE, 0)
        fade.manual = True
        self.fades.append(fade)
        self.pending_incoming = True

    def _set_rate(self, player, rate):
        exo = self.exo(player)
        if exo is None:
            return
        try:
            user_speed = float(self.mc().getPlaybackSpeed(True))
        except Exception:
            user_speed = 1.0
        try:
            params = exo.getPlaybackParameters()
            PP = jclass(params.getClass().getName())
            exo.setPlaybackParameters(PP(float(user_speed * rate), float(params.pitch)))
        except Exception:
            try:
                player.setPlaybackSpeed(float(user_speed * rate))
            except Exception:
                pass

    def _set_pitch(self, player, semitones):
        exo = self.exo(player)
        if exo is None:
            return
        try:
            params = exo.getPlaybackParameters()
            PP = jclass(params.getClass().getName())
            exo.setPlaybackParameters(PP(float(params.speed), float(2 ** (semitones / 12.0))))
        except Exception:
            pass

    def _finish_fade(self, fade, release=True):
        if not fade.old_released and release:
            fade.old_released = True
            self.gains.pop(fade.old_key, None)
            self.norm.pop(fade.old_key, None)
            session = self._session_of(fade.old)
            try:
                fade.old.releasePlayer(True)
            except Exception:
                pass
            fx = self.session_fx.pop(session, None)
            if fx is not None:
                fx.release()
        fade.done = True

    def _session_of(self, player):
        exo = self.exo(player)
        if exo is None:
            return 0
        try:
            return int(exo.getAudioSessionId())
        except Exception:
            return 0

    def _update_fade(self, fade):
        mc = self.mc()
        elapsed = time.time() - fade.started
        plan = fade.plan
        out_level, in_level, rate, complete = mix_envelope(elapsed, plan.duration, plan.rate)
        if self.user_paused() and not fade.old_released:
            try:
                fade.old.pause()
            except Exception:
                pass
            self._finish_fade(fade)
            if fade.new is not None:
                self.gains[fade.new_key] = self.base_gain(fade.new_key)
            return
        current = self.main_player()
        if fade.new is not None and (current is None or _identity(current) != fade.new_key):
            # The user switched tracks again; drop the incoming envelope.
            self.gains.pop(fade.new_key, None)
            fade.new = None
        if not fade.old_released:
            self.gains[fade.old_key] = fade.out_gain * out_level
            try:
                fade.old.setVolume(1.0)
            except Exception:
                pass
            if fade.old_fx is not None and elapsed < plan.duration:
                t = min(1.0, elapsed / max(0.1, plan.duration))
                wet = t * t * (3 - 2 * t)
                if fade.effect == EFFECT_MUFFLED:
                    fade.old_fx.shape_outgoing(0.0, wet)
                elif plan.assisted:
                    fade.old_fx.shape_outgoing(wet, 0.0)
                elif fade.effect == EFFECT_ECHO:
                    fade.old_fx.set_echo(wet)
            if fade.effect == EFFECT_PITCH and fade.pitch:
                t = min(1.0, elapsed / max(0.1, plan.duration))
                self._set_pitch(fade.old, fade.pitch * t)
            if elapsed >= plan.duration:
                self._finish_fade(fade)
        if fade.new is not None:
            self.gains[fade.new_key] = self.base_gain(fade.new_key) * (in_level if elapsed < plan.duration else 1.0)
            try:
                mc.setPlayerVolume()
            except Exception:
                pass
            if plan.beat_matched and not fade.aligned and elapsed >= 0.35 and not fade.old_released:
                fade.aligned = True
                try:
                    out_pos = fade.old.getCurrentPosition() / 1000.0
                    target = plan.incoming_start + (out_pos - plan.start) * plan.rate
                    actual = fade.new.getCurrentPosition() / 1000.0
                    if target > 0 and abs(actual - target) > 0.025:
                        fade.new.seekTo(int(target * 1000))
                except Exception:
                    pass
            if abs(plan.rate - 1) > 0.0005:
                self._set_rate(fade.new, rate)
        if complete or (fade.new is None and fade.old_released):
            fade.done = True

    def _tick(self):
        self.ticking = False
        self.in_tick = True
        try:
            interval = self._tick_body()
        except Exception as e:
            log("[Mornye] tick: %s" % e)
            interval = 1000
        finally:
            self.in_tick = False
        if interval:
            self._schedule(interval)

    def _tick_body(self):
        mc = self.mc()
        for fade in list(self.fades):
            self._update_fade(fade)
        self.fades = [f for f in self.fades if not f.done]
        player = self.main_player()
        msg = mc.getPlayingMessageObject()
        if player is None or msg is None or not msg.isMusic():
            return 40 if self.fades else (1000 if self.sleep_at else 0)
        session = self._session_of(player)
        if session and session not in self.session_fx:
            fx = SessionFx(session)
            fx.apply(self.cfg())
            self.session_fx[session] = fx
            def ctl(e):
                try:
                    return "on" if e.getEnabled() else ("off" if e.hasControl() else "no-control")
                except Exception:
                    return "none"
            log("[Mornye] audio session %d: eq=%s bass=%s virt=%s loud=%s" % (
                session, ctl(fx.eq), ctl(fx.bass), ctl(fx.virt), ctl(fx.loud)))
        paused = self.user_paused()
        now = time.time()
        if self.listen_started is not None:
            if not paused:
                self.listen_seconds += min(2.0, now - self.listen_started)
            self.listen_started = now
            if not self.listen_counted and self.listen_seconds >= 30:
                self.listen_counted = True
        if self._check_sleep(player, paused):
            return 40
        if paused:
            # Resuming goes through playMessage(), which restarts the loop.
            return 40 if self.fades else 0
        pos = player.getCurrentPosition() / 1000.0
        dur = player.getDuration() / 1000.0
        key = _identity(player)
        if self.gains.get(key) == 0.0 and not self.pending_incoming and \
                not any(f.new_key == key and not f.done for f in self.fades):
            # A deck left muted by an interrupted fade (skip during a fade, queue change).
            self.gains[key] = self.base_gain(key)
            try:
                self.mc().setPlayerVolume()
            except Exception:
                pass
        if dur <= 0:
            return 40 if self.fades else 300
        mode = self.mix_mode()
        remaining = dur - pos
        if self.plugin.get_setting("autoplay", True) and remaining < 40 and self.autoplay_done_for != key:
            self.autoplay_done_for = key
            if msg.getId() < 0 and self.is_last_in_queue():
                self.plugin.library.autoplay_extend(msg)
        if mode != MIX_OFF and not self.fades:
            if self.plan_key != key and remaining < 45:
                self._request_plan(player, msg, dur)
            plan = self.plan if self.plan_key == key else None
            if plan is not None and remaining > 0.5:
                until = plan.start - pos
                if until <= 0.02:
                    nxt = self.peek_next()
                    if nxt is not None and nxt.getId() == self.plan_next:
                        self.start_transition(plan)
                    else:
                        self.plan = None  # the queue changed after planning
                    return 40
                if until < 0.6:
                    return max(10, int(until * 1000))
        if self.fades:
            return 40
        return 250 if mode != MIX_OFF and remaining < 60 else 500

    # -- sleep timer ------------------------------------------------------

    def set_sleep(self, minutes, end_of_track=False):
        self.sleep_at = time.time() + minutes * 60 if minutes else 0.0
        self.sleep_end_of_track = end_of_track
        if minutes or end_of_track:
            self.ensure_ticking()

    def _check_sleep(self, player, paused):
        if not self.sleep_at and not self.sleep_end_of_track:
            return False
        if paused:
            if self.sleep_at and time.time() > self.sleep_at:
                self.sleep_at = 0.0  # it ran out while the music was paused
            return False
        key = _identity(player)
        if self.sleep_end_of_track:
            remaining = (player.getDuration() - player.getCurrentPosition()) / 1000.0
            if 0 < remaining < 1.0:
                self._sleep_pause(key)
                return True
            return False
        left = self.sleep_at - time.time()
        if left > 8:
            return False
        if left <= 0:
            self._sleep_pause(key)
            return True
        self.gains[key] = self.base_gain(key) * max(0.0, left / 8.0)
        try:
            self.mc().setPlayerVolume()
        except Exception:
            pass
        return True

    def _sleep_pause(self, key):
        mc = self.mc()
        self.sleep_at = 0.0
        self.sleep_end_of_track = False
        try:
            mc.pauseMessage(mc.getPlayingMessageObject())
        except Exception:
            pass
        self.gains[key] = self.base_gain(key)
        BulletinHelper.show_info("Mornye: таймер сна остановил музыку")
