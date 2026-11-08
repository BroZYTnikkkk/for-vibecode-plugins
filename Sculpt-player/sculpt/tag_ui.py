# SPDX-License-Identifier: LGPL-3.0-only
# Sculpt Player for exteraGram. Copyright 2026 BroNik (@BroZYTnikkkk).
# Metadata search goes through Mornye extensions (Mornye by zarzet, https://github.com/mornyeapp/Mornye, LGPL-3.0-only).

"""The tag editor with hints from the services, and the list of songs whose tags need a look."""

import os
import re

from java import jclass

from . import tags
from .common import UNKNOWN_ARTIST, _dp
from .dl_ui import EditorAction, RemoteRows, seconds_of
from .library_ui import TextChanged

SEARCH_PROVIDERS = 2  # metadata providers asked, in priority order, until this many answered
CANDIDATES = 8
PILL_KEYS = ("title", "artist", "album", "albumartist", "date", "genre", "tracknumber", "discnumber", "isrc", "cover")
PILL_NAMES = {"title": "Название", "artist": "Исполнитель", "album": "Альбом", "albumartist": "Исполнитель альбома",
              "date": "Год", "genre": "Жанр", "tracknumber": "Дорожка", "discnumber": "Диск", "isrc": "ISRC", "cover": "Обложка"}


def broken(text):
    """Letters a wrong encoding turned into question marks: "??" in a row, or more question marks than a title has."""
    text = text or ""
    return "??" in text or text.count("?") >= 3


def needs_look(track):
    """A song whose tags are likely wrong or missing: no album, no real author, a "?" left by a broken encoding."""
    title, artist = track.get("title") or "", track.get("artist") or ""
    return (not track.get("album") or not artist or artist == UNKNOWN_ARTIST or broken(title) or broken(artist)
            or title == os.path.splitext(os.path.basename(track["path"]))[0])


