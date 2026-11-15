# Sculpt Player for exteraGram. Copyright 2026 BroNik (@BroZYTnikkkk).

"""Up and down on the big cover: the right half sets the volume; the left half sets how solid the cover stays over
a Spotify Canvas video, or, without a video, the screen's brightness while the player is open.

A finger that goes sideways first is left to the cover view: that is a swipe to the next song. The player no longer
closes by a drag that starts on the cover (SwipeAreaHook); it closes from anywhere else."""

from java import jarray, jclass

from .i18n import tr
from .common import _dp

VOLUME, BRIGHTNESS, ALPHA = range(3)
STREAM_MUSIC = 3
SPAN = 0.85  # the share of the cover's height that runs a value from its lowest to its highest
CANCEL = 3
HINT_W = 220
HINT_H = 44


class CoverSwipes:
    def __init__(self, plugin, player):
        self.plugin = plugin
        self.player = player
        self.start = None  # (x, y) of a finger that went down on the cover, while it may still become ours
        self.active = False
        self.kind = VOLUME
        self.base = 0.0
        self.value = 0.0
        self.height = 1.0
        self.slop = jclass("android.view.ViewConfiguration").get(player.context).getScaledTouchSlop()
        self.brightness_set = False
        self.cancelling = False
        self.hint = None
        self.fill = None
        self.plates = None

    # -- touches, from CoverTouchHook; True: the touch is ours and the cover view does not see it

    def touch(self, cover, event):
        if self.cancelling:
            return False
        action = event.getActionMasked()
        if action == 0:
            self.active = False
            self.start = None
            if self.allowed(cover, event.getX(), event.getY()):
                rect = cover.getCoverRect()
                self.start = (float(event.getX()), float(event.getY()))
                self.height = max(1.0, float(rect.height()))
                left = event.getX() < rect.centerX()
                canvas_behind = self.player.canvas_amount() > 0.5 and not self.plugin.canvas_in_cover
                self.kind = VOLUME if not left else (ALPHA if canvas_behind else BRIGHTNESS)
            return False
        if self.start is None:
            return False
        if action == 2:  # move
            dx = float(event.getX()) - self.start[0]
            dy = float(event.getY()) - self.start[1]
            if not self.active:
                if abs(dy) > self.slop and abs(dy) > abs(dx) * 1.3:
                    self.begin(cover, event)
                    self.start = (self.start[0], float(event.getY()))
                    return True
                if abs(dx) > self.slop:
                    self.start = None  # a swipe to another song
                return False
            self.move(self.base - dy / (self.height * SPAN))
            return True
        if action in (1, CANCEL):
            ours = self.active
            if ours:
                self.finish()
            self.active = False
            self.start = None
            return ours
        return self.active

    def allowed(self, cover, x, y):
        player = self.player
        if player.library_visible() or player.queue_visible():
            return False
        if self.plugin.sheet_fields.float(player.sheet, "modeProgress") > 0.01:
            return False
        return bool(cover.getCoverRect().contains(x, y))

    def begin(self, cover, event):
        self.active = True
        parent = cover.getParent()
        if parent is not None:
            parent.requestDisallowInterceptTouchEvent(True)
        # the cover view and the taps let go of this finger: no long press, no swipe to another song
        cancel = jclass("android.view.MotionEvent").obtain(event)
        cancel.setAction(CANCEL)
        self.cancelling = True
        try:
            cover.dispatchTouchEvent(cancel)
            if self.player.taps is not None:
                self.player.taps.cover_touch(cover, cancel)
        finally:
            self.cancelling = False
            cancel.recycle()
        self.base = self.read()
        self.value = self.base
        self.show()

    # -- the three values, each 0..1

    def fine_top(self, audio):
        """Samsung's own finer media volume: ten steps for each of the usual ones (0..150), so the swipe moves by
        the percent instead of by 15 steps of about 7%. 0 on a phone without it."""
        try:
            if audio.semIsFineVolumeSupported():
                return max(1, int(audio.getStreamMaxVolume(STREAM_MUSIC))) * 10
        except Exception:
            pass
        return 0

    def read(self):
        if self.kind == VOLUME:
            audio = self.audio()
            fine = self.fine_top(audio)
            if fine:
                return int(audio.semGetFineVolume(STREAM_MUSIC)) / float(fine)
            top = max(1, int(audio.getStreamMaxVolume(STREAM_MUSIC)))
            return audio.getStreamVolume(STREAM_MUSIC) / float(top)
        if self.kind == ALPHA:
            return self.plugin.canvas_cover_alpha()
        params = self.player.sheet.getWindow().getAttributes()
        if params.screenBrightness >= 0:
            return float(params.screenBrightness)
        try:
            resolver = self.player.context.getContentResolver()
            return jclass("android.provider.Settings$System").getInt(resolver, "screen_brightness") / 255.0
        except Exception:
            return 0.5

    def move(self, value):
        value = max(0.0, min(1.0, value))
        if self.kind == VOLUME:
            audio = self.audio()
            fine = self.fine_top(audio)
            if fine:
                steps = int(round(value * fine))
                if steps != int(audio.semGetFineVolume(STREAM_MUSIC)):
                    audio.semSetFineVolume(STREAM_MUSIC, steps, 0)
                value = steps / float(fine)
            else:
                top = max(1, int(audio.getStreamMaxVolume(STREAM_MUSIC)))
                steps = int(round(value * top))
                if steps != audio.getStreamVolume(STREAM_MUSIC):
                    audio.setStreamVolume(STREAM_MUSIC, steps, 0)  # plain ints: the method takes int, not Integer
                value = steps / float(top)
        elif self.kind == ALPHA:
            value = round(value * 20) / 20.0  # steps of 5%, like the slider in the settings
            if value != self.value:
                self.plugin.canvas_alpha_live = value
                self.player.apply_cover_alpha()
        else:
            value = max(0.02, value)
            window = self.player.sheet.getWindow()
            params = window.getAttributes()
            params.screenBrightness = float(value)
            window.setAttributes(params)
            self.brightness_set = True
        self.value = value
        self.paint()

    def finish(self):
        if self.kind == ALPHA:
            self.plugin.set_setting("canvas_cover_alpha", int(round(self.value * 100)))
            self.plugin.canvas_alpha_live = None
        self.hide()

    def audio(self):
        return self.player.context.getSystemService("audio")

    def reset_brightness(self):
        """The player closes: the screen goes back to its own brightness."""
        if not self.brightness_set:
            return
        self.brightness_set = False
        try:
            window = self.player.sheet.getWindow()
            params = window.getAttributes()
            params.screenBrightness = -1.0
            window.setAttributes(params)
        except Exception:
            pass

    # -- the hint over the cover: what is changing and how far, on a plate filled up to the value

    def build(self, layout):
        GradientDrawable = jclass("android.graphics.drawable.GradientDrawable")
        back = GradientDrawable()
        back.setCornerRadius(float(_dp(HINT_H // 2)))
        fill = GradientDrawable()
        fill.setCornerRadius(float(_dp(HINT_H // 2)))
        clip = jclass("android.graphics.drawable.ClipDrawable")(fill, 3, 1)  # Gravity.LEFT, HORIZONTAL
        Drawable = jclass("android.graphics.drawable.Drawable")
        layers = jclass("android.graphics.drawable.LayerDrawable")(jarray(Drawable)([back, clip]))
        hint = jclass("android.widget.TextView")(self.player.context)
        hint.setBackground(layers)
        hint.setGravity(17)
        hint.setTextSize(1, 14.0)
        hint.setSingleLine(True)
        hint.setPadding(_dp(16), 0, _dp(16), 0)
        hint.setAlpha(0.0)
        hint.setVisibility(4)
        hint.setImportantForAccessibility(2)  # the system speaks its own volume and brightness
        layout.addOwnView(hint)
        self.hint, self.fill, self.plates = hint, clip, (back, fill)

    def measure(self, measure):
        if self.hint is not None:
            measure(self.hint, _dp(HINT_W), _dp(HINT_H))

    def place(self, put, cover_left, cover_top, size):
        if self.hint is not None:
            put(self.hint, int(cover_left + (size - _dp(HINT_W)) / 2), int(cover_top + _dp(16)))

    def colors(self, colors):
        if self.hint is None or colors is None:
            return
        ColorUtils = jclass("androidx.core.graphics.ColorUtils")
        self.plates[0].setColor(ColorUtils.setAlphaComponent(colors.background, 225))
        self.plates[1].setColor(ColorUtils.setAlphaComponent(colors.accent, 110))
        self.hint.setTextColor(colors.text)

    def show(self):
        if self.hint is None:
            return
        self.colors(self.plugin.sheet_fields.get(self.player.sheet, "colors"))
        self.paint()
        self.hint.setVisibility(0)
        self.hint.animate().cancel()
        self.hint.animate().alpha(1.0).setStartDelay(0).setDuration(120).start()

    def hide(self):
        if self.hint is None:
            return
        self.hint.animate().cancel()
        self.hint.animate().alpha(0.0).setStartDelay(600).setDuration(200).start()

    def paint(self):
        if self.hint is None:
            return
        name = {VOLUME: tr("Громкость"), BRIGHTNESS: tr("Яркость"), ALPHA: tr("Обложка")}[self.kind]
        self.hint.setText("%s  %d%%" % (name, int(round(self.value * 100))))
        self.fill.setLevel(int(round(self.value * 10000)))

    def dispose(self):
        self.reset_brightness()
        self.plugin.canvas_alpha_live = None
        self.hint = None
