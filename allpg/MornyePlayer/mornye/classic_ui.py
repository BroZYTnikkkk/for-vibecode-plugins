# SPDX-License-Identifier: LGPL-3.0-only
# Mornye Player for exteraGram. Copyright 2026 BroNik (@BroZYTnikkkk).
# Based on Mornye by zarzet (https://github.com/mornyeapp/Mornye), LGPL-3.0-only.

"""The classic dialog-based menu."""

import json
import random
import time
from client_utils import get_last_fragment, get_media_controller, run_on_queue
from ui.alert import AlertDialogBuilder
from ui.bulletin import BulletinHelper
from android.os import Handler, Looper
from android.text import TextWatcher
from android.util import TypedValue
from android.widget import EditText, LinearLayout, ScrollView, SeekBar, TextView
from android_utils import OnClickListener, OnLongClickListener, R, run_on_ui_thread
from .logs import log
from java import dynamic_proxy
from org.telegram.messenger import AndroidUtilities, UserConfig
from org.telegram.ui.ActionBar import Theme
from org.telegram.ui.Components import LayoutHelper
from .common import (
    EQ_CENTERS,
    EQ_PRESETS,
    EQ_PRESET_LABELS,
    MIX_CROSSFADE,
    _color,
    _dp,
    _fmt_time,
    _norm_key,
    _selected_account,
)
from .automix import audio_quality_label, message_file_path, message_meta
from .library import fetch_lyrics


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------


class _Watcher(dynamic_proxy(TextWatcher)):
    def __init__(self, fn):
        super().__init__()
        self.fn = fn

    def afterTextChanged(self, s):
        try:
            self.fn(str(s))
        except Exception as e:
            log("[Mornye] watcher: %s" % e)

    def beforeTextChanged(self, s, start, count, after):
        pass

    def onTextChanged(self, s, start, before, count):
        pass


class _SeekListener(dynamic_proxy(SeekBar.OnSeekBarChangeListener)):
    def __init__(self, on_change, on_stop):
        super().__init__()
        self.on_change = on_change
        self.on_stop = on_stop

    def onProgressChanged(self, bar, progress, from_user):
        if from_user:
            self.on_change(progress)

    def onStartTrackingTouch(self, bar):
        pass

    def onStopTrackingTouch(self, bar):
        self.on_stop()


