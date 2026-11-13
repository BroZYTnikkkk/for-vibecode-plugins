# Sculpt Player for exteraGram. Copyright 2026 BroNik (@BroZYTnikkkk).

import time

from base_plugin import MethodHook
from java import jclass
from java.lang import Boolean as JBoolean, Float as JFloat, Integer as JInteger

from .i18n import language, tr
from .common import CHECKS, ID_OPEN_SETTINGS, RHYTHM_TAP, _dp, _log
from . import link_stream
from .music import local_path


class _Hook(MethodHook):
    def __init__(self, plugin, name):
        self.plugin = plugin
        self.name = name

    def fail(self, exc):
        self.plugin.report(self.name, exc)


class ConstructorHook(_Hook):
    def after_hooked_method(self, param):
        try:
            self.plugin.open_player(param.thisObject, param.args[0])
        except Exception as e:
            self.fail(e)


class LayoutHook(_Hook):
    """PlayerLayout.computeGeometry / onMeasure / onLayout, after the original, portrait only."""

    def __init__(self, plugin, name, action):
        super().__init__(plugin, name)
        self.action = action

    def after_hooked_method(self, param):
        try:
            player = self.plugin.player_for(param.thisObject)
            if player is not None:
                self.action(player, param)
        except Exception as e:
            self.fail(e)


class ModeSegmentsHook(_Hook):
    """PlayerLayout.layoutModeSegments: lyrics and queue join the icon row instead of the two wide segments."""

    def before_hooked_method(self, param):
        try:
            player = self.plugin.player_for(param.thisObject)
            if player is not None:
                player.place_mode_buttons()
                param.setResult(None)
        except Exception as e:
            self.fail(e)


class ModeSegmentColorsHook(_Hook):
    """applyModeSegment(ImageView, ExpressiveStateDrawable, PlayerColors): plain icon, accent when selected."""

    def before_hooked_method(self, param):
        try:
            view, background, colors = param.args[0], param.args[1], param.args[2]
            tint = jclass("androidx.core.graphics.ColorUtils").blendARGB(colors.icon, colors.accent, background.getSelectProgress())
            view.setColorFilter(jclass("android.graphics.PorterDuffColorFilter")(tint, jclass("android.graphics.PorterDuff$Mode").SRC_IN))
            background.setColors(tint, 0).setSelectedContainerColor(0)
            param.setResult(None)
        except Exception as e:
            self.fail(e)


class ColorsHook(_Hook):
    """MusicPlayerSheet.applyColors: what this plugin added follows the cover colors too."""

    def after_hooked_method(self, param):
        try:
            player = self.plugin.player
            if player is not None:
                player.apply_colors(param.args[0])
        except Exception as e:
            self.fail(e)


class SpeedColorsHook(_Hook):
    """applySpeedColors: the speed button is a plain label like its neighbours, without the outline."""

    def after_hooked_method(self, param):
        try:
            self.plugin.sheet_fields.get(param.thisObject, "speedBackground").setOutline(0, 1.0)
        except Exception as e:
            self.fail(e)


class ControlsColorsHook(_Hook):
    """PlayerControlsView.setColors(tonal, onTonal, accent, onAccent): no containers, only the icons."""

    def before_hooked_method(self, param):
        try:
            icon = int(param.args[1])
            param.args[0] = JInteger(0)
            param.args[2] = JInteger(0)
            param.args[3] = JInteger(icon)
        except Exception as e:
            self.fail(e)


