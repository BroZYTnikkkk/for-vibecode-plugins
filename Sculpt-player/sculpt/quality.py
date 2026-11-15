# Sculpt Player for exteraGram. Copyright 2026 BroNik (@BroZYTnikkkk).

"""The playing song's quality on a small pill: "FLAC 24/96", "MP3 320". Under the cover, in the middle, or in the
cover's corner, or not at all (setting quality_pill). A tap tells the details.

The numbers are exteraGram's own (TrackQuality): the format from the document, then the file probed once it is on
the phone, which comes back later through a callback."""

from java import dynamic_proxy, jclass

from .i18n import tr
from .common import _dp

TRACK_QUALITY = "com.exteragram.messenger.player.TrackQuality"
OFF, UNDER, CORNER = 0, 1, 2
HEIGHT = 24

_loaded = {}


def _callback_class():
    found = _loaded.get("cls")
    if found is None:
        class Loaded(dynamic_proxy(jclass("org.telegram.messenger.Utilities$Callback"))):
            def __init__(self, action):
                super().__init__()
                self.action = action

            def run(self, info, *more):
                action = self.action
                self.action = None
                if action is not None:
                    action(info)
        found = _loaded["cls"] = Loaded
    return found


class FileInfo:
    """The quality of a song on the phone, read from the file here: exteraGram's TrackQuality keeps its answers
    by the document's id, and every song from the phone has the id 0, so it told the first song's quality for all."""

    FORMATS = {"audio/flac": "FLAC", "audio/mpeg": "MP3", "audio/mp4a-latm": "AAC", "audio/opus": "Opus",
               "audio/vorbis": "Vorbis", "audio/alac": "ALAC", "audio/x-wav": "WAV", "audio/raw": "WAV"}

    def __init__(self, path):
        self.format = None
        self.bitsPerSample = 0
        self.sampleRate = 0
        self.bitrateKbps = 0
        self.probed = True
        extractor = jclass("android.media.MediaExtractor")()
        try:
            extractor.setDataSource(path)
            for i in range(extractor.getTrackCount()):
                fmt = extractor.getTrackFormat(i)
                mime = str(fmt.getString("mime") or "")
                if not mime.startswith("audio/"):
                    continue
                self.format = self.FORMATS.get(mime, mime.split("/")[-1].upper())
                if fmt.containsKey("sample-rate"):
                    self.sampleRate = int(fmt.getInteger("sample-rate"))
                if fmt.containsKey("bitrate"):
                    self.bitrateKbps = int(fmt.getInteger("bitrate")) // 1000
                if fmt.containsKey("bits-per-sample"):
                    self.bitsPerSample = int(fmt.getInteger("bits-per-sample"))
                if not self.bitrateKbps and fmt.containsKey("durationUs"):
                    seconds = fmt.getLong("durationUs") / 1e6
                    if seconds > 0:
                        import os
                        self.bitrateKbps = int(os.path.getsize(path) * 8 / seconds / 1000)
                break
        finally:
            extractor.release()
        if self.format == "FLAC" and not self.bitsPerSample:
            self.bitsPerSample = _flac_bits(path)
        if self.format not in ("FLAC", "WAV", "ALAC"):
            self.bitsPerSample = 0  # a lossy file has no depth of its own: its bitrate says it

    def formatBitDepth(self):
        return tr("%d бит") % self.bitsPerSample if self.bitsPerSample > 0 else None

    def formatSampleRate(self):
        return tr("%s кГц") % ("%g" % (self.sampleRate / 1000.0)) if self.sampleRate > 0 else None

    def formatBitrate(self):
        return tr("%d кбит/с") % self.bitrateKbps if self.bitrateKbps > 0 else None


def _flac_bits(path):
    """Bits per sample from a FLAC file's STREAMINFO block."""
    try:
        with open(path, "rb") as f:
            head = f.read(42)
        if head[:4] != b"fLaC":
            return 0
        info = head[8:42]
        return (((info[12] & 0x01) << 4) | (info[13] >> 4)) + 1
    except Exception:
        return 0


_file_infos = {}


def short_text(info):
    """"FLAC 24/96", "MP3 320", or the format alone."""
    if info is None:
        return None
    name = str(info.format) if info.format is not None else ""
    bits, rate, kbps = int(info.bitsPerSample), int(info.sampleRate), int(info.bitrateKbps)
    if bits > 0 and rate > 0:
        khz = rate / 1000.0
        return ("%s %d/%s" % (name, bits, ("%g" % khz))).strip()
    if kbps > 0:
        return ("%s %d" % (name, kbps)).strip()
    return name or None


def long_text(info):
    parts = [str(info.format)] if info.format is not None else []
    for method in ("formatBitDepth", "formatSampleRate", "formatBitrate"):
        try:
            value = getattr(info, method)()
            if value is not None:
                parts.append(str(value))
        except Exception:
            pass
    return " · ".join(parts)


