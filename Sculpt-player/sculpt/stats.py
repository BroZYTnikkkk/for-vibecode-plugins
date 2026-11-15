# Sculpt Player for exteraGram. Copyright 2026 BroNik (@BroZYTnikkkk).

"""Listening statistics: how long music played, day by day and song by song, and every stretch of listening with
its exact time. Kept in the plugin's own data folder (stats.json), which clearing Telegram's cache does not touch.

The screen: a week, a month or a year as a line of points, the time in total, the songs and authors heard most,
each song with how many times it was heard to the end; a day's point opens that day's stretches of listening, a
month's point in the year opens that month.

A play counts when one run of the song reaches PLAYED of its length: a song skipped halfway is time, not a play."""

import calendar
import datetime
import time

from java import jclass

from .common import _dp, _log, run_on_work
from .i18n import language, plural, tr
from .library_ui import Screen
from .music import local_path, split_artists

SESSION_GAP = 20.0  # seconds of silence that end one stretch of listening and start the next
SESSIONS_MAX = 20000
SAVE_EVERY = 60.0
TOP_SONGS = 10
TOP_ARTISTS = 5
WEEK, MONTH, YEAR = 0, 1, 2
PLAYED = 0.9  # the share of a song one run must reach to count as heard once


def day_key(stamp):
    return time.strftime("%Y-%m-%d", time.localtime(stamp))


def _paint_color(paint, color):
    """Paint.setColor(int) loses to its long overload from Python (a color long is not a color): the channels."""
    color = int(color) & 0xFFFFFFFF
    paint.setARGB(color >> 24, (color >> 16) & 0xFF, (color >> 8) & 0xFF, color & 0xFF)


def times_text(count):
    if language() == "en":
        return "%d play%s" % (count, "" if count == 1 else "s")  # Russian has one word for one and for many
    return "%d %s" % (count, plural(count, tr("раз"), tr("раза"), tr("раз")))


def duration_text(seconds):
    seconds = int(seconds)
    hours, minutes = seconds // 3600, seconds % 3600 // 60
    if hours:
        return tr("%d ч %d мин") % (hours, minutes)
    if minutes:
        return tr("%d мин") % minutes
    return tr("%d сек") % seconds