class CoverRectHook(_Hook):
    """PlayerCoverView.setCoverRect(left, top, size, radius, compact): the big cover's corners."""

    def before_hooked_method(self, param):
        try:
            compact = float(param.args[4])
            player = self.plugin.player
            if compact > 0.0 and player is not None and player.effects is not None:
                # toward the lyrics the cover does not shrink away: it grows and dissolves into the backdrop
                f = self.plugin.layout_fields
                lay = player.layout
                size = f.float(lay, "coverSize")
                grown = size * (1.0 + 0.6 * compact)
                param.args[0] = JFloat(float(f.float(lay, "coverLeft") - (grown - size) / 2.0))
                param.args[1] = JFloat(float(f.float(lay, "coverTop") - (grown - size) / 2.0))
                param.args[2] = JFloat(float(grown))
                param.args[3] = JFloat(float(_dp(self.plugin.cover_radius())))
                param.args[4] = JFloat(0.0)
                param.thisObject.setAlpha(max(0.0, 1.0 - compact * 1.6))
                return
            param.thisObject.setAlpha(1.0)
            radius = _dp(self.plugin.cover_radius()) * (1.0 - compact) + _dp(14) * compact
            param.args[3] = JFloat(float(radius))
        except Exception as e:
            self.fail(e)


class TransitionsHook(_Hook):
    """applyTransitions runs on every frame of a mode change: the album line leaves with the big cover."""

    def after_hooked_method(self, param):
        try:
            player = self.plugin.player
            if player is not None and player.album is not None:
                player.album.setAlpha(1.0 - min(1.0, max(0.0, self.plugin.sheet_fields.float(player.sheet, "modeProgress"))))
                # the heart and the plus come and go the way the player's own heart would
                alpha = player.profileButton.getAlpha()
                player.like.setAlpha(alpha)
                player.add.setAlpha(alpha)
                player.recenter()
                player.lyrics_layout(max(0.0, min(1.0, self.plugin.sheet_fields.float(player.sheet, "modeProgress"))))
                player.hide_panel(self.plugin.layout_fields.bool(player.layout, "keyboardLayout"))
        except Exception as e:
            self.fail(e)


class DrawHook(_Hook):
    """PlayerLayout.onDraw, after the background and under the views: the visualizer."""

    def after_hooked_method(self, param):
        try:
            player = self.plugin.player_for(param.thisObject)
            if player is not None and player.visualizer is not None:
                canvas = param.args[0]
                visualizer = player.visualizer
                progress = self.plugin.sheet_fields.float(player.sheet, "modeProgress")
                if progress > 0.003 and player.effects is not None and not (player.library_visible() or player.queue_visible()):
                    player.effects.draw(canvas, min(1.0, progress))
                # over a Spotify Canvas video the cover is only a thumbnail: bars and peeks at its old place would
                # hang over the video
                video = progress < 0.5 and player.canvas_amount() > 0.01
                if not video:
                    visualizer.draw(canvas)
                if player.peeks is not None and not video and not (player.library_visible() or player.queue_visible()):
                    player.peeks.draw(canvas, visualizer.colors)
                # the file's tags arrive after bindMessage, with nothing to tell when
                now = time.monotonic()
                if now - player.album_checked > 1.0:
                    player.album_checked = now
                    player.update_album()
        except Exception as e:
            self.fail(e)


class CoverSwapHook(_Hook):
    """PlayerCoverView.setCover(message, animated, direction): after a swipe the cover view makes the neighbor's
    slot the current one and loads nothing if that slot already holds this very song. The neighbor was loaded for
    the swipe, from a preview or a small copy, maybe before the file's cover was read: the playing song then kept
    that, or an empty cover. Here the playing song is loaded again, in full, as for any other start."""

    def __init__(self, plugin, name):
        super().__init__(plugin, name)
        self.swapped = False

    def before_hooked_method(self, param):
        try:
            cover = param.thisObject
            f = self.plugin.cover_fields
            waiting = f.int(cover, "awaitingDirection")
            neighbor = f.int(cover, "neighbor")
            self.swapped = (waiting != 0 and neighbor >= 0 and f.int(cover, "neighborDirection") == waiting
                            and f.get(cover, "messages")[neighbor] == param.args[0])
        except Exception as e:
            self.swapped = False
            self.fail(e)

    def after_hooked_method(self, param):
        try:
            if self.swapped:
                self.swapped = False
                param.thisObject.refreshCover()
        except Exception as e:
            self.fail(e)