class QualityPill:
    def __init__(self, plugin, player):
        self.plugin = plugin
        self.player = player
        self.info = None
        self.message_id = None
        self.view = None
        self.plate = None
        self.pressed = None  # (x, y) of a finger that went down on the pill

    def where(self):
        return int(self.plugin.get_setting("quality_pill", UNDER))

    def build(self, layout):
        view = jclass("android.widget.TextView")(self.player.context)
        view.setTextSize(1, 11.0)
        view.setSingleLine(True)
        view.setGravity(17)
        view.setPadding(_dp(10), 0, _dp(10), 0)
        try:
            view.setTypeface(jclass("org.telegram.messenger.AndroidUtilities").bold())
        except Exception:
            pass
        self.plate = jclass("android.graphics.drawable.GradientDrawable")()
        self.plate.setCornerRadius(float(_dp(HEIGHT // 2)))
        view.setBackground(self.plate)
        view.setVisibility(8)
        from android_utils import OnClickListener
        self.listener = OnClickListener(lambda _: self.tapped())
        view.setOnClickListener(self.listener)
        layout.addOwnView(view)
        self.view = view

    def measure(self, measure):
        if self.view is None:
            return
        spec = jclass("android.view.View$MeasureSpec")
        self.view.measure(spec.makeMeasureSpec(_dp(220), spec.AT_MOST), spec.makeMeasureSpec(_dp(HEIGHT), spec.EXACTLY))

    def place(self, put, cover_left, cover_top, size, title_top):
        if self.view is None:
            return
        width = self.view.getMeasuredWidth()
        if self.where() == CORNER:
            x = cover_left + size - width - _dp(10)
            y = cover_top + size - _dp(HEIGHT) - _dp(10)
        else:
            # right above the title: in the middle of the gap the visualizer's bars could cover it
            x = cover_left + (size - width) / 2
            y = title_top - _dp(HEIGHT) - _dp(4)
        put(self.view, int(x), int(y))

    def colors(self, colors):
        if self.view is None or colors is None:
            return
        ColorUtils = jclass("androidx.core.graphics.ColorUtils")
        if self.where() == CORNER:
            self.plate.setColor(ColorUtils.setAlphaComponent(0xFF000000 - 0x100000000, 120))
            self.view.setTextColor(0xFFFFFFFF - 0x100000000)
        else:
            self.plate.setColor(ColorUtils.setAlphaComponent(colors.text, 30))
            self.view.setTextColor(colors.textSecondary)

    def update(self):
        """The song changed, or its file was probed: the pill says what is known now."""
        if self.view is None:
            return
        message = jclass("org.telegram.messenger.MediaController").getInstance().getPlayingMessageObject()
        if self.where() == OFF or message is None:
            self.view.setVisibility(8)
            return
        identity = (message.getDialogId(), message.getId())
        from .music import local_path
        path = local_path(message)
        if path is not None:
            self.message_id = identity
            info = _file_infos.get(path)
            if info is not None:
                self.show(info)
                return
            self.view.setVisibility(8)

            def read():
                try:
                    found = _file_infos[path] = FileInfo(path)
                except Exception as e:
                    from .common import _log
                    _log("quality %s: %s" % (path.rsplit("/", 1)[-1], e))
                    return
                from android_utils import run_on_ui_thread
                run_on_ui_thread(lambda: self.probed(identity, found))

            from .common import run_on_work
            run_on_work(read)
            return
        quality = jclass(TRACK_QUALITY)
        info = quality.get(message)
        if identity != self.message_id:
            self.message_id = identity
            if info is None or not info.probed:
                from android_utils import run_on_ui_thread
                quality.load(message, _callback_class()(lambda probed: run_on_ui_thread(lambda: self.probed(identity, probed))))
        self.show(info)

    def probed(self, identity, info):
        if identity == self.message_id and self.view is not None:
            self.show(info)

    def show(self, info):
        self.info = info
        text = short_text(info)
        if not text:
            self.view.setVisibility(8)
            return
        self.colors(self.plugin.sheet_fields.get(self.player.sheet, "colors"))
        self.view.setText(text)
        self.view.setContentDescription(tr("Качество: %s") % long_text(info))
        self.view.setVisibility(0)
        self.view.requestLayout()

    def mode(self, progress):
        """Toward the lyrics the pill leaves with the big cover."""
        if self.view is not None:
            self.view.setAlpha(max(0.0, 1.0 - progress))

    def touch(self, cover, event):
        """From CoverTouchHook: the cover view lies over the pill and takes its touches first, so a tap on the
        pill is found here. True: the touch is the pill's."""
        view = self.view
        if view is None or view.getVisibility() != 0 or view.getAlpha() < 0.5:
            self.pressed = None
            return False
        x = float(event.getX()) + cover.getLeft()
        y = float(event.getY()) + cover.getTop()
        action = event.getActionMasked()
        if action == 0:
            slack = _dp(6)
            inside = (view.getLeft() - slack <= x <= view.getRight() + slack
                      and view.getTop() - slack <= y <= view.getBottom() + slack)
            self.pressed = (x, y) if inside else None
            return inside
        if self.pressed is None:
            return False
        if action == 1:
            near = abs(x - self.pressed[0]) < _dp(12) and abs(y - self.pressed[1]) < _dp(12)
            self.pressed = None
            if near:
                self.tapped()
            return True
        if action == 3:
            self.pressed = None
        return True

    def tapped(self):
        if self.info is not None:
            self.plugin.bulletin(self.player.sheet, "info", long_text(self.info))

    def dispose(self):
        if self.view is not None:
            self.view.setOnClickListener(None)
        self.view = None
        self.listener = None
