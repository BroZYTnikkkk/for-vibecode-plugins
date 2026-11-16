# Sculpt Player for exteraGram. Copyright 2026 BroNik (@BroZYTnikkkk).

import array
import collections
import colorsys
import math
import time

from java import jarray, jclass, jfloat, jint
from java.lang import Boolean as JBoolean, Double as JDouble, Float as JFloat, Integer as JInteger

from .common import sculpt_method, LYRICS_SHIFT, MARGIN, BANDS, BAR_RADIUS, Fields, RHYTHM_ANALYZER, RHYTHM_TAP, VIS_BARS, VIS_BUILD_SECONDS, VIS_CORNER, VIS_COVER_CHECK, VIS_DARKER, VIS_FAR_BINS, VIS_GRAY, VIS_HEIGHT_DP, VIS_HUE_BINS, VIS_LAYERS, VIS_MIN_CHROMA, VIS_MIN_HUE, VIS_MIN_SHARE, VIS_PALE_LIGHT, VIS_SAMPLE, VIS_WIDTHS, _dp, _log


def _hls(color):
    return colorsys.rgb_to_hls(((color >> 16) & 255) / 255.0, ((color >> 8) & 255) / 255.0, (color & 255) / 255.0)


def _argb(h, l, s):
    r, g, b = colorsys.hls_to_rgb(h % 1.0, l, s)
    value = 0xFF000000 | (round(r * 255) << 16) | (round(g * 255) << 8) | round(b * 255)
    return value - (1 << 32)


def _chroma(l, s):
    return s * (1.0 - abs(2.0 * l - 1.0))


def vivid_parts(found):
    """The layers, front first: the main color of the cover half faded, then that color, then its next color.

    Everything comes from the pixels of the cover. A cover with a single color gets a darker shade of that color
    for the back layer, and a cover with no color stays gray in three tones.
    """
    colors = [_hls(c) for c in found]
    lively = [c for c in colors if _chroma(c[1], c[2]) >= VIS_MIN_CHROMA]
    if not lively:
        return [_argb(0.0, 0.72, 0.0), _argb(0.0, 0.55, 0.0), _argb(0.0, 0.38, 0.0)]

    def rich(color):
        return color[0], max(0.5, min(0.66, color[1])), min(1.0, color[2] * 1.1)

    hue, light, sat = rich(lively[0])
    back = (hue, max(0.3, light - VIS_DARKER), sat)
    for color in lively[1:]:
        if abs((color[0] - hue + 0.5) % 1.0 - 0.5) > VIS_MIN_HUE:
            back = rich(color)
            break
    return [_argb(hue, (light + VIS_PALE_LIGHT) / 2.0, sat * 0.5), _argb(hue, light, sat), _argb(*back)]


def palette_from_pixels(pixels):
    """Real colors of the cover by how many pixels have them: the largest hue, then the next one far enough away.

    Counting pixels instead of clustering them: a cluster averages red and blue-gray into a violet nobody painted.
    """
    bins = [[0, 0.0, 0.0, 0.0, 0.0] for _ in range(VIS_HUE_BINS)]
    for color in pixels:
        r, g, b = ((color >> 16) & 255) / 255.0, ((color >> 8) & 255) / 255.0, (color & 255) / 255.0
        h, l, s = colorsys.rgb_to_hls(r, g, b)
        chroma = _chroma(l, s)
        if chroma < VIS_MIN_CHROMA:
            continue
        cell = bins[int(h * VIS_HUE_BINS) % VIS_HUE_BINS]
        cell[0] += 1
        # vivid pixels weigh more, so the average stays a color and not its muddy mix
        cell[1] += r * chroma
        cell[2] += g * chroma
        cell[3] += b * chroma
        cell[4] += chroma
    total = len(pixels)

    def weight(index):
        return sum(bins[(index + d) % VIS_HUE_BINS][0] for d in (-1, 0, 1))

    def far(a, b):
        d = abs(a - b) % VIS_HUE_BINS
        return min(d, VIS_HUE_BINS - d) >= VIS_FAR_BINS

    order = sorted(range(VIS_HUE_BINS), key=weight, reverse=True)
    peaks = []
    for index in order:
        need = VIS_MIN_SHARE * total
        if weight(index) >= need and all(far(index, p) for p in peaks):
            peaks.append(index)
        if len(peaks) == 2:
            break
    found = []
    for index in peaks:
        cells = [bins[(index + d) % VIS_HUE_BINS] for d in (-1, 0, 1)]
        mass = sum(c[4] for c in cells) or 1.0
        r, g, b = (sum(c[i] for c in cells) / mass for i in (1, 2, 3))
        found.append(-16777216 | (round(r * 255) << 16) | (round(g * 255) << 8) | round(b * 255))
    return found or [VIS_GRAY]