class StatsStore:
    def __init__(self, plugin):
        self.plugin = plugin
        data = plugin.music._load("stats.json", {})
        if not isinstance(data, dict):
            data = {}
        self.songs = data.get("songs") if isinstance(data.get("songs"), dict) else {}
        self.days = data.get("days") if isinstance(data.get("days"), dict) else {}
        self.sessions = data.get("sessions") if isinstance(data.get("sessions"), list) else []
        self.plays = data.get("plays") if isinstance(data.get("plays"), dict) else {}
        # stretches kept before plays were counted are counted once, when the library knows the songs' lengths
        self.recount = not data.get("plays_recounted")
        self.saved_at = time.monotonic()
        self.dirty = False
        # the song playing now: its key, how long this run of it has played, whether it has counted already
        self.run_key = None
        self.run_seconds = 0.0
        self.run_counted = False

    def _plays_from_sessions(self):
        plays = {}
        for start, seconds, key in self.sessions:
            track = self.plugin.music.by_path.get(key) if not str(key).startswith("tg:") else None
            length = float((track or {}).get("duration") or 0)
            if length <= 0:
                continue
            count = int(seconds / length + (1.0 - PLAYED))
            if count > 0:
                day = plays.setdefault(day_key(start), {})
                day[key] = day.get(key, 0) + count
        return plays

    def new_run(self):
        """A song started (MediaController.playMessage): the next seconds belong to a new run of it."""
        self.run_key = None

    # -- recording, from music.ListenTimer every few seconds of playing

    def add(self, message, seconds):
        if seconds <= 0:
            return
        path = local_path(message)
        if path is not None:
            key = path
            track = self.plugin.music.by_path.get(path) or {}
            title, artist = track.get("title") or "", track.get("artist") or ""
        else:
            key = "tg:%d:%d" % (message.getDialogId(), message.getId())
            title, artist = str(message.getMusicTitle() or ""), str(message.getMusicAuthor() or "")
        if not title:
            title = str(message.getMusicTitle() or "")
        self.songs[key] = [title, artist, path or ""]
        now = time.time()
        day = self.days.setdefault(day_key(now), {})
        day[key] = round(day.get(key, 0.0) + seconds, 1)
        if key != self.run_key:
            self.run_key, self.run_seconds, self.run_counted = key, 0.0, False
        self.run_seconds += seconds
        if not self.run_counted:
            length = float((self.plugin.music.by_path.get(path) or {}).get("duration") or 0) if path else 0.0
            if length <= 0:
                try:
                    length = float(message.getDuration())
                except Exception:
                    length = 0.0
            if length > 0 and self.run_seconds >= PLAYED * length:
                self.run_counted = True
                counts = self.plays.setdefault(day_key(now), {})
                counts[key] = counts.get(key, 0) + 1
        last = self.sessions[-1] if self.sessions else None
        if last is not None and last[2] == key and last[0] + last[1] >= now - seconds - SESSION_GAP:
            last[1] = round(now - last[0], 1)
        else:
            self.sessions.append([int(now - seconds), round(seconds, 1), key])
            if len(self.sessions) > SESSIONS_MAX:
                del self.sessions[:len(self.sessions) - SESSIONS_MAX]
        self.dirty = True
        if time.monotonic() - self.saved_at > SAVE_EVERY:
            self.save()

    def save(self):
        if not self.dirty:
            return
        self.dirty = False
        self.saved_at = time.monotonic()
        data = {"version": 2, "songs": dict(self.songs), "days": {k: dict(v) for k, v in self.days.items()},
                "sessions": [list(s) for s in self.sessions], "plays": {k: dict(v) for k, v in self.plays.items()},
                "plays_recounted": not self.recount}
        run_on_work(lambda: self.plugin.music._save("stats.json", data))

    # -- reading, for the screen

    def total(self, days):
        return sum(sum(self.days.get(d, {}).values()) for d in days)

    def per_song(self, days):
        out = {}
        for d in days:
            for key, seconds in self.days.get(d, {}).items():
                out[key] = out.get(key, 0.0) + seconds
        return out

    def plays_of(self, days):
        if self.recount and self.plugin.music.by_path:
            self.recount = False
            for day, counts in self._plays_from_sessions().items():
                kept = self.plays.setdefault(day, {})
                for key, count in counts.items():
                    kept[key] = kept.get(key, 0) + count
            self.dirty = True
            self.save()
        out = {}
        for d in days:
            for key, count in self.plays.get(d, {}).items():
                out[key] = out.get(key, 0) + count
        return out

    def per_artist(self, songs):
        out = {}
        for key, seconds in songs.items():
            artist = (self.songs.get(key) or ["", "", ""])[1]
            for name in split_artists(artist) if artist else []:
                out[name] = out.get(name, 0.0) + seconds
        return out

    def sessions_of(self, day):
        """(start, seconds, key) of one day's stretches of listening, the latest first."""
        return [s for s in reversed(self.sessions) if day_key(s[0]) == day]


class Period:
    """A week, a month or a year, `back` of them before the current one."""

    def __init__(self, kind, back):
        today = datetime.date.today()
        self.kind = kind
        if kind == WEEK:
            self.start = today - datetime.timedelta(days=today.weekday() + 7 * back)
            self.parts = [self.start + datetime.timedelta(days=i) for i in range(7)]
        elif kind == MONTH:
            year, month = today.year, today.month - back
            while month < 1:
                month += 12
                year -= 1
            self.start = datetime.date(year, month, 1)
            count = calendar.monthrange(year, month)[1]
            self.parts = [self.start + datetime.timedelta(days=i) for i in range(count)]
        else:
            self.start = datetime.date(today.year - back, 1, 1)
            self.parts = [datetime.date(self.start.year, m, 1) for m in range(1, 13)]

    def days_of(self, part):
        if self.kind == YEAR:
            count = calendar.monthrange(part.year, part.month)[1]
            return [(part + datetime.timedelta(days=i)).isoformat() for i in range(count)]
        return [part.isoformat()]

    def all_days(self):
        return [d for part in self.parts for d in self.days_of(part)]