class ShowMenuHook(_Hook):
    """MusicPlayerSheet.showMenu: the ⋯ opens the song's own menu; if that fails, the player's own one still opens."""

    def before_hooked_method(self, param):
        try:
            player = self.plugin.player
            if player is not None and player.open_song_menu():
                param.setResult(None)
        except Exception as e:
            self.fail(e)


class LyricsStateHook(_Hook):
    """LyricsView.setState: the offer to look a text up names only one service, and there are more."""

    def before_hooked_method(self, param):
        try:
            # a language the plugin has no words for keeps exteraGram's own sentence
            if "LRCLIB" in str(param.args[2] or "") and language() in ("ru", "uk", "en"):
                param.args[2] = tr("Название и исполнитель уйдут сервисам поиска текстов, а не через Telegram.")
        except Exception as e:
            self.fail(e)


class LinkSourceHook(_Hook):
    """VideoPlayer.preparePlayer: a song from the computer starts from its empty marker file, and plays from the network."""

    def before_hooked_method(self, param):
        try:
            uri = param.args[0]
            if uri is None or str(uri.getScheme()) != "file":
                return
            url = link_stream.stream_url(self.plugin, str(uri.getPath()))
            if url is not None:
                param.args[0] = jclass("android.net.Uri").parse(url)
        except Exception as e:
            self.fail(e)


class LyricsPositionHook(_Hook):
    """LyricsView.setPosition: the lines' blur follows the current line."""

    def after_hooked_method(self, param):
        try:
            player = self.plugin.player
            if player is not None and player.effects is not None:
                player.effects.position(param.thisObject)
        except Exception as e:
            self.fail(e)


class LyricsSetHook(_Hook):
    """LyricsView.setLyrics: new line views, which take the chosen alignment."""

    def after_hooked_method(self, param):
        try:
            player = self.plugin.player
            if player is not None and player.effects is not None:
                player.effects.lyrics_set(param.thisObject)
        except Exception as e:
            self.fail(e)


class LyricsHook(_Hook):
    """LyricsRepository.requestLrclib, on its own thread: the extensions are asked first, LRCLIB when they have nothing."""

    def before_hooked_method(self, param):
        try:
            found = self.plugin.extensions.lyrics_for(param.args[0])
            if found is not None:
                param.setResult(found)
        except Exception as e:
            _log("lyrics from extensions: %s" % e)


class CoverTouchHook(_Hook):
    """PlayerCoverView.dispatchTouchEvent: the cover's touches also go to the player's taps (a tap, a long press);
    the cover view itself handles them as before, so a swipe is still a swipe."""

    def before_hooked_method(self, param):
        try:
            player = self.plugin.player
            if player is not None and player.taps is not None and param.thisObject.hashCode() == player.coverView.hashCode():
                player.taps.cover_touch(param.thisObject, param.args[0])
        except Exception as e:
            self.fail(e)


class NeighborHook(_Hook):
    """MusicPlayerSheet.getNeighborMessage(direction): exteraGram gives no neighbor while the queue plays mixed, so
    a swipe showed an empty cover. The mixed queue has one too: the song MediaController would play next."""

    def before_hooked_method(self, param):
        try:
            if jclass("org.telegram.messenger.SharedConfig").shuffleMusic:
                from .peeks import shuffled_neighbor
                param.setResult(shuffled_neighbor(self.plugin.media_fields, int(param.args[0])))
        except Exception as e:
            self.fail(e)