class UI:
    def __init__(self, plugin):
        self.plugin = plugin
        self.lyrics_dialog = None

    @property
    def lib(self):
        return self.plugin.library

    @property
    def engine(self):
        return self.plugin.engine

    def activity(self):
        frag = get_last_fragment()
        return frag.getParentActivity() if frag is not None else None

    # -- view helpers -----------------------------------------------------

    def text(self, ctx, value, size=15, color_key=None, bold=False):
        tv = TextView(ctx)
        tv.setText(value)
        tv.setTextSize(TypedValue.COMPLEX_UNIT_DIP, float(size))
        tv.setTextColor(_color(color_key if color_key is not None else Theme.key_dialogTextBlack))
        if bold:
            tv.setTypeface(AndroidUtilities.bold())
        return tv

    def row(self, ctx, title, subtitle=None, on_click=None, on_long=None):
        box = LinearLayout(ctx)
        box.setOrientation(LinearLayout.VERTICAL)
        box.setPadding(_dp(21), _dp(9), _dp(21), _dp(9))
        box.addView(self.text(ctx, title, 15))
        if subtitle:
            box.addView(self.text(ctx, subtitle, 13, Theme.key_dialogTextGray2))
        try:
            box.setBackground(Theme.createSelectorDrawable(_color(Theme.key_listSelector), 2))
        except Exception:
            pass
        if on_click is not None:
            box.setOnClickListener(OnClickListener(lambda v: on_click()))
        if on_long is not None:
            box.setOnLongClickListener(OnLongClickListener(lambda v: (on_long(), True)[1]))
        return box

    def dialog(self, title, view=None, height=None, items=None, on_item=None):
        act = self.activity()
        if act is None:
            BulletinHelper.show_error("Mornye: нет активного экрана")
            return None
        b = AlertDialogBuilder(act)
        b.set_title(title)
        if view is not None:
            if height:
                b.set_view(view, height)
            else:
                b.set_view(view)
        if items is not None:
            b.set_items(items, lambda bld, which: (bld.dismiss(), on_item(which)))
        b.set_negative_button("Закрыть", lambda bld, w: bld.dismiss())
        b.show()
        return b

    def scroll_list(self, ctx):
        scroll = ScrollView(ctx)
        content = LinearLayout(ctx)
        content.setOrientation(LinearLayout.VERTICAL)
        scroll.addView(content)
        return scroll, content

    # -- main sheet -------------------------------------------------------

    def open_main(self):
        mc = get_media_controller()
        msg = mc.getPlayingMessageObject()
        header = "Ничего не играет"
        if msg is not None and msg.isMusic():
            title, artist = message_meta(msg)
            header = "%s — %s" % (artist, title)
            path = message_file_path(msg)
            label = audio_quality_label(path) if path else None
            if label:
                header += "\n" + label
        mix = ["выкл", "кроссфейд", "AutoMix"][self.plugin.get_setting("mix_mode", MIX_CROSSFADE)]
        items = [
            "Открыть плеер Mornye",
            "Библиотека (%d)" % len(self.lib.tracks),
            "Текст песни",
            "Эквалайзер",
            "Переход: %s" % mix,
            "Таймер сна",
            "Статистика",
            "Избранное: добавить/убрать текущий",
            "Сохранить текущий трек в библиотеку",
        ]
        actions = [
            self.plugin.open_app, self.open_library, self.open_lyrics, self.open_equalizer,
            self.cycle_mix, self.open_sleep, self.open_stats, self.toggle_current_favorite, self.save_current,
        ]
        act = self.activity()
        if act is None:
            return
        b = AlertDialogBuilder(act)
        b.set_title("Mornye")
        b.set_message(header)
        b.set_items(items, lambda bld, which: (bld.dismiss(), actions[which]()))
        b.set_negative_button("Закрыть", lambda bld, w: bld.dismiss())
        b.show()

    def cycle_mix(self):
        mode = (self.plugin.get_setting("mix_mode", MIX_CROSSFADE) + 1) % 3
        self.plugin.set_setting("mix_mode", mode)
        BulletinHelper.show_info("Mornye: переход — %s" % ["выключен", "кроссфейд", "AutoMix"][mode])

    def toggle_current_favorite(self):
        msg = get_media_controller().getPlayingMessageObject()
        path = message_file_path(msg) if msg is not None else None
        if not path:
            BulletinHelper.show_error("Mornye: трек ещё не скачан")
            return
        added = self.lib.toggle_favorite(path)
        BulletinHelper.show_success("Добавлено в избранное" if added else "Убрано из избранного")

    def save_current(self):
        msg = get_media_controller().getPlayingMessageObject()
        if msg is None or msg.getId() < 0:
            BulletinHelper.show_info("Mornye: этот трек уже в локальной библиотеке")
            return
        self.lib.save_message(msg)

    # -- library ----------------------------------------------------------

    def open_library(self, mode="songs", group=None):
        act = self.activity()
        if act is None:
            return
        if not self.lib.tracks:
            self.lib.request_permission(act)
            BulletinHelper.show_info("Mornye: сканирую музыку…")
            self.lib.scan(lambda n: (BulletinHelper.show_success("Найдено треков: %d" % n), self.open_library()) if n else BulletinHelper.show_info("Музыка не найдена. Проверьте доступ к файлам и папки в настройках."))
            return
        ctx = act
        root = LinearLayout(ctx)
        root.setOrientation(LinearLayout.VERTICAL)
        tabs = LinearLayout(ctx)
        tabs.setOrientation(LinearLayout.HORIZONTAL)
        tabs.setPadding(_dp(16), 0, _dp(16), _dp(4))
        search = EditText(ctx)
        search.setHint("Поиск")
        search.setSingleLine(True)
        search.setTextColor(_color(Theme.key_dialogTextBlack))
        search.setHintTextColor(_color(Theme.key_dialogTextGray2))
        root.addView(search, LayoutHelper.createLinear(-1, -2, 21, 0, 21, 4))
        root.addView(tabs, LayoutHelper.createLinear(-1, -2))
        scroll, content = self.scroll_list(ctx)
        root.addView(scroll, LayoutHelper.createLinear(-1, 380))
        state = {"mode": mode, "group": group, "query": ""}
        holder = {}

        def tracks_for():
            with self.lib.lock:
                tracks = list(self.lib.tracks)
            if state["mode"] == "favorites":
                tracks = [t for t in tracks if t["path"] in self.lib.favorites]
            elif state["mode"] == "history":
                by_path = {t["path"]: t for t in tracks}
                tracks = [by_path[h["path"]] for h in self.lib.history if h.get("path") in by_path]
            if state["group"] is not None:
                field, value = state["group"]
                tracks = [t for t in tracks if (t[field] or "") == value]
            q = _norm_key(state["query"])
            if q:
                tracks = [t for t in tracks if q in _norm_key("%s %s %s" % (t["title"], t["artist"], t["album"]))]
            return tracks

        def render():
            content.removeAllViews()
            if state["mode"] in ("artists", "albums") and state["group"] is None:
                field = "artist" if state["mode"] == "artists" else "album"
                groups = {}
                for t in tracks_for():
                    groups.setdefault(t[field] or "Без альбома", []).append(t)
                for name in sorted(groups, key=_norm_key)[:300]:
                    items = groups[name]
                    content.addView(self.row(ctx, name, "%d трек(ов)" % len(items),
                                             on_click=lambda n=name, f=field: open_group(f, n)))
                return
            tracks = tracks_for()
            if tracks:
                content.addView(self.row(ctx, "▶ Слушать все (%d)" % len(tracks), "↻ долгое нажатие — перемешать",
                                         on_click=lambda: (self.lib.play(tracks, 0), close()),
                                         on_long=lambda: (self.lib.play(random.sample(tracks, len(tracks)), 0), close())))
            for i, t in enumerate(tracks[:250]):
                star = "★ " if t["path"] in self.lib.favorites else ""
                sub = "%s · %s" % (t["artist"], _fmt_time(t.get("duration") or 0))
                content.addView(self.row(ctx, star + t["title"], sub,
                                         on_click=lambda i=i: (self.lib.play(tracks, i), close()),
                                         on_long=lambda t=t: self.track_menu(t, tracks)))
            if len(tracks) > 250:
                content.addView(self.row(ctx, "Показано 250 из %d, уточните поиск" % len(tracks)))
            if not tracks:
                content.addView(self.row(ctx, "Пусто"))

        def open_group(field, name):
            state["group"] = (field, name if name != "Без альбома" else "")
            render()

        def set_mode(m):
            state["mode"] = m
            state["group"] = None
            render()

        for label, m in (("Треки", "songs"), ("Артисты", "artists"), ("Альбомы", "albums"), ("★", "favorites"), ("История", "history")):
            tab = self.text(ctx, label, 14, Theme.key_dialogTextBlue2, bold=True)
            tab.setPadding(_dp(6), _dp(6), _dp(6), _dp(6))
            tab.setOnClickListener(OnClickListener(lambda v, m=m: set_mode(m)))
            tabs.addView(tab)

        debounce = Handler(Looper.getMainLooper())
        pending = R(render)

        def on_query(q):
            state["query"] = q
            debounce.removeCallbacks(pending)
            debounce.postDelayed(pending, 250)

        search.addTextChangedListener(_Watcher(on_query))
        render()
        b = AlertDialogBuilder(ctx)
        b.set_title("Библиотека")
        b.set_view(root)
        b.set_neutral_button("Обновить", lambda bld, w: (bld.dismiss(), self.lib.scan(lambda n: BulletinHelper.show_success("Найдено треков: %d" % n))))
        b.set_positive_button("M3U8", lambda bld, w: self._export(tracks_for()))
        b.set_negative_button("Закрыть", lambda bld, w: bld.dismiss())
        b.show()
        holder["b"] = b

        def close():
            try:
                holder["b"].dismiss()
            except Exception:
                pass

    def _export(self, tracks):
        try:
            path = self.lib.export_m3u(tracks, "Mornye %s" % time.strftime("%Y-%m-%d %H-%M"))
            BulletinHelper.show_success("Плейлист сохранён: %s" % path)
        except Exception as e:
            BulletinHelper.show_error("Не удалось сохранить: %s" % e)

    def track_menu(self, track, tracks):
        fav = "Убрать из избранного" if track["path"] in self.lib.favorites else "В избранное"
        items = ["Играть следующим", fav, "Отправить в Избранное (Saved Messages)", "Информация"]

        def on_item(which):
            if which == 0:
                self.lib.play_next(track)
                BulletinHelper.show_success("Будет играть следующим")
            elif which == 1:
                self.lib.toggle_favorite(track["path"])
            elif which == 2:
                from client_utils import send_audio
                send_audio(UserConfig.getInstance(_selected_account()).getClientUserId(), track["path"])
            elif which == 3:
                label = audio_quality_label(track["path"]) or ""
                self.dialog(track["title"], self.text(self.activity(), "%s\n%s\n%s\n\n%s" % (
                    track["artist"], track["album"], label, track["path"]), 14))

        self.dialog(track["title"], items=items, on_item=on_item)

    def open_lyrics(self):
        mc = get_media_controller()
        msg = mc.getPlayingMessageObject()
        if msg is None or not msg.isMusic():
            BulletinHelper.show_info("Mornye: сейчас ничего не играет")
            return
        act = self.activity()
        if act is None:
            return
        title, artist = message_meta(msg)
        duration = msg.getDuration()
        ctx = act
        scroll, content = self.scroll_list(ctx)
        content.setPadding(_dp(21), _dp(4), _dp(21), _dp(12))
        status = self.text(ctx, "Ищу текст на LRCLIB…", 15, Theme.key_dialogTextGray2)
        content.addView(status)
        b = AlertDialogBuilder(ctx)
        b.set_title("%s — %s" % (artist, title))
        b.set_view(scroll, 380)
        b.set_negative_button("Закрыть", lambda bld, w: bld.dismiss())
        b.show()
        state = {"views": [], "lines": [], "current": -1, "alive": True}
        handler = Handler(Looper.getMainLooper())

        def follow():
            if not state["alive"]:
                return
            try:
                dlg = b.get_dialog()
                if dlg is None or not dlg.isShowing():
                    state["alive"] = False
                    return
                player = self.engine.main_player()
                if player is not None and state["lines"]:
                    pos = player.getCurrentPosition()
                    idx = -1
                    for i, (ms, _) in enumerate(state["lines"]):
                        if ms <= pos:
                            idx = i
                        else:
                            break
                    if idx != state["current"]:
                        if 0 <= state["current"] < len(state["views"]):
                            state["views"][state["current"]].setTextColor(_color(Theme.key_dialogTextGray2))
                        if 0 <= idx < len(state["views"]):
                            v = state["views"][idx]
                            v.setTextColor(_color(Theme.key_dialogTextBlack))
                            scroll.smoothScrollTo(0, max(0, v.getTop() - _dp(120)))
                        state["current"] = idx
            except Exception:
                pass
            handler.postDelayed(state["runnable"], 300)

        def show(data):
            content.removeAllViews()
            if not data:
                content.addView(self.text(ctx, "Текст не найден", 15, Theme.key_dialogTextGray2))
                return
            for ms, line in data["lines"]:
                tv = self.text(ctx, line or "♪", 18 if data["synced"] else 16,
                               Theme.key_dialogTextGray2 if data["synced"] else Theme.key_dialogTextBlack, bold=data["synced"])
                tv.setPadding(0, _dp(5), 0, _dp(5))
                if data["synced"]:
                    tv.setOnClickListener(OnClickListener(lambda v, ms=ms: self._seek_ms(ms)))
                content.addView(tv)
                state["views"].append(tv)
            credit = self.text(ctx, "\nТексты: lrclib.net", 12, Theme.key_dialogTextGray2)
            content.addView(credit)
            if data["synced"]:
                state["lines"] = data["lines"]
                state["runnable"] = R(follow)
                follow()

        run_on_queue(lambda: (lambda d: run_on_ui_thread(lambda: show(d)))(fetch_lyrics(title, artist, duration)))

    def _seek_ms(self, ms):
        mc = get_media_controller()
        msg = mc.getPlayingMessageObject()
        if msg is not None:
            try:
                mc.seekToProgressMs(msg, int(ms))
            except Exception:
                player = self.engine.main_player()
                if player is not None:
                    player.seekTo(int(ms))

    # -- equalizer --------------------------------------------------------

    def open_equalizer(self):
        act = self.activity()
        if act is None:
            return
        ctx = act
        scroll, content = self.scroll_list(ctx)
        content.setPadding(_dp(21), _dp(4), _dp(21), _dp(8))
        gains = self.plugin.custom_eq()
        preset = self.plugin.get_setting("eq_preset", 0)
        if preset < len(EQ_PRESETS):
            gains = list(EQ_PRESETS[preset][1])
        content.addView(self.text(ctx, "Полосы ±12 дБ. Изменение ползунка включает пресет «Свой».", 13, Theme.key_dialogTextGray2))
        labels = []

        def band_label(i):
            hz = EQ_CENTERS[i]
            name = ("%g кГц" % (hz / 1000)) if hz >= 1000 else ("%g Гц" % hz)
            return "%s: %+d дБ" % (name, round(gains[i]))

        def on_change(i, value):
            gains[i] = value - 12
            labels[i].setText(band_label(i))

        def on_stop():
            self.plugin.set_setting("eq_custom", json.dumps(gains))
            self.plugin.set_setting("eq_preset", len(EQ_PRESETS))
            self.plugin.set_setting("eq_enabled", True)
            self.engine.reapply_fx()

        for i in range(len(EQ_CENTERS)):
            label = self.text(ctx, band_label(i), 14)
            labels.append(label)
            content.addView(label)
            bar = SeekBar(ctx)
            bar.setMax(24)
            bar.setProgress(int(round(gains[i])) + 12)
            bar.setOnSeekBarChangeListener(_SeekListener(lambda p, i=i: on_change(i, p), on_stop))
            content.addView(bar)

        def pick_preset(bld, w):
            bld.dismiss()
            self.dialog("Пресет", items=EQ_PRESET_LABELS, on_item=lambda which: (
                self.plugin.set_setting("eq_preset", which),
                self.plugin.set_setting("eq_enabled", True),
                self.engine.reapply_fx(),
                BulletinHelper.show_success("Эквалайзер: %s" % EQ_PRESET_LABELS[which])))

        enabled = self.plugin.get_setting("eq_enabled", False)
        b = AlertDialogBuilder(ctx)
        b.set_title("Эквалайзер" + ("" if enabled else " (выключен)"))
        b.set_view(scroll, 380)
        b.set_positive_button("Пресеты", pick_preset)
        b.set_neutral_button("Выключить" if enabled else "Включить", lambda bld, w: (
            bld.dismiss(), self.plugin.set_setting("eq_enabled", not enabled), self.engine.reapply_fx()))
        b.set_negative_button("Закрыть", lambda bld, w: bld.dismiss())
        b.show()

    # -- sleep timer ------------------------------------------------------

    def open_sleep(self):
        options = [("Выключить таймер", 0, False), ("15 минут", 15, False), ("30 минут", 30, False),
                   ("45 минут", 45, False), ("1 час", 60, False), ("1,5 часа", 90, False), ("После этого трека", 0, True)]
        left = self.engine.sleep_at - time.time() if self.engine.sleep_at else 0
        title = "Таймер сна" + (" (осталось %s)" % _fmt_time(left) if left > 0 else "")

        def on_item(which):
            _, minutes, eot = options[which]
            self.engine.set_sleep(minutes, eot)
            if minutes or eot:
                BulletinHelper.show_success("Таймер сна: %s" % options[which][0].lower())
            else:
                BulletinHelper.show_info("Таймер сна выключен")

        self.dialog(title, items=[o[0] for o in options], on_item=on_item)

    # -- stats ------------------------------------------------------------

    def open_stats(self):
        s = self.lib.stats
        hours = s.get("seconds", 0.0) / 3600.0
        lines = ["Всего прослушано: %.1f ч, засчитано %d прослушиваний (от 30 секунд)." % (hours, s.get("plays", 0))]
        week = 0.0
        for i in range(7):
            day = time.strftime("%Y-%m-%d", time.localtime(time.time() - i * 86400))
            week += s.get("days", {}).get(day, 0.0)
        lines.append("За 7 дней: %.1f ч" % (week / 3600.0))
        tracks = sorted(s.get("tracks", {}).values(), key=lambda t: (t.get("plays", 0), t.get("seconds", 0)), reverse=True)[:10]
        artists = sorted(s.get("artists", {}).values(), key=lambda a: (a.get("plays", 0), a.get("seconds", 0)), reverse=True)[:10]
        lines.append("\nТоп треков:")
        for n, t in enumerate(tracks, 1):
            lines.append("%d. %s — %s (%d)" % (n, t["artist"], t["title"], t.get("plays", 0)))
        lines.append("\nТоп исполнителей:")
        for n, a in enumerate(artists, 1):
            lines.append("%d. %s (%d, %.0f мин)" % (n, a["name"], a.get("plays", 0), a.get("seconds", 0) / 60.0))
        act = self.activity()
        if act is None:
            return
        scroll, content = self.scroll_list(act)
        content.setPadding(_dp(21), _dp(4), _dp(21), _dp(8))
        content.addView(self.text(act, "\n".join(lines), 14))
        self.dialog("Статистика прослушиваний", scroll, 380)