def locale_names():
    """Short weekday names (Monday first), short and full month names, in the language of the player."""
    try:
        locale = jclass("org.telegram.messenger.LocaleController").getInstance().getCurrentLocale()
        symbols = jclass("java.text.DateFormatSymbols").getInstance(locale)
        weekdays = [str(w) for w in symbols.getShortWeekdays()]  # index 1 is Sunday
        return ([weekdays[(i + 1) % 7 + 1] for i in range(7)], [str(m) for m in symbols.getShortMonths()][:12],
                [str(m) for m in symbols.getMonths()][:12])
    except Exception as e:
        _log("stats names: %s" % e)
        numbers = [str(n) for n in range(1, 13)]
        return [str(n) for n in range(1, 8)], numbers, numbers


class StatsScreen(Screen):
    """A period at a time: its chart, its time, its songs and authors."""

    def __init__(self, owner):
        super().__init__(owner, tr("Статистика"))
        self.store = owner.plugin.stats
        self.store.save()
        self.kind = WEEK
        self.back_by = 0
        self.weekdays, self.months, self.long_months = locale_names()
        LinearLayout = jclass("android.widget.LinearLayout")
        Params = jclass("android.widget.LinearLayout$LayoutParams")
        context = owner.context
        page = LinearLayout(context)
        page.setOrientation(1)
        page.addView(self.header())
        scroll = jclass("android.widget.ScrollView")(context)
        scroll.setVerticalScrollBarEnabled(False)
        self.body = LinearLayout(context)
        self.body.setOrientation(1)
        self.body.setPadding(_dp(16), 0, _dp(16), _dp(24))
        scroll.addView(self.body)
        page.addView(scroll, Params(-1, 0, 1.0))
        self.view = page
        self.refresh()

    # -- building

    def pill(self, row, text, selected, action):
        owner = self.owner
        view = self.label(14, "onAccent" if selected else "text", selected)
        view.setText(text)
        view.setGravity(17)
        tone = jclass("androidx.core.graphics.ColorUtils").setAlphaComponent(owner.color("text"), 26)
        view.setBackground(owner.rounded(owner.color("accent") if selected else tone, _dp(18)))
        self.click(view, action)
        place = jclass("android.widget.LinearLayout$LayoutParams")(0, _dp(36), 1.0)
        place.setMarginEnd(_dp(8))
        row.addView(view, place)

    def section(self, text):
        label = self.label(17, "text", True)
        label.setText(text)
        label.setPadding(0, _dp(24), 0, _dp(8))
        self.body.addView(label)

    def line(self, first, second, value):
        owner = self.owner
        Params = jclass("android.widget.LinearLayout$LayoutParams")
        row = jclass("android.widget.LinearLayout")(owner.context)
        row.setOrientation(0)
        row.setGravity(16)
        texts = jclass("android.widget.LinearLayout")(owner.context)
        texts.setOrientation(1)
        top = self.label(15, "text")
        top.setText(first)
        top.setSingleLine(True)
        texts.addView(top)
        if second:
            bottom = self.label(13, "textSecondary")
            bottom.setText(second)
            bottom.setSingleLine(True)
            texts.addView(bottom)
        row.addView(texts, Params(0, -2, 1.0))
        amount = self.label(14, "textSecondary")
        amount.setText(value)
        row.addView(amount)
        self.body.addView(row, Params(-1, _dp(52)))

    def song_line(self, title, artist, path, count, seconds):
        """A song: its cover, its names, how many times it was heard to the end on a pill, and its time."""
        owner = self.owner
        Params = jclass("android.widget.LinearLayout$LayoutParams")
        LinearLayout = jclass("android.widget.LinearLayout")
        row = LinearLayout(owner.context)
        row.setOrientation(0)
        row.setGravity(16)
        cover = jclass("android.widget.ImageView")(owner.context)
        cover.setScaleType(jclass("android.widget.ImageView$ScaleType").CENTER_CROP)
        cover.setClipToOutline(True)
        self.back(cover, "tonal", _dp(8))
        jpg = owner.plugin.music.covers.get(path) if path else None
        bitmap = jclass("android.graphics.BitmapFactory").decodeFile(jpg) if jpg else None
        if bitmap is not None:
            cover.setImageBitmap(bitmap)
        else:
            owner.set_icon(cover, ("msg_filled_musicnote", "media_music", "msg_musicnote"))
            cover.setScaleType(jclass("android.widget.ImageView$ScaleType").CENTER)
            self.tint_icon(cover, "onTonal")
        at = Params(_dp(44), _dp(44))
        at.setMarginEnd(_dp(12))
        row.addView(cover, at)
        texts = LinearLayout(owner.context)
        texts.setOrientation(1)
        top = self.label(15, "text")
        top.setText(title)
        top.setSingleLine(True)
        texts.addView(top)
        if artist:
            bottom = self.label(13, "textSecondary")
            bottom.setText(artist)
            bottom.setSingleLine(True)
            texts.addView(bottom)
        row.addView(texts, Params(0, -2, 1.0))
        side = LinearLayout(owner.context)
        side.setOrientation(1)
        side.setGravity(5)  # end
        if count > 0:
            pill = self.label(12, "onTonal", True)
            pill.setText(times_text(count))
            pill.setPadding(_dp(10), _dp(2), _dp(10), _dp(2))
            self.back(pill, "tonal", _dp(10))
            side.addView(pill)
        amount = self.label(12, "textSecondary")
        amount.setText(duration_text(seconds))
        amount.setPadding(0, _dp(2), _dp(2), 0)
        side.addView(amount)
        at = Params(-2, -2)
        at.setMarginStart(_dp(8))
        row.addView(side, at)
        self.body.addView(row, Params(-1, _dp(60)))

    def refresh(self):
        self.body.removeAllViews()
        owner = self.owner
        Params = jclass("android.widget.LinearLayout$LayoutParams")
        LinearLayout = jclass("android.widget.LinearLayout")
        period = Period(self.kind, self.back_by)

        kinds = LinearLayout(owner.context)
        kinds.setOrientation(0)
        kinds.setPadding(0, _dp(4), 0, _dp(8))
        for kind, text in ((WEEK, tr("Неделя")), (MONTH, tr("Месяц")), (YEAR, tr("Год"))):
            self.pill(kinds, text, kind == self.kind, lambda k=kind: self.choose(k, 0))
        self.body.addView(kinds, Params(-1, -2))

        bar = LinearLayout(owner.context)
        bar.setOrientation(0)
        bar.setGravity(16)
        earlier = self.icon_button(("msg_arrowright",), tr("Раньше"), self.choose, self.kind, self.back_by + 1)
        earlier.setScaleX(-1.0)  # the same arrow as "later", turned the other way
        bar.addView(earlier, owner.params(40, 40))
        name = self.label(15, "text", True)
        name.setText(self.period_name(period))
        name.setGravity(17)
        bar.addView(name, Params(0, -2, 1.0))
        later = self.icon_button(("msg_arrowright",), tr("Позже"), self.choose, self.kind, max(0, self.back_by - 1))
        later.setAlpha(1.0 if self.back_by > 0 else 0.3)
        later.setEnabled(self.back_by > 0)
        bar.addView(later, owner.params(40, 40))
        self.body.addView(bar, Params(-1, -2))

        days = period.all_days()
        big = self.label(34, "text", True)
        big.setText(duration_text(self.store.total(days)))
        big.setPadding(0, _dp(8), 0, 0)
        self.body.addView(big)
        songs = self.store.per_song(days)
        plays = self.store.plays_of(days)
        under = self.label(14, "textSecondary")
        heard = sum(plays.values())
        under.setText((tr("Песен: %d") % len(songs) + (" · " + times_text(heard) if heard else "")) if songs
                      else tr("Пока тишина: статистика копится, пока играет музыка."))
        under.setSingleLine(False)
        self.body.addView(under)

        self.chart(period)
        if not songs:
            return
        self.section(tr("Песни"))
        for key, seconds in sorted(songs.items(), key=lambda kv: (-plays.get(kv[0], 0), -kv[1]))[:TOP_SONGS]:
            title, artist, path = (self.store.songs.get(key) or ["", "", ""])[:3]
            self.song_line(title or tr("Без названия"), artist, path, plays.get(key, 0), seconds)
        artists = sorted(self.store.per_artist(songs).items(), key=lambda kv: -kv[1])[:TOP_ARTISTS]
        if artists:
            self.section(tr("Исполнители"))
            for name_text, seconds in artists:
                self.line(name_text, "", duration_text(seconds))

    def chart(self, period):
        """A point per day (per month in a year), its height by the time, joined by lines that stop short of the
        points; today, or this month, a larger point. Drawn once into a picture; a tap on a point's column opens it."""
        owner = self.owner
        Params = jclass("android.widget.LinearLayout$LayoutParams")
        LinearLayout = jclass("android.widget.LinearLayout")
        FrameLayout = jclass("android.widget.FrameLayout")
        values = [self.store.total(period.days_of(part)) for part in period.parts]
        today = datetime.date.today()
        current = [((part.month == today.month and part.year == today.year) if period.kind == YEAR else part == today)
                   for part in period.parts]
        width = owner.context.getResources().getDisplayMetrics().widthPixels - _dp(32)
        try:
            pane = owner.plugin.layout_fields.int(owner.player.layout, "paneWidth")
            if pane > 0:
                width = pane - _dp(32)
        except Exception:
            pass
        height = _dp(160)
        frame = FrameLayout(owner.context)
        picture = jclass("android.widget.ImageView")(owner.context)
        picture.setImageBitmap(self.draw_line(values, current, max(1, width), height))
        frame.addView(picture, jclass("android.widget.FrameLayout$LayoutParams")(-1, height))
        hits = LinearLayout(owner.context)
        hits.setOrientation(0)
        for part, value in zip(period.parts, values):
            slot = jclass("android.view.View")(owner.context)
            slot.setContentDescription("%s: %s" % (self.part_name(period, part), duration_text(value)))
            if value > 0:
                self.click(slot, self.open_part, period, part)
            hits.addView(slot, Params(0, -1, 1.0))
        frame.addView(hits, jclass("android.widget.FrameLayout$LayoutParams")(-1, height))
        at = Params(width, height)
        at.topMargin = _dp(16)
        self.body.addView(frame, at)
        labels = LinearLayout(owner.context)
        labels.setOrientation(0)
        for index, part in enumerate(period.parts):
            name = self.label(11, "textSecondary")
            name.setGravity(17)
            if period.kind == WEEK:
                name.setText(self.weekdays[index])
            elif period.kind == YEAR:
                name.setText(self.months[index][:3])
            elif part.day in (1, 8, 15, 22, 29):
                name.setText(str(part.day))
            labels.addView(name, Params(0, -2, 1.0))
        self.body.addView(labels, Params(width, -2))

    def draw_line(self, values, current, width, height):
        owner = self.owner
        Bitmap = jclass("android.graphics.Bitmap")
        Paint = jclass("android.graphics.Paint")
        ColorUtils = jclass("androidx.core.graphics.ColorUtils")
        bitmap = Bitmap.createBitmap(int(width), int(height), jclass("android.graphics.Bitmap$Config").ARGB_8888)
        canvas = jclass("android.graphics.Canvas")(bitmap)
        accent = owner.color("accent")
        muted = owner.color("textSecondary")
        count = max(1, len(values))
        slot = width / float(count)
        dense = count > 12
        radius = _dp(3.5) if dense else _dp(5)
        gap = radius + (_dp(2) if dense else _dp(4))
        pad_top, pad_bottom = _dp(10), _dp(10)
        span = height - pad_top - pad_bottom
        top = max(values) if values else 0.0
        grid = Paint(1)
        _paint_color(grid, ColorUtils.setAlphaComponent(muted, 40))
        grid.setStrokeWidth(float(max(1, _dp(1))))
        for share in (0.0, 0.5, 1.0):
            y = pad_top + span * share
            canvas.drawLine(0.0, float(y), float(width), float(y), grid)
        points = []
        for index, value in enumerate(values):
            x = slot * (index + 0.5)
            y = pad_top + span * (1.0 - (value / top if top > 0 else 0.0))
            points.append((x, y))
        line = Paint(1)
        _paint_color(line, ColorUtils.setAlphaComponent(accent, 150))
        line.setStrokeWidth(float(_dp(2.5)))
        line.setStrokeCap(jclass("android.graphics.Paint$Cap").ROUND)
        for (x1, y1), (x2, y2) in zip(points, points[1:]):
            dx, dy = x2 - x1, y2 - y1
            length = (dx * dx + dy * dy) ** 0.5
            if length <= 2 * gap + _dp(1):
                continue
            ux, uy = dx / length, dy / length
            canvas.drawLine(float(x1 + ux * gap), float(y1 + uy * gap), float(x2 - ux * gap), float(y2 - uy * gap), line)
        dot = Paint(1)
        for (x, y), value, now in zip(points, values, current):
            if now:
                _paint_color(dot, ColorUtils.setAlphaComponent(accent, 70))
                canvas.drawCircle(float(x), float(y), float(radius * 2.0), dot)
            _paint_color(dot, accent if value > 0 else ColorUtils.setAlphaComponent(muted, 110))
            canvas.drawCircle(float(x), float(y), float(radius if value > 0 or now else radius * 0.7), dot)
        return bitmap

    # -- names and moves

    def period_name(self, period):
        if period.kind == WEEK:
            first, last = period.parts[0], period.parts[-1]
            if first.month == last.month:
                return "%d–%d %s" % (first.day, last.day, self.months[last.month - 1])
            return "%d %s – %d %s" % (first.day, self.months[first.month - 1], last.day, self.months[last.month - 1])
        if period.kind == MONTH:
            return "%s %d" % (self.long_months[period.start.month - 1], period.start.year)
        return str(period.start.year)

    def part_name(self, period, part):
        if period.kind == YEAR:
            return self.long_months[part.month - 1]
        return "%d %s" % (part.day, self.months[part.month - 1])

    def choose(self, kind, back):
        self.kind, self.back_by = kind, back
        self.refresh()

    def open_part(self, period, part):
        if period.kind == YEAR:
            today = datetime.date.today()
            self.choose(MONTH, (today.year - part.year) * 12 + today.month - part.month)
            return
        self.owner.push(DayScreen(self.owner, self.store, part, self.part_name(period, part)))