class RhythmHook(_Hook):
    """updateRhythm: the analyzer also runs for the visualizer, even with the rhythm background off.

    Under a tab only the glow shows. It keeps moving unless the "living glow" setting is off: the moving
    background redraws the whole screen 120 times a second even while a list stands still, which warms the phone."""

    def after_hooked_method(self, param):
        try:
            player = self.plugin.player
            if player is None:
                return
            sheet = param.thisObject
            covered = player.library_visible() or player.queue_visible()
            if covered and not self.plugin.get_setting("glow_under_tabs", True):
                jclass(RHYTHM_TAP).setEnabled(False)
                background = self.plugin.sheet_fields.get(sheet, "rhythmBackground")
                if background is not None:
                    background.setAnimating(False)
                    background.setParticlesEnabled(False)
                return
            if not (self.plugin.get_setting("vis_top", True) or self.plugin.get_setting("vis_bottom", True)):
                return
            shown = sheet.isShowing() and not sheet.isDismissed() and player.layout.getWindowVisibility() == 0
            jclass(RHYTHM_TAP).setEnabled(bool(shown))
        except Exception as e:
            self.fail(e)


class BindHook(_Hook):
    def after_hooked_method(self, param):
        try:
            player = self.plugin.player
            if player is not None:
                player.update_album()
                player.update_like()
                if player.queue_visible():
                    player.queue_screen.playing_changed()
        except Exception as e:
            self.fail(e)


class SettingsFillHook(_Hook):
    """PlayerSettingsSheet.fillItems(items, adapter): this plugin's settings live in the player's own sheet."""

    def after_hooked_method(self, param):
        try:
            self.plugin.fill_settings(param.args[0])
        except Exception as e:
            self.fail(e)


class SettingsClickHook(_Hook):
    """PlayerSettingsSheet.onItemClick(item, view): the switches of this plugin."""

    def before_hooked_method(self, param):
        try:
            item_id = int(param.args[0].id)
            if item_id == ID_OPEN_SETTINGS:
                param.thisObject.dismiss()
                self.plugin.open_settings_tab()
                param.setResult(None)
                return
            key = CHECKS.get(item_id)
            if key is None:
                return
            value = not self.plugin.get_setting(key, True)
            self.plugin.set_setting(key, value)
            param.args[1].setChecked(value)
            self.plugin.settings_changed()
            param.setResult(None)
        except Exception as e:
            self.fail(e)


class BackHook(_Hook):
    """MusicPlayerSheet.onBackPressed: inside the media library, back goes up one level at a time; from the
    queue tab it goes to the player tab, the way it leaves the library, instead of closing the player."""

    def before_hooked_method(self, param):
        try:
            player = self.plugin.player
            if player is not None and player.wants_back():
                player.go_back()
                param.setResult(None)
        except Exception as e:
            self.fail(e)


class PredictiveBackHook(_Hook):
    """BottomSheet's OnBackAnimationCallback. With predictive back on (Android 13+), the back gesture and key
    reach this callback, whose onBackInvoked dismisses the sheet without asking onBackPressed: the player's own
    way back out of lyrics and queue, and the library's, never run. While the player has somewhere to go back
    to, the closing preview is skipped and the back is a step back, cancelled the way BottomSheet cancels it
    when its delegate refuses to be dismissed."""

    def __init__(self, plugin, name, kind):
        super().__init__(plugin, name)
        self.kind = kind
        self.outer = None

    def sheet(self, callback):
        if self.outer is None:
            field = callback.getClass().getDeclaredField("this$0")
            field.setAccessible(True)
            self.outer = field
        return self.outer.get(callback)

    def before_hooked_method(self, param):
        try:
            player = self.plugin.player
            if player is None or not player.sheet.equals(self.sheet(param.thisObject)) or not player.wants_back():
                return
            if self.kind == "invoked":
                param.thisObject.onBackCancelled()
                player.go_back()
            param.setResult(None)
        except Exception as e:
            self.fail(e)


