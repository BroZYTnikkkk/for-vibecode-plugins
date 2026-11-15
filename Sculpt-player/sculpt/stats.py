# Sculpt Player for exteraGram. Copyright 2026 BroNik (@BroZYTnikkkk).

"""Listening statistics: how long music played, day by day and song by song, and every stretch of listening with
its exact time. Kept in the plugin's own data folder (stats.json), which clearing Telegram's cache does not touch.

The screen: a week, a month or a year as a chart of bars, the time in total, the songs and authors heard most; a
day's bar opens that day's stretches of listening, a month's bar in the year opens that month."""

import calendar
import datetime
import time

from client_utils import run_on_queue
from java import jclass

from .common import _dp, _log
from .i18n import tr
from .library_ui import Screen
from .music import local_path, split_artists

SESSION_GAP = 20.0  # seconds of silence that end one stretch of listening and start the next
SESSIONS_MAX = 20000
SAVE_EVERY = 60.0
TOP_SONGS = 10
TOP_ARTISTS = 5
WEEK, MONTH, YEAR = 0, 1, 2


def day_key(stamp):
    return time.strftime("%Y-%m-%d", time.localtime(stamp))


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
        self.saved_at = time.monotonic()
        self.dirty = False

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
        data = {"version": 1, "songs": dict(self.songs), "days": {k: dict(v) for k, v in self.days.items()},
                "sessions": [list(s) for s in self.sessions]}
        run_on_queue(lambda: self.plugin.music._save("stats.json", data))

    # -- reading, for the screen

    def total(self, days):
        return sum(sum(self.days.get(d, {}).values()) for d in days)

    def per_song(self, days):
        out = {}
        for d in days:
            for key, seconds in self.days.get(d, {}).items():
                out[key] = out.get(key, 0.0) + seconds
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
        bar.addView(self.icon_button(("msg_arrow_back", "ic_ab_back"), tr("Раньше"), self.choose, self.kind, self.back_by + 1),
                    owner.params(40, 40))
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
        under = self.label(14, "textSecondary")
        under.setText(tr("Песен: %d") % len(songs) if songs else tr("Пока тишина: статистика копится, пока играет музыка."))
        under.setSingleLine(False)
        self.body.addView(under)

        self.chart(period)
        if not songs:
            return
        self.section(tr("Песни"))
        for key, seconds in sorted(songs.items(), key=lambda kv: -kv[1])[:TOP_SONGS]:
            title, artist = (self.store.songs.get(key) or ["", ""])[:2]
            self.line(title or tr("Без названия"), artist, duration_text(seconds))
        artists = sorted(self.store.per_artist(songs).items(), key=lambda kv: -kv[1])[:TOP_ARTISTS]
        if artists:
            self.section(tr("Исполнители"))
            for name_text, seconds in artists:
                self.line(name_text, "", duration_text(seconds))

    def chart(self, period):
        """One bar per day (per month in a year), its height by the time; today, or this month, in the accent."""
        owner = self.owner
        Params = jclass("android.widget.LinearLayout$LayoutParams")
        LinearLayout = jclass("android.widget.LinearLayout")
        values = [self.store.total(period.days_of(part)) for part in period.parts]
        top = max(values) if values else 0.0
        accent = owner.color("accent")
        soft = jclass("androidx.core.graphics.ColorUtils").setAlphaComponent(accent, 90)
        height = _dp(150)
        bars = LinearLayout(owner.context)
        bars.setOrientation(0)
        bars.setPadding(0, _dp(16), 0, 0)
        labels = LinearLayout(owner.context)
        labels.setOrientation(0)
        today = datetime.date.today()
        gap = _dp(3) if len(values) > 12 else _dp(6)
        for index, (part, value) in enumerate(zip(period.parts, values)):
            slot = jclass("android.widget.FrameLayout")(owner.context)
            fill = jclass("android.view.View")(owner.context)
            current = (part.month == today.month and part.year == today.year) if period.kind == YEAR else part == today
            fill.setBackground(owner.rounded(accent if current else soft, _dp(4)))
            share = value / top if top > 0 else 0.0
            place = jclass("android.widget.FrameLayout$LayoutParams")(-1, max(_dp(3), int(height * share)))
            place.gravity = 80  # bottom
            slot.addView(fill, place)
            slot.setContentDescription("%s: %s" % (self.part_name(period, part), duration_text(value)))
            if value > 0:
                self.click(slot, self.open_part, period, part)
            at = Params(0, height, 1.0)
            at.setMarginStart(gap // 2)
            at.setMarginEnd(gap // 2)
            bars.addView(slot, at)
            name = self.label(11, "textSecondary")
            name.setGravity(17)
            if period.kind == WEEK:
                name.setText(self.weekdays[index])
            elif period.kind == YEAR:
                name.setText(self.months[index][:3])
            elif part.day in (1, 8, 15, 22, 29):
                name.setText(str(part.day))
            labels.addView(name, Params(0, -2, 1.0))
        self.body.addView(bars, Params(-1, -2))
        self.body.addView(labels, Params(-1, -2))

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