class DayScreen(Screen):
    """One day's stretches of listening, each with its exact time."""

    def __init__(self, owner, store, day, title):
        sessions = store.sessions_of(day.isoformat())
        super().__init__(owner, title, duration_text(sum(s[1] for s in sessions)))
        LinearLayout = jclass("android.widget.LinearLayout")
        Params = jclass("android.widget.LinearLayout$LayoutParams")
        context = owner.context
        page = LinearLayout(context)
        page.setOrientation(1)
        page.addView(self.header())
        scroll = jclass("android.widget.ScrollView")(context)
        body = LinearLayout(context)
        body.setOrientation(1)
        body.setPadding(_dp(16), 0, _dp(16), _dp(24))
        scroll.addView(body)
        page.addView(scroll, Params(-1, 0, 1.0))
        self.view = page
        if not sessions:
            empty = self.label(15, "textSecondary")
            empty.setText(tr("В этот день музыка не играла."))
            body.addView(empty)
            return
        for start, seconds, key in sessions:
            title_text, artist = (store.songs.get(key) or ["", ""])[:2]
            row = LinearLayout(context)
            row.setOrientation(0)
            row.setGravity(16)
            when = self.label(14, "textSecondary")
            when.setText("%s–%s" % (time.strftime("%H:%M", time.localtime(start)), time.strftime("%H:%M", time.localtime(start + seconds))))
            row.addView(when, owner.params(96, 44))
            texts = LinearLayout(context)
            texts.setOrientation(1)
            name = self.label(15, "text")
            name.setText(title_text or tr("Без названия"))
            name.setSingleLine(True)
            texts.addView(name)
            if artist:
                who = self.label(13, "textSecondary")
                who.setText(artist)
                who.setSingleLine(True)
                texts.addView(who)
            row.addView(texts, Params(0, -2, 1.0))
            amount = self.label(13, "textSecondary")
            amount.setText(duration_text(seconds))
            row.addView(amount)
            body.addView(row, Params(-1, _dp(56)))