class TagScreen(RemoteRows):
    """A song's tags: as they are ("было") and as they will be. "Search the internet" at the top, folded, finds the
    song in the services; the tag pills choose which tags a found version fills."""

    def __init__(self, owner, path):
        super().__init__(owner, "Теги")
        self.path = path
        self.track = owner.data.by_path.get(path, {})
        self.before = tags.read(path)
        self.fields = {}
        self.cover_url = None
        self.saving = False
        self.query_field = None
        self.query_action = None
        self.open = False
        self.searched = False
        self.chosen = {key for key in PILL_KEYS if self.is_empty(key)}
        self.page()
        self.set_subtitle(os.path.basename(path))
        self.build_search()
        self.start_body()
        self.build_fields()

    def is_empty(self, key):
        """Empty for "choose the empty ones": nothing or a zero (what an M4A stores for no number); the cover when
        the file has none."""
        if key == "cover":
            known, jpg = self.owner.data.covers.cached(self.path)
            return bool(known) and jpg is None
        return str(self.before.get(key) or "").strip() in ("", "0", "0/0")

    # -- "search the internet"

    def build_search(self):
        owner = self.owner
        Params = jclass("android.widget.LinearLayout$LayoutParams")
        head = jclass("android.widget.LinearLayout")(owner.context)
        head.setOrientation(0)
        head.setGravity(16)
        head.setPadding(_dp(20), _dp(12), _dp(16), _dp(12))
        head.setBackground(owner.rounded(owner.color("surfaceContainer"), _dp(20)))
        icon = jclass("android.widget.ImageView")(owner.context)
        owner.set_icon(icon, ("outline_search_1_24", "msg_search"))
        self.tint_icon(icon, "accent")
        head.addView(icon, owner.params(22, 22))
        title = self.label(16, "text", True)
        title.setText("Поиск в интернете")
        at = Params(0, -2, 1.0)
        at.setMarginStart(_dp(12))
        head.addView(title, at)
        self.fold_arrow = jclass("android.widget.ImageView")(owner.context)
        owner.set_icon(self.fold_arrow, ("arrow_more", "msg_arrow_more"))
        self.tint_icon(self.fold_arrow, "textSecondary")
        head.addView(self.fold_arrow, owner.params(20, 20))
        head.setContentDescription("Поиск в интернете, развернуть")
        self.click(head, self.toggle_search)
        place = Params(-1, -2)
        place.setMargins(_dp(12), _dp(4), _dp(12), _dp(4))
        self.content.addView(head, place)
        self.search_box = jclass("android.widget.LinearLayout")(owner.context)
        self.search_box.setOrientation(1)
        self.search_box.setVisibility(8)
        self.content.addView(self.search_box, Params(-1, -2))
        pill = jclass("android.widget.LinearLayout")(owner.context)
        pill.setOrientation(0)
        pill.setGravity(16)
        pill.setPadding(_dp(16), 0, _dp(4), 0)
        pill.setBackground(owner.rounded(owner.color("surfaceContainer"), _dp(24)))
        self.query_field = jclass("android.widget.EditText")(owner.context)
        artist = self.before.get("artist") or self.track.get("artist") or ""
        name = self.before.get("title") or self.track.get("title") or os.path.splitext(os.path.basename(self.path))[0]
        self.query_field.setText(("%s %s" % (artist, name)).strip() if artist != UNKNOWN_ARTIST else name)
        self.query_field.setTextSize(1, 15.0)
        self.query_field.setSingleLine(True)
        self.query_field.setBackground(None)
        self.query_field.setImeOptions(3)
        self.query_field.setTextColor(owner.color("text"))
        self.query_field.setHintTextColor(owner.color("textSecondary"))
        self.query_field.setHint("Исполнитель и название")
        self.query_action = EditorAction(lambda: self.guarded(self.search))
        self.query_field.setOnEditorActionListener(self.query_action)
        pill.addView(self.query_field, Params(0, -1, 1.0))
        pill.addView(self.icon_button(("outline_search_1_24", "msg_search"), "Искать", self.search), owner.params(40, 40))
        place = Params(-1, _dp(48))
        place.setMargins(_dp(16), _dp(8), _dp(16), _dp(4))
        self.search_box.addView(pill, place)
        label = self.label(13, "textSecondary")
        label.setText("Что взять из найденного:")
        place = Params(-1, -2)
        place.setMargins(_dp(20), _dp(10), _dp(20), _dp(6))
        self.search_box.addView(label, place)
        self.pills = jclass("android.widget.LinearLayout")(owner.context)
        self.pills.setOrientation(1)
        self.pills.setPadding(_dp(16), 0, _dp(16), 0)
        self.search_box.addView(self.pills, Params(-1, -2))
        quick = jclass("android.widget.LinearLayout")(owner.context)
        quick.setOrientation(0)
        quick.setPadding(_dp(16), _dp(4), _dp(16), _dp(4))
        for text, action in (("Выбрать всё", self.choose_all), ("Убрать всё", self.choose_none), ("Выбрать пустые", self.choose_empty)):
            at = Params(-2, -2)
            at.setMarginEnd(_dp(8))
            quick.addView(self.pill(text, False, action), at)
        scroller = jclass("android.widget.HorizontalScrollView")(owner.context)
        scroller.setHorizontalScrollBarEnabled(False)
        scroller.addView(quick)
        self.search_box.addView(scroller, Params(-1, -2))
        self.hints = jclass("android.widget.LinearLayout")(owner.context)
        self.hints.setOrientation(1)
        self.search_box.addView(self.hints, Params(-1, -2))
        self.draw_pills()

    def toggle_search(self):
        self.open = not self.open
        self.search_box.setVisibility(0 if self.open else 8)
        self.fold_arrow.setRotation(180.0 if self.open else 0.0)
        if self.open and not self.searched:
            self.search()

    def draw_pills(self):
        owner = self.owner
        Params = jclass("android.widget.LinearLayout$LayoutParams")
        self.pills.removeAllViews()
        width = int(owner.context.getResources().getDisplayMetrics().widthPixels) - _dp(32)
        spec = jclass("android.view.View$MeasureSpec").makeMeasureSpec(0, 0)
        line, used = None, 0
        for key in PILL_KEYS:
            chosen = key in self.chosen
            chip = self.pill(PILL_NAMES[key], chosen, lambda k=key: self.flip(k))
            chip.setContentDescription("%s, %s" % (PILL_NAMES[key], "брать" if chosen else "не брать"))
            chip.measure(spec, spec)
            need = int(chip.getMeasuredWidth()) + _dp(8)
            if line is None or used + need > width:
                line = jclass("android.widget.LinearLayout")(owner.context)
                line.setOrientation(0)
                place = Params(-1, -2)
                place.bottomMargin = _dp(8)
                self.pills.addView(line, place)
                used = 0
            at = Params(-2, -2)
            at.setMarginEnd(_dp(8))
            line.addView(chip, at)
            used += need

    def flip(self, key):
        self.chosen ^= {key}
        self.draw_pills()

    def choose_all(self):
        self.chosen = set(PILL_KEYS)
        self.draw_pills()

    def choose_none(self):
        self.chosen = set()
        self.draw_pills()

    def choose_empty(self):
        self.chosen = {key for key in PILL_KEYS if self.is_empty(key)}
        self.draw_pills()

    def search(self):
        query = str(self.query_field.getText()).strip()
        if not query:
            return
        self.searched = True
        try:
            jclass("org.telegram.messenger.AndroidUtilities").hideKeyboard(self.query_field)
        except Exception:
            pass
        self.hints.removeAllViews()
        self.note(self.hints, "Ищу «%s» в сервисах…" % query)
        length = int(self.track.get("duration") or 0)

        def task(manager):
            found, asked = [], 0
            for ext in manager.priorities("metadata"):
                try:
                    value = manager.provider_call(ext, "searchTracks", [query, 6], 30000)
                except Exception:
                    continue
                items = [i for i in (value.get("tracks") or []) if isinstance(i, dict)]
                service = manager.manifest(ext).display_name
                for item in items:
                    item["service_name"] = service
                found += items
                asked += 1 if items else 0
                if asked >= SEARCH_PROVIDERS:
                    break
            if length:
                # the same recording runs the same length: within ten seconds goes first
                found.sort(key=lambda i: abs(int(i.get("duration_ms") or 0) // 1000 - length) > 10)
            return found[:CANDIDATES]

        self.run(task, self.show_hints, lambda text: (self.hints.removeAllViews(), self.note(self.hints, "Не получилось найти. %s" % text)))

    def show_hints(self, items):
        self.hints.removeAllViews()
        if not items:
            self.note(self.hints, "Сервисы ничего не нашли. Измени запрос или впиши теги сам.")
            return
        plate = self.card(self.hints, "Найдено")
        for item in items:
            details = " · ".join(p for p in (item.get("artists"), item.get("album_name"), str(item.get("release_date") or "")[:4],
                                             seconds_of(item), item.get("service_name")) if p)
            self.item_row(plate, item.get("name") or "", details, lambda i=item: self.fill(i), image=self.remote_image(item))

    def fill(self, item):
        if not self.chosen:
            self.say("Отметь, что взять: пиллы над результатами.")
            return
        taken = 0
        for key, value in tags.from_item(item).items():
            if value and key in self.chosen and key in self.fields:
                self.fields[key].setText(value)
                taken += 1
        if "cover" in self.chosen and item.get("cover_url"):
            self.cover_url = str(item["cover_url"])
            self.paint_cover()
            taken += 1
        self.say("Взято из «%s»: %d. Проверь и нажми «Сохранить»." % (item.get("service_name") or "сервиса", taken))

    # -- the fields

    def add_field(self, container, key, label):
        """A tag's name, what it was, and the field that holds what it becomes."""
        owner = self.owner
        Params = jclass("android.widget.LinearLayout$LayoutParams")
        title = self.label(14, "text", True)
        title.setText(label)
        place = Params(-1, -2)
        place.setMargins(_dp(20), _dp(12), _dp(20), 0)
        container.addView(title, place)
        was = self.label(12, "textSecondary")
        before = self.before.get(key) or ""
        was.setText("было: %s" % ((before[:60] + "…") if len(before) > 60 else (before or "пусто")))
        place = Params(-1, -2)
        place.setMargins(_dp(20), 0, _dp(20), 0)
        container.addView(was, place)
        field = jclass("android.widget.EditText")(owner.context)
        field.setText(before)
        field.setTextSize(1, 16.0)
        if key in tags.MULTILINE:
            field.setSingleLine(False)
            field.setMaxLines(8)
        else:
            field.setSingleLine(True)
        field.setTextColor(owner.color("text"))
        field.setHintTextColor(owner.color("textSecondary"))
        field.setHint(label)
        field.setContentDescription(label)
        place = Params(-1, -2)
        place.setMargins(_dp(16), 0, _dp(16), 0)
        container.addView(field, place)
        self.fields[key] = field

    def toggle_advanced(self):
        shown = self.advanced_box.getVisibility() == 0
        self.advanced_box.setVisibility(8 if shown else 0)
        self.advanced_arrow.setRotation(0.0 if shown else 180.0)
        self.advanced_row.setContentDescription("Расширенные теги, %s" % ("развернуть" if shown else "свернуть"))

    def build_fields(self):
        owner = self.owner
        Params = jclass("android.widget.LinearLayout$LayoutParams")
        self.section(self.body, "Теги")
        for key, label in tags.MAIN_FIELDS:
            self.add_field(self.body, key, label)
        self.section(self.body, "Обложка")
        self.cover_row = jclass("android.widget.LinearLayout")(owner.context)
        self.cover_row.setOrientation(0)
        self.cover_row.setGravity(16)
        self.cover_row.setPadding(_dp(20), _dp(4), _dp(16), _dp(4))
        self.body.addView(self.cover_row, Params(-1, -2))
        self.paint_cover()
        # the rest of the tags, folded: most songs need only the main ones
        self.advanced_box = jclass("android.widget.LinearLayout")(owner.context)
        self.advanced_box.setOrientation(1)
        self.advanced_box.setVisibility(8)
        filled = [label for key, label in tags.ADVANCED_FIELDS if self.before.get(key)]
        hint = ("заполнено: %d из %d" % (len(filled), len(tags.ADVANCED_FIELDS))) if filled else "Номера, ISRC, композитор, лейбл, текст и другое"
        self.advanced_row, self.advanced_arrow = self.fold_header(self.body, ("menu_tag_edit", "msg_edit"),
                                                                  "Расширенные теги", hint, self.toggle_advanced)
        for key, label in tags.ADVANCED_FIELDS:
            self.add_field(self.advanced_box, key, label)
        self.body.addView(self.advanced_box, Params(-1, -2))
        save = self.pill("Сохранить", True, self.save)
        save.setContentDescription("Записать теги в файл")
        place = Params(-1, _dp(48))
        place.setMargins(_dp(20), _dp(24), _dp(20), _dp(8))
        self.body.addView(save, place)
        self.save_button = save
        self.note(self.body, "Теги записываются прямо в файл, вернуть прежние будет нельзя.", size=12, top=0)

    def paint_cover(self):
        owner = self.owner
        self.cover_row.removeAllViews()
        old = owner.cover_view(8, 72)
        owner.bind_cover(old, self.path, 72)
        self.cover_row.addView(old, owner.params(72, 72))
        if not self.cover_url:
            return
        arrow = self.label(20, "textSecondary")
        arrow.setText("→")
        arrow.setPadding(_dp(12), 0, _dp(12), 0)
        self.cover_row.addView(arrow)
        self.cover_row.addView(self.remote_image({"cover_url": self.cover_url}, size=72), owner.params(72, 72))
        undo = self.icon_button(("msg_close", "ic_close_white"), "Оставить прежнюю обложку", self.keep_cover)
        at = owner.params(40, 40)
        at.setMarginStart(_dp(12))
        self.cover_row.addView(undo, at)

    def keep_cover(self):
        self.cover_url = None
        self.paint_cover()

    # -- saving

    def values(self):
        return {key: str(field.getText()).strip() for key, field in self.fields.items()}

    def save(self):
        if self.saving:
            return
        values = self.values()
        changed = {key: value for key, value in values.items() if value != (self.before.get(key) or "")}
        cover_url = self.cover_url
        if not changed and not cover_url:
            self.say("Ничего не изменилось.")
            return
        self.saving = True
        self.save_button.setText("Сохраняю…")
        path = self.path

        def task(manager):
            cover = tags.fetch_cover(cover_url) if cover_url else None
            try:
                tags.save(path, changed, cover)
                self.owner.data.covers.forget(path)
            except PermissionError:
                return "permission"
            return "saved"

        def done(result):
            self.saving = False
            self.save_button.setText("Сохранить")
            if result == "permission":
                if tags.request_access(path):
                    self.say("Android спрашивает, можно ли изменить этот файл. Разреши и нажми «Сохранить» ещё раз.")
                else:
                    self.say("Android не дал изменить этот файл.")
                return
            self.before = values
            self.say("Теги записаны", "saved_messages")
            self.owner.data.scan()
            self.owner.back()

        def failed(text):
            self.saving = False
            self.save_button.setText("Сохранить")
            self.say("Теги не записаны. %s" % text)

        self.run(task, done, failed)

    def dispose(self):
        if self.query_action is not None:
            self.query_action.action = None
            try:
                self.query_field.setOnEditorActionListener(None)
            except Exception:
                pass
        super().dispose()