def cover_palette(bitmap):
    small = jclass("android.graphics.Bitmap").createScaledBitmap(bitmap, VIS_SAMPLE, VIS_SAMPLE, True)
    pixels = jarray(jint)(VIS_SAMPLE * VIS_SAMPLE)
    small.getPixels(pixels, 0, VIS_SAMPLE, 0, 0, VIS_SAMPLE, VIS_SAMPLE)
    if small is not bitmap:
        small.recycle()
    return palette_from_pixels(list(pixels))


class Spectrum:
    """24 frequency bands from exteraGram's own RhythmAnalyzer, in time with what is heard.

    The analyzer sees audio before it reaches the speaker, so each snapshot waits until the playback
    position catches up with it, the way RhythmTap.read treats its frames.
    """

    def __init__(self):
        self.tap_fields = Fields(RHYTHM_TAP)
        self.analyzer_fields = Fields(RHYTHM_ANALYZER)
        self.tap_class = jclass(RHYTHM_TAP)
        self.queue = collections.deque(maxlen=128)
        self.last_frame = -1
        self.tap_id = 0
        self.fresh_at = 0.0
        self.peaks = [0.05] * BANDS
        self.current = [0.0] * BANDS

    def poll(self, playing):
        """The band levels (0..1) to show now."""
        tap = self.tap_class.getCurrent()
        if tap is None or not playing:
            self.queue.clear()
            self.current = [0.0] * BANDS
            return self.current
        tap_id = tap.hashCode()
        if tap_id != self.tap_id:
            # every track gets a new tap, and its levels have nothing to do with the last track's peaks
            self.tap_id = tap_id
            self.queue.clear()
            self.last_frame = -1
            self.peaks = [0.05] * BANDS
        analyzer = self.tap_fields.get(tap, "analyzer")
        frame = self.analyzer_fields.field("frame").getLong(analyzer)
        if frame < self.last_frame:
            self.queue.clear()
        if frame != self.last_frame and frame > 0:
            self.last_frame = frame
            times = self.analyzer_fields.get(analyzer, "pendingTime")
            self.queue.append((times[int((frame - 1) % 64)], list(self.analyzer_fields.get(analyzer, "bandLevel"))))
        position = self.tap_fields.field("positionUs").getLong(tap)
        elapsed = (jclass("android.os.SystemClock").elapsedRealtimeNanos() - self.tap_fields.field("positionAtNs").getLong(tap)) // 1000
        position += 40000 + min(120000, max(0, elapsed))
        # A seek back leaves entries far ahead of the position; they would hold back everything behind them.
        while self.queue and self.queue[0][0] > position + 2000000:
            self.queue.popleft()
        levels = None
        while self.queue and self.queue[0][0] <= position:
            levels = self.queue.popleft()[1]
        now = time.monotonic()
        if levels is None and now - self.fresh_at > 0.25:
            # nothing new yet (the next track is loading): let the bars fall instead of standing still
            self.current = [0.0] * BANDS
        if levels is not None:
            out = []
            peaks = self.peaks
            for i in range(BANDS):
                level = levels[i]
                peak = max(level, peaks[i] * 0.997, 0.05)
                peaks[i] = peak
                # the levels are logarithmic and rarely fall far below the peak: spread the top part over the height
                ratio = max(0.0, (level / peak - 0.55) / 0.45)
                out.append(ratio * ratio)
            self.current = out
            self.fresh_at = now
        return self.current


MEASURE_SECONDS = 1.0 / 60.0


