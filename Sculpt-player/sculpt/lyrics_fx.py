# Sculpt Player for exteraGram. Copyright 2026 BroNik (@BroZYTnikkkk).

"""The lyrics screen: lines blurred by their distance from the current one, their alignment, and the cover growing
into a blurred backdrop behind them. The work done every frame is in the DEX (sculpt.LyricsFx); here it is only
decided when something changed."""

from java import jclass
from java.lang import Boolean as JBoolean, Float as JFloat, Integer as JInteger

from .common import Fields, sculpt_method

LYRICS_VIEW = "com.exteragram.messenger.player.ui.LyricsView"
SCRIM = 0.36  # how dark the backdrop gets, so words read on a light cover
ALIGN_LABELS = ("Слева", "По центру", "Справа")


class LyricsEffects:
    def __init__(self, plugin, player):
        self.plugin = plugin
        self.player = player
        self.fields = Fields(LYRICS_VIEW)
        self.last = None
        self.cover_key = None
        self.backdrop = None
        self.density = float(player.context.getResources().getDisplayMetrics().density)
        self.clock = jclass("android.os.SystemClock")

    def view(self):
        return self.plugin.sheet_fields.get(self.player.sheet, "lyricsView")

    # -- the lines

    def position(self, view):
        """After every LyricsView.setPosition: the blur moves only when the current line or the scrolling changed."""
        lyrics = self.fields.get(view, "lyrics")
        user_scrolls = self.fields.field("userScrollUntil").getLong(view) > self.clock.elapsedRealtime()
        blur = lyrics is not None and bool(lyrics.synced) and not user_scrolls
        state = (self.fields.int(view, "currentIndex"), blur, lyrics.hashCode() if lyrics is not None else 0)
        if state == self.last:
            return
        self.last = state
        focus = sculpt_method("sculpt.LyricsFx", "focus")
        if focus is not None:
            focus.invoke(None, self.fields.get(view, "lineViews"), JInteger(state[0]), JBoolean(blur), JFloat(self.density))

    def lyrics_set(self, view):
        """New lines were made: they take the alignment, and the blur is worked out again."""
        self.last = None
        self.align(view)

    def align(self, view=None):
        align = sculpt_method("sculpt.LyricsFx", "align")
        if align is None:
            return
        view = view if view is not None else self.view()
        mode = int(self.plugin.get_setting("lyrics_align", 0))
        align.invoke(None, self.fields.get(view, "lineViews"), JInteger(mode if 0 <= mode < len(ALIGN_LABELS) else 0))

    # -- the backdrop

    def refresh_backdrop(self):
        cover = self.player.coverView
        message = cover.getMessageObject()
        bitmap = cover.getImageReceiver().getBitmap()
        key = (None if message is None else message.getId(), None if bitmap is None else bitmap.hashCode())
        if key == self.cover_key or bitmap is None:
            return
        make = sculpt_method("sculpt.LyricsFx", "backdrop")
        if make is not None:
            self.backdrop = make.invoke(None, bitmap)
            self.cover_key = key

    def draw(self, canvas, progress):
        draw = sculpt_method("sculpt.LyricsFx", "draw")
        if draw is None:
            return
        self.refresh_backdrop()
        lay = self.player.layout
        draw.invoke(None, canvas, self.backdrop, JInteger(lay.getWidth()), JInteger(lay.getHeight()),
                    JFloat(float(progress)), JFloat(SCRIM))