class SwipeAreaHook(_Hook):
    """isSwipeDismissArea(x, y): the lists scroll under the finger, so only the screen's header drags the player down."""

    def before_hooked_method(self, param):
        try:
            player = self.plugin.player
            if player is not None and (player.library_visible() or player.queue_visible()):
                if float(param.args[1]) >= self.plugin.layout_fields.int(player.layout, "headerBottom"):
                    param.setResult(JBoolean.FALSE)
        except Exception as e:
            self.fail(e)


class ArtworkHook(_Hook):
    """MessageObject.getArtworkUrl(boolean): the file's own cover for a song from the library, never a search by title."""

    def before_hooked_method(self, param):
        try:
            path = local_path(param.thisObject)
            if path is not None:
                param.setResult(self.plugin.music.covers.get(path))
        except Exception as e:
            self.fail(e)


class NeedsArtworkHook(_Hook):
    """PlayerCovers.needsArtwork: a small cover in a phone's file is still that song's cover, so no looking online."""

    def before_hooked_method(self, param):
        try:
            if local_path(param.args[0]) is not None:
                param.setResult(JBoolean.FALSE)
        except Exception as e:
            self.fail(e)


class PlayHook(_Hook):
    """MediaController.playMessage: something started, so the time spent listening is counted from here."""

    def after_hooked_method(self, param):
        try:
            self.plugin.listen.kick()
            self.plugin.song_started()
        except Exception as e:
            self.fail(e)


class SheetTouchHook(_Hook):
    """MusicPlayerSheet.dispatchTouchEvent: every touch of the player, for the gestures on its empty places."""

    def before_hooked_method(self, param):
        try:
            player = self.plugin.player
            if player is not None and player.gestures is not None:
                player.gestures.touch(param.args[0])
        except Exception as e:
            self.fail(e)


class NextSongHook(_Hook):
    """MediaController.playNextMessageWithoutOrder: tells a song that ended by itself from a press of "next"."""

    def before_hooked_method(self, param):
        try:
            self.plugin.song_ended = bool(param.args[0])
        except Exception as e:
            self.fail(e)

    def after_hooked_method(self, param):
        self.plugin.song_ended = False


class DetachHook(_Hook):
    """PlayerLayout.onDetachedFromWindow: when the sheet is gone for good, the player lets go of what it built."""

    def after_hooked_method(self, param):
        try:
            self.plugin.close_player(param.thisObject)
        except Exception as e:
            self.fail(e)


class PlaylistHook(_Hook):
    """MediaController.setPlaylist(list, message, dialog, loop, search): the queue it replaces keeps its song
    and place, and a chat's music becomes a queue of its own."""

    def before_hooked_method(self, param):
        try:
            if self.plugin.queues is not None:
                self.plugin.queues.before_playlist()
        except Exception as e:
            self.fail(e)

    def after_hooked_method(self, param):
        try:
            if self.plugin.queues is not None:
                self.plugin.queues.after_playlist()
            player = self.plugin.player
            if player is not None and player.queue_visible():
                player.queue_screen.refresh_soon()
        except Exception as e:
            self.fail(e)


class ModeHook(_Hook):
    """MusicPlayerSheet.setMode(mode, animated): the queue is a tab now, so the tabs follow the mode."""

    def after_hooked_method(self, param):
        try:
            player = self.plugin.player
            if player is not None and player.sheet.equals(param.thisObject):
                player.mode_changed(int(param.args[0]))
        except Exception as e:
            self.fail(e)


class HeaderHook(_Hook):
    """MusicPlayerSheet.updateHeader: a song from the library belongs to Saved Messages, so Telegram would name
    that chat and count all of its music. The header names the list the queue was started from instead."""

    def after_hooked_method(self, param):
        try:
            self.plugin.library_header(param.thisObject)
        except Exception as e:
            self.fail(e)


class NewPlayerHook(_Hook):
    """ExteraConfig.getNewPlayerStyle: the sculpted player is the new one, so it is on while the plugin is."""

    def before_hooked_method(self, param):
        param.setResult(JBoolean.TRUE)