class Visualizer:
    """Bars above and below the cover, drawn on PlayerLayout's canvas with one gradient across the cover."""

    def __init__(self, plugin, player):
        self.plugin = plugin
        self.player = player
        self.spectrum = Spectrum()
        Paint = jclass("android.graphics.Paint")
        self.paint = Paint(Paint.ANTI_ALIAS_FLAG)
        self.paint.setStyle(jclass("android.graphics.Paint$Style").STROKE)
        self.paint.setStrokeCap(jclass("android.graphics.Paint$Cap").ROUND)
        self.layers = [[], [], []]
        self.parts = None
        self.palette = None
        self.cover_id = 0
        self.cover_checked = 0.0
        self.settings = None
        self.settings_at = 0.0
        self.media = jclass("org.telegram.messenger.MediaController")
        caps = jclass("android.graphics.Paint$Cap")
        self.butt = caps.BUTT
        self.round = caps.ROUND
        self.batches = []
        self.profiled = None  # whether the parts below are timed (profiler), known at the first frame
        self.built_at = 0.0
        self.built_key = None
        self.geometry = None  # (left, size, top, playing, scale) as last measured; () when nothing is drawn
        self.measured_at = 0.0
        self.moving = False
        self.last_time = 0.0
        self.colors = None
        self.shader_key = None
        # the bars' heights, layout and paint in this plugin's Java code; None: the Python way below
        methods = [sculpt_method("sculpt.Bars", name) for name in ("advance", "build", "paint", "frame", "clear", "mode")]
        self.bars = methods if all(m is not None for m in methods) else None
        self.flags = 0  # what the last frame said (Bars.LYRICS, VIDEO, BUILD)
        self.layer_params = jarray(jfloat)([float(v) for layer in VIS_LAYERS for v in layer])

    def set_colors(self, colors):
        self.colors = colors
        self.shader_key = None

    def _config(self, now):
        """Reading settings goes through Java: once per second is enough, a change in the sheet resets it."""
        if self.settings is None or now - self.settings_at > 1.0:
            get = self.plugin.get_setting
            density, height = get("vis_density", 1), get("vis_height", 1)
            # the sliders' values; before them, a choice of three
            bars = get("vis_bars", None) or VIS_BARS[density if 0 <= density < len(VIS_BARS) else 1]
            height_dp = get("vis_height_dp", None) or VIS_HEIGHT_DP[height if 0 <= height < len(VIS_HEIGHT_DP) else 1]
            self.settings = (get("vis_top", True), get("vis_bottom", True), int(bars), get("vis_color_mode", 0),
                             float(height_dp), get("vis_style", 0), self.plugin.cover_radius())
            self.strip_on_top = int(get("lyrics_vis", 0)) == 1
            self.settings_at = now
        return self.settings

    def _shader(self, left, size, top, height_top, height_bottom):
        """The paint for the bars: solid colors per layer in the three-layer mode, a gradient in the others."""
        mode = self.settings[3]
        key = (round(left), round(size), round(top), round(height_top), round(height_bottom), mode)
        if key == self.shader_key or self.colors is None:
            return
        self.shader_key = key
        colors = self.colors
        Gradient = jclass("android.graphics.LinearGradient")
        clamp = jclass("android.graphics.Shader$TileMode").CLAMP
        base, middle, tip = vivid_parts(self.palette or [colors.glow[0]])
        span = height_top + size + height_bottom
        if mode == 2 or span <= 0:
            self.paint.setShader(Gradient(float(left), 0.0, float(left + size), 0.0, jarray(jint)([colors.accent, colors.accent]), None, clamp))
            return
        y0, y1 = top - height_top, top + size + height_bottom
        if mode == 1:
            # colors fixed across the cover, whitening towards the tip of each bar
            edge, side, center = tip, middle, base
            across = Gradient(float(left), 0.0, float(left + size), 0.0, jarray(jint)([edge, side, center, side, edge]), None, clamp)
            clear, white = 16777215, -1
            marks = [0.0, 0.75 * height_top / span, height_top / span, (height_top + size) / span,
                     (height_top + size + 0.25 * height_bottom) / span, 1.0]
            along = Gradient(0.0, float(y0), 0.0, float(y1), jarray(jint)([white, clear, clear, clear, clear, white]),
                             jarray(jfloat)(marks), clamp)
            self.paint.setShader(jclass("android.graphics.ComposeShader")(across, along, jclass("android.graphics.PorterDuff$Mode").SRC_OVER))
            return
        self.parts = (base, middle, tip)
        self.paint.setShader(None)

    def _check_cover(self, now):
        """exteraGram fills its own glow colors with shifted hues when a cover has few of them or is not read yet,
        so the palette comes from the bitmap on screen, read once per bitmap."""
        if now - self.cover_checked < VIS_COVER_CHECK:
            return
        self.cover_checked = now
        receiver = self.player.coverView.getImageReceiver()
        bitmap = receiver.getBitmap() if receiver is not None else None
        if bitmap is None or bitmap.isRecycled():
            return
        cover_id = bitmap.hashCode()
        if cover_id == self.cover_id:
            return
        self.cover_id = cover_id
        try:
            self.palette = cover_palette(bitmap)
        except Exception as e:
            self.palette = None
            _log("cover palette: %s" % e)
        self.shader_key = None

    def _advance(self, count, bands, layered):
        now = time.monotonic()
        dt = min(0.1, now - self.last_time) if self.last_time else 0.016
        self.last_time = now
        moving = False
        scale = (BANDS - 1) / float(max(1, count - 1))
        last = BANDS - 1
        for layer, (shift, rise, fall, gain, depth, speed, phase) in enumerate(VIS_LAYERS if layered else VIS_LAYERS[:1]):
            values = self.layers[layer]
            if len(values) != count:
                values = self.layers[layer] = [0.0] * count
            rise = min(1.0, dt * rise)
            fall = min(1.0, dt * fall)
            if not layered:
                gain = 1.0
            for i in range(count):
                at = max(0.0, min(float(last), i * scale + shift))
                low = int(at)
                high = min(last, low + 1)
                target = (bands[low] + (bands[high] - bands[low]) * (at - low)) * gain
                if depth:
                    target *= 1.0 - depth + depth * (0.5 + 0.5 * math.sin(now * speed + i * phase))
                value = values[i]
                value += (target - value) * (rise if target > value else fall)
                values[i] = value
                if value > 0.005:
                    moving = True
        return moving

    def draw(self, canvas):
        if self.profiled is None:
            from . import profiler
            self.profiled = profiler.enabled()
            if self.profiled:
                self._build = profiler.timed("vis.build", self._build)
                self._config = profiler.timed("vis.config", self._config)
                self.paint_batches = profiler.timed("vis.paint", self.paint_batches)
        if self.player.library_visible() or self.player.queue_visible():
            return  # hidden under the media library or the queue: nothing to draw, and no reason to keep redrawing
        if self.bars is not None:
            # one call a frame: Java reads the player's state, paints the bars and says when to lay them out again
            player = self.player
            flags = int(self.bars[3].invoke(None, canvas, self.paint, player.sheet, player.layout, player.coverView))
            self.flags = flags & 7
            if flags & 8:
                _log("visualizer: the Java frame failed, Python draws")
                self.bars = None
            elif flags & 4 and not flags & 2:
                self.geometry = self.measure(time.monotonic())
                if not self.geometry:
                    self.bars[4].invoke(None)
            return
        started = time.monotonic()
        if self.geometry is None or started - self.measured_at >= MEASURE_SECONDS:
            # the cover's place and the player's state are read 60 times a second at most: each read is a call into
            # Java, and a 120 Hz screen draws twice as often as any of them needs
            self.measured_at = started
            self.geometry = self.measure(started)
        if not self.geometry:
            return
        left, size, top, playing, scale = self.geometry
        player = self.player
        lay = player.layout

        # A finger swiping the cover moves it sideways, shrinks it and fades it (PlayerCoverView.drawSide): the
        # bars go with it, so they never hang in place over the next cover.
        cover = player.coverView
        offset = float(cover.getPageOffset())
        fade = 1.0
        if offset != 0.0:
            page = float(cover.getPageWidth())
            pager = self.plugin.cover_fields.float(cover, "pager")
            amount = (1.0 - pager) * min(1.0, abs(offset) / page) if page > 0 else 0.0
            shrink = 1.0 + (0.86 - 1.0) * amount
            fade = 1.0 + (0.55 - 1.0) * amount
            canvas.save()
            canvas.translate(offset, 0.0)
            canvas.scale(shrink, shrink, left + size / 2.0, top + size / 2.0)

        self.paint_batches(canvas, fade)
        if offset != 0.0:
            canvas.restore()
        # the cover redraws only itself while it slides: the layer under it is asked for each frame here
        if playing or self.moving or offset != 0.0 or 0.941 < scale < 0.999:
            lay.postInvalidateOnAnimation()

    def measure(self, started):
        """Reads where the bars go and lays them out again when it is time; () when there is nothing to draw."""
        show_top, show_bottom, density, color_mode, height_index, style, cover_radius = self._config(started)
        self.top_extent = 0.0
        if not show_top and not show_bottom:
            return ()
        player = self.player
        sheet_fields, f = self.plugin.sheet_fields, self.plugin.layout_fields
        lay = player.layout
        self.raw = None
        mode = max(0.0, min(1.0, sheet_fields.float(player.sheet, "modeProgress")))
        playing = not self.media.getInstance().isMessagePaused()
        # with the lyrics open the bars leave the cover and become a low strip standing on the title
        strip = mode > 0.5

        full_left = f.float(lay, "coverLeft")
        full_size = f.float(lay, "coverSize")
        if full_size <= 0:
            return ()
        # the cover shrinks around its center on pause (PlayerCoverView.pauseScale): the bars stay on its edges
        scale = self.plugin.cover_fields.float(player.coverView, "pauseScale")
        inset = full_size * (1.0 - scale) / 2.0
        left = full_left + inset
        size = full_size * scale
        cover_top = f.float(lay, "coverTop")
        top = cover_top + inset
        # what Java compares each frame to know the cover moved: the values as read, before the strip's own place
        self.raw = (full_left, full_size, cover_top, mode, scale)
        if strip:
            show_top, show_bottom = True, False
            inset = 0.0
            full_left = left = float(f.int(lay, "paneLeft") + _dp(MARGIN))
            full_size = size = float(f.int(lay, "paneWidth") - 2 * _dp(MARGIN))
            top = float(f.int(lay, "titleTop") + _dp(LYRICS_SHIFT) - _dp(6))
            if getattr(self, "strip_on_top", False):
                # hanging from the header and growing down, the way the bottom row grows from a cover's lower edge
                show_top, show_bottom = False, True
                top = float(f.int(lay, "headerBottom") + _dp(4)) - size

        # The numbers change 40 times a second at most: other frames paint what is built, at almost no cost.
        key = (left, size, top, mode, color_mode, style, density, height_index, show_top, show_bottom, self.shader_key)
        if started - self.built_at >= VIS_BUILD_SECONDS or key != self.built_key:
            self._build(lay, f, left, size, top, inset, full_left, full_size, mode, playing, color_mode, style, density,
                        height_index, show_top, show_bottom, cover_radius, strip)
            self.built_at = started
            self.built_key = (left, size, top, mode, color_mode, style, density, height_index, show_top, show_bottom, self.shader_key)
        return left, size, top, playing, scale

    def lyrics_progress(self):
        """How far the lyrics are open, as the last frame saw it; 0 while they are closed."""
        if self.bars is not None:
            return float(self.bars[5].invoke(None)) if self.flags & 1 else 0.0
        return max(0.0, min(1.0, self.plugin.sheet_fields.float(self.player.sheet, "modeProgress")))

    def video(self):
        """Whether a Spotify Canvas video stands where the cover was."""
        if self.bars is not None:
            return bool(self.flags & 2)
        return self.lyrics_progress() < 0.5 and self.player.canvas_amount() > 0.01

    def paint_batches(self, canvas, fade):
        if self.bars is not None:
            self.bars[2].invoke(None, canvas, self.paint, JFloat(fade))
            return
        paint = self.paint
        for color, width, tip_width, corner_width, body, tips, corners, alpha in self.batches:
            alpha = int(alpha * fade)
            if color is not None:
                # setARGB: Python ints would pick the setColor(long) overload
                paint.setARGB(alpha, color[0], color[1], color[2])
            else:
                paint.setAlpha(alpha)
            paint.setStrokeCap(self.butt if tips is not None else self.round)
            paint.setStrokeWidth(width)
            canvas.drawLines(body, paint)
            if tips is not None:
                # Slightly rounded rectangles in three batches, far cheaper than a drawRoundRect call per bar.
                paint.setStrokeWidth(tip_width)
                canvas.drawLines(tips, paint)
                paint.setStrokeCap(self.round)
                paint.setStrokeWidth(corner_width)
                canvas.drawPoints(corners, paint)

    def _build(self, lay, f, left, size, top, inset, full_left, full_size, mode, playing, color_mode, style, density,
               height_index, show_top, show_bottom, cover_radius, strip=False):
        count = density  # the number of bars itself, since the slider
        layered = color_mode == 0
        self._check_cover(self.built_at)
        bands = self.spectrum.poll(playing)
        if self.bars is not None:
            self.moving = bool(self.bars[0].invoke(None, jarray(jfloat)(bands), self.layer_params, JInteger(count),
                                                   JBoolean(layered), JDouble(time.monotonic())))
        else:
            self.moving = self._advance(count, bands, layered)
        wanted = _dp(48) if strip else _dp(height_index)  # dp, since the slider
        full_top = top - inset
        ceiling = f.int(lay, "headerBottom") + _dp(4)
        above = max(0.0, min(wanted, full_top - ceiling)) if show_top else 0.0
        below = max(0.0, min(wanted, f.int(lay, "titleTop") - _dp(4) - (full_top + full_size))) if show_bottom else 0.0
        self._shader(full_left, full_size, full_top, above, below)

        step = size / count
        half = step / 2.0
        rows = []
        if show_top:
            room = top - ceiling
            rows.append((top, -1.0, max(0.0, min(wanted, room))))
        if show_bottom:
            room = f.int(lay, "titleTop") - _dp(4) - (top + size)
            rows.append((top + size, 1.0, max(0.0, min(wanted, room))))

        # The bars start under the cover, which is drawn over them: this also fills its rounded corners.
        width = step * VIS_WIDTHS[style]
        # a strip has no cover over its foot: the feet stay on the line, a round cap included
        inside = (0.0 if style == 0 else -width / 2.0) if strip else _dp(cover_radius) + _dp(2)
        radius = min(_dp(BAR_RADIUS), width * VIS_CORNER)
        offset = width / 2.0 - radius
        alpha = int(255 * 0.85 * max(0.0, 2.0 * mode - 1.0)) if strip else int(255 * max(0.0, 1.0 - 2.0 * mode))
        self.top_extent = float(rows[0][2]) if show_top and rows else 0.0
        if self.bars is not None:
            geometry = [left, step, inside, width, radius, offset]
            for base, sign, height in rows:
                geometry += [base, sign, height]
            raw = self.raw or (0.0, 0.0, 0.0, mode, 1.0)
            geometry += [left + size / 2.0, rows[0][0] if strip else (top + size / 2.0)] + list(raw)
            flags = [1 if layered else 0, style, 1 if strip else 0, alpha, len(rows), count]
            colors = jarray(jint)(list(self.parts)) if layered and self.parts is not None else None
            self.bars[1].invoke(None, jarray(jfloat)([float(v) for v in geometry]), jarray(jint)(flags), colors)
            return
        batches = []
        for layer in (2, 1, 0) if layered else (0,):
            values = self.layers[layer]
            hiding = self.layers[:layer] if layered else ()
            body, tips, corners = array.array("f"), array.array("f"), array.array("f")
            for base, sign, height in rows:
                start = base - sign * inside
                for i, value in enumerate(values):
                    # what a layer in front covers is not drawn at all
                    if value <= 0.005 or any(front[i] >= value for front in hiding):
                        continue
                    x = left + half + i * step
                    reach = height * value
                    if strip:
                        # a bar shorter than its own rounded top would poke through the line
                        reach = max(reach, 2.0 * radius if style == 0 else width)
                    tip = base + sign * reach
                    if style != 0:
                        body.extend((x, start, x, tip))
                        continue
                    neck = tip - sign * radius
                    body.extend((x, start, x, neck))
                    tips.extend((x, neck - sign, x, tip))
                    corners.extend((x - offset, neck, x + offset, neck))
            if not len(body):
                continue
            color = None
            if layered and self.parts is not None:
                part = self.parts[layer]
                color = ((part >> 16) & 255, (part >> 8) & 255, part & 255)
            batches.append((color, float(width), float(width - 2.0 * radius), float(2.0 * radius), jarray(jfloat)(body),
                            jarray(jfloat)(tips) if style == 0 else None, jarray(jfloat)(corners) if style == 0 else None, alpha))
        self.batches = batches
        self.top_extent = float(rows[0][2]) if show_top and rows else 0.0
