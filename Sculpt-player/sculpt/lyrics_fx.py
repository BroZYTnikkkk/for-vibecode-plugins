# Sculpt Player for exteraGram. Copyright 2026 BroNik (@BroZYTnikkkk).

"""The lyrics screen: lines blurred by their distance from the current one, their alignment, and the cover growing
into a blurred backdrop behind them. The work done every frame is in the DEX (sculpt.LyricsFx); here it is only
decided when something changed."""

import threading

from android_utils import OnClickListener, run_on_ui_thread
from java import jclass
from java.lang import Boolean as JBoolean, Float as JFloat, Integer as JInteger

from .i18n import tr
from . import tags
from .common import MEDIA_CONTROLLER, Fields, _dp, _log, sculpt_method
from .music import local_path

LYRICS_VIEW = "com.exteragram.messenger.player.ui.LyricsView"
FROM_FILE = 0  # Lyrics.source: read from the song's own tags
SCRIM = 0.36  # how dark the backdrop gets, so words read on a light cover
ALIGN_LABELS = (tr("Слева"), tr("По центру"), tr("Справа"))


class LyricsEffects:
    def __init__(self, plugin, player):
        self.plugin = plugin
        self.player = player
        self.fields = Fields(LYRICS_VIEW)
        self.lyrics_fields = Fields("com.exteragram.messenger.player.lyrics.Lyrics")
        self.last = None
        self.cover_key = None
        self.backdrop = None
        self.density = float(player.context.getResources().getDisplayMetrics().density)
        self.clock = jclass("android.os.SystemClock")
        self.save_button = None

    def view(self):
        return self.plugin.sheet_fields.get(self.player.sheet, "lyricsView")

    # -- the lines

    def position(self, view):
        """After every LyricsView.setPosition: the blur moves only when the current line or the scrolling changed."""
        lyrics = self.fields.get(view, "lyrics")
        user_scrolls = self.fields.field("userScrollUntil").getLong(view) > self.clock.elapsedRealtime()
        # by reflection: Lyrics also has a static synced(), and on a Java object Python finds the method, always true
        blur = lyrics is not None and self.lyrics_fields.bool(lyrics, "synced") and not user_scrolls
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
        self.offer_save(view)

    def align(self, view=None):
        align = sculpt_method("sculpt.LyricsFx", "align")
        if align is None:
            return
        view = view if view is not None else self.view()
        mode = int(self.plugin.get_setting("lyrics_align", 0))
        align.invoke(None, self.fields.get(view, "lineViews"), JInteger(mode if 0 <= mode < len(ALIGN_LABELS) else 0))
        gravity = self.gravity()
        credit = self.fields.get(view, "creditView")
        if credit is not None:
            credit.setGravity(gravity)
        if self.save_button is not None:
            place = self.save_button.getLayoutParams()
            place.gravity = gravity
            self.save_button.setLayoutParams(place)

    def gravity(self):
        mode = int(self.plugin.get_setting("lyrics_align", 0))
        return 1 if mode == 1 else 8388613 if mode == 2 else 8388611

    def dispose(self):
        """The listener holds this object and through it the player: it goes with the sheet."""
        if self.save_button is not None:
            self.save_button.setOnClickListener(None)
            self.save_button = None

    # -- keeping a text found online

    def offer_save(self, view):
        """Under a text that came from the network, for a song that is a file on the phone: it can be kept in the file."""
        if self.save_button is not None:
            self.save_button.setOnClickListener(None)
            self.save_button = None
        lyrics = self.fields.get(view, "lyrics")
        lines = self.fields.get(view, "lineViews")
        playing = jclass(MEDIA_CONTROLLER).getInstance().getPlayingMessageObject()
        path = local_path(playing) if playing is not None else None
        # an instrumental never gets here: exteraGram shows it as a state of its own, without setLyrics
        if lyrics is None or lines is None or lines.isEmpty() or path is None or int(lyrics.source) == FROM_FILE:
            return
        # exteraGram credits most services under the text, but not lrcmux: then the button stands right under the last line
        credit = self.fields.get(view, "creditView")
        above = credit if credit is not None else lines.get(lines.size() - 1)
        column = self.fields.get(view, "linesLayout")
        Params = jclass("android.widget.LinearLayout$LayoutParams")
        color = self.fields.int(view, "secondaryColor")
        button = jclass("android.widget.TextView")(self.player.context)
        button.setText(tr("Сохранить текст в файл"))
        button.setContentDescription(tr("Сохранить этот текст в файл песни"))
        button.setTextSize(1, 14.0)
        button.setTextColor(color)
        button.setGravity(17)
        button.setPadding(_dp(16), _dp(8), _dp(16), _dp(8))
        button.setMinHeight(_dp(36))
        frame = jclass("android.graphics.drawable.GradientDrawable")()
        frame.setCornerRadius(float(_dp(18)))
        frame.setStroke(_dp(1), color)
        button.setBackground(frame)
        button.setOnClickListener(OnClickListener(lambda _: self.save_text(button, path, lyrics)))
        place = Params(-2, -2)
        place.setMargins(0, _dp(12 if credit is not None else 28), 0, 0)
        place.gravity = self.gravity()
        column.addView(button, column.indexOfChild(above) + 1, place)
        self.save_button = button

    def save_text(self, button, path, lyrics):
        text = str(lyrics.toText())
        button.setText(tr("Сохраняю…"))
        button.setEnabled(False)

        def finish(result):
            run_on_ui_thread(lambda: self.saved(button, path, result))

        def work():
            try:
                tags.save(path, {"lyrics": text})
                finish("saved")
            except PermissionError:
                finish("permission")
            except Exception as e:
                _log("lyrics save: %s" % type(e).__name__)
                finish("failed")

        threading.Thread(target=work, name="sculpt-lyrics-save", daemon=True).start()

    def saved(self, button, path, result):
        sheet = self.player.sheet
        if result == "saved":
            button.setVisibility(8)
            self.plugin.bulletin(sheet, "saved_messages", tr("Текст записан в файл песни."))
            return
        button.setText(tr("Сохранить текст в файл"))
        button.setEnabled(True)
        if result == "permission" and tags.request_access(path):
            self.plugin.bulletin(sheet, "info", tr("Android спрашивает разрешение. После него нажми кнопку ещё раз."))
        else:
            self.plugin.bulletin(sheet, "info", tr("Не получилось записать текст в файл."))

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
