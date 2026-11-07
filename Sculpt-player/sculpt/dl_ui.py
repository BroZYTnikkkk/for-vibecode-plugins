# SPDX-License-Identifier: LGPL-3.0-only
# Sculpt Player for exteraGram. Copyright 2026 BroNik (@BroZYTnikkkk).
# Search and downloads go through Mornye extensions (Mornye by zarzet, https://github.com/mornyeapp/Mornye, LGPL-3.0-only).

"""The Mornye tab's search for songs to download, albums and authors from a service, the downloads, their settings."""

import json
import re

from java import dynamic_proxy, jclass

from .common import SEARCH_HISTORY, _dp, _log, advanced
from .extensions import QUALITIES, STAGES, describe
from .ext_ui import ExtScreen
from .library_ui import TextChanged

URL = re.compile(r"^https?://", re.I)
SPLIT = re.compile(r",|&|;| feat\.| ft\.", re.I)
KINDS = {"album": "Альбом", "playlist": "Плейлист", "artist": "Исполнитель"}


class EditorAction(dynamic_proxy(jclass("android.widget.TextView$OnEditorActionListener"))):
    def __init__(self, action):
        super().__init__()
        self.action = action

    def onEditorAction(self, view, action_id, event):
        if self.action is not None:
            self.action()
        return True


def _key(title, artist):
    def clean(text):
        return re.sub(r"[\W_]+", "", str(text or "").casefold())
    return clean(artist) + "|" + clean(title)


def kind_of(item):
    kind = str(item.get("item_type") or "track").lower()
    return "track" if kind == "song" else kind


def mark_local(music, items):
    """Results the library already has (same author and title) get the path of the song on the phone."""
    local = {}
    # right after Telegram starts the library has not been read yet: its saved list stands in
    for track in music.tracks or music._load("library.json", []):
        local.setdefault(_key(track["title"], SPLIT.split(track["artist"])[0].strip()), track["path"])
        local[_key(track["title"], track["artist"])] = track["path"]
    for item in items or []:
        if isinstance(item, dict) and kind_of(item) == "track":
            first = SPLIT.split(item.get("artists") or "")[0].strip()
            path = local.get(_key(item.get("name"), item.get("artists"))) or local.get(_key(item.get("name"), first))
            if path:
                item["local_path"] = path
    return items


def seconds_of(item):
    try:
        ms = int(item.get("duration_ms") or 0)
        seconds = ms // 1000 if ms else int(item.get("duration") or 0)
    except (TypeError, ValueError):
        seconds = 0
    return "%d:%02d" % (seconds // 60, seconds % 60) if seconds else ""


def tracks_label(count):
    tail = count % 100
    word = "песен" if 11 <= tail <= 14 else {1: "песня", 2: "песни", 3: "песни", 4: "песни"}.get(count % 10, "песен")
    return "%d %s" % (count, word)


QUALITY_NAMES = {"LOSSLESS": ("FLAC Lossless", "16 бит, до 44,1 кГц"),
                 "HI_RES": ("FLAC высокого разрешения", "24 бит, до 96 кГц"),
                 "HI_RES_LOSSLESS": ("FLAC Max высокого разрешения", "24 бит, до 192 кГц")}
HEALTH_COLORS = {"online": 0xFF24D47A, "offline": 0xFFFF5A66}  # anything else: amber
HEALTH_AMBER = 0xFFFFC247
SECTIONS = (("artist", "Исполнители"), ("album", "Альбомы"), ("playlist", "Плейлисты"), ("track", "Песни"))
FILTER_ICONS = {"track": "msg_played", "song": "msg_played", "music": "msg_played", "album": "msg_media",
                "artist": "msg_contacts", "playlist": "msg_list", "video": "msg_video"}


def signed(color):
    """An ARGB color as Java's int: Python's 0xFF... is past its range."""
    return color - (1 << 32) if color >= (1 << 31) else color


class RemoteRows(ExtScreen):
    """Shared by the search and the album, playlist and author screens: rows of what a service returned."""

    def remote_image(self, item, round_image=False, size=48):
        owner = self.owner
        radius = _dp(size // 2 if round_image else 8)
        image = jclass("org.telegram.ui.Components.BackupImageView")(owner.context)
        image.setRoundRadius(radius)
        image.setBackground(owner.rounded(owner.color("surfaceContainer"), radius))
        url = item.get("cover_url") or item.get("images") or ""
        if isinstance(url, list):
            url = url[0] if url else ""
        if isinstance(url, dict):
            url = url.get("url") or ""
        if url:
            image.setImage(str(url), "96_96", None)
        return image

    def card(self, container, title=None):
        """A section: its name, then its rows on a rounded plate."""
        Params = jclass("android.widget.LinearLayout$LayoutParams")
        if title:
            head = self.label(20, "text", True)
            head.setText(title)
            place = Params(-1, -2)
            place.setMargins(_dp(20), _dp(20), _dp(20), _dp(8))
            container.addView(head, place)
        plate = jclass("android.widget.LinearLayout")(self.owner.context)
        plate.setOrientation(1)
        plate.setPadding(0, _dp(4), 0, _dp(4))
        plate.setBackground(self.owner.rounded(self.owner.color("surfaceContainer"), _dp(20)))
        place = Params(-1, -2)
        place.setMargins(_dp(12), 0, _dp(12), 0)
        container.addView(plate, place)
        return plate

    def item_rows(self, container, items):
        for item in items:
            if not isinstance(item, dict):
                continue
            kind = kind_of(item)
            if kind == "track":
                self.track_row(container, item)
                continue
            details = KINDS.get(kind, kind) + (" · %s" % item["artists"] if item.get("artists") and kind != "artist" else "")
            self.item_row(container, item.get("name") or "", details,
                          lambda i=item, k=kind: self.owner.open_remote(k, i.get("provider_id"), i.get("id"), i),
                          image=self.remote_image(item, kind == "artist"))

    def badge(self, text, role, outline=False):
        owner = self.owner
        view = self.label(11, role, True)
        view.setText(text)
        view.setPadding(_dp(6), _dp(1), _dp(6), _dp(1))
        if outline:
            frame = jclass("android.graphics.drawable.GradientDrawable")()
            frame.setCornerRadius(float(_dp(4)))
            frame.setStroke(_dp(1), owner.color(role))
            view.setBackground(frame)
        else:
            tint = jclass("androidx.core.graphics.ColorUtils").setAlphaComponent(owner.color("accent"), 40)
            view.setBackground(owner.rounded(tint, _dp(4)))
        return view

    def track_row(self, container, item, second=None, number=None):
        """Cover (or the number on an album), title, author (or what `second` says) with badges; a tap
        downloads it, or plays it if it is here; ⋯ for the rest."""
        owner = self.owner
        Params = jclass("android.widget.LinearLayout$LayoutParams")
        LinearLayout = jclass("android.widget.LinearLayout")
        local = bool(item.get("local_path"))
        row = LinearLayout(owner.context)
        row.setOrientation(0)
        row.setGravity(16)
        row.setPadding(_dp(12), _dp(8), _dp(4), _dp(8))
        row.setMinimumHeight(_dp(64))
        if number is not None:
            place_number = self.label(16, "textSecondary")
            place_number.setText(str(number))
            place_number.setGravity(17)
            row.addView(place_number, owner.params(36, 48))
        else:
            row.addView(self.remote_image(item), owner.params(48, 48))
        column = LinearLayout(owner.context)
        column.setOrientation(1)
        name = self.label(16, "text")
        name.setText(item.get("name") or "")
        column.addView(name)
        line = LinearLayout(owner.context)
        line.setOrientation(0)
        line.setGravity(16)
        artist = self.label(13, "textSecondary")
        artist.setText(second if second is not None else (item.get("artists") or ""))
        line.addView(artist, Params(-2, -2, 0.0))
        if item.get("explicit") is True or str(item.get("explicit")).lower() in ("1", "true"):
            at = Params(-2, -2)
            at.setMarginStart(_dp(6))
            line.addView(self.badge("E", "textSecondary", True), at)
        if item.get("audio_quality") and advanced(owner.plugin):
            at = Params(-2, -2)
            at.setMarginStart(_dp(6))
            line.addView(self.badge(str(item["audio_quality"]), "accent"), at)
        if local:
            folder = jclass("android.widget.ImageView")(owner.context)
            owner.set_icon(folder, ("msg_folders", "msg2_folder"))
            self.tint_icon(folder, "accent")
            folder.setContentDescription("Уже есть на телефоне")
            at = owner.params(16, 16)
            at.setMarginStart(_dp(6))
            line.addView(folder, at)
        column.addView(line)
        place = Params(0, -2, 1.0)
        place.setMarginStart(_dp(14))
        row.addView(column, place)
        if local:
            row.addView(self.icon_button(("msg_played", "player_play"), "Слушать с телефона", self.play_local, item), owner.params(40, 40))
        row.addView(self.icon_button(("ic_ab_other", "msg_more"), "Ещё: %s" % (item.get("name") or ""), self.track_menu, item, row), owner.params(40, 40))
        row.setBackground(owner.selector(0))
        self.click(row, self.track_pressed, item)
        self.long_click(row, lambda view: self.track_menu(item, view))
        row.setContentDescription("%s, %s%s" % (item.get("name") or "", item.get("artists") or "", ", уже есть на телефоне" if local else ""))
        container.addView(row, Params(-1, -2))

    def track_pressed(self, item):
        if item.get("local_path"):
            self.play_local(item)
        elif self.owner.plugin.get_setting("download_direct", False):
            self.download([item], False)
        else:
            self.pick_service(item)

    def play_local(self, item):
        track = self.owner.data.by_path.get(item["local_path"])
        if track is not None:
            self.owner.play([track], 0, item.get("name") or "")
        else:
            self.say("Песня ещё не в медиатеке: открой «Медиатеку», чтобы она нашлась.")

    def track_menu(self, item, anchor):
        owner = self.owner
        menu = owner.make_menu(anchor, False)
        later = owner.player.start_menu()
        icon = owner.resource
        if item.get("local_path"):
            menu.add(icon("msg_played"), "Слушать с телефона", later(lambda: (menu.dismiss(), self.play_local(item))))
        menu.add(icon("msg_download"), "Скачать из…", later(lambda: (menu.dismiss(), self.pick_service(item))))
        menu.add(icon("msg_download"), "Скачать основным сервисом", later(lambda: (menu.dismiss(), self.download([item], False))))
        menu.add(icon("msg_played"), "Скачать и слушать", later(lambda: (menu.dismiss(), self.download([item], True))))
        if item.get("album_id"):
            menu.add(icon("msg_media"), "Открыть альбом", later(lambda: (menu.dismiss(), owner.open_remote(
                "album", item.get("provider_id"), item["album_id"], {"name": item.get("album_name"), "cover_url": item.get("cover_url")}))))
        if item.get("artist_id"):
            menu.add(icon("msg_contacts"), "Открыть исполнителя", later(lambda: (menu.dismiss(), owner.open_remote(
                "artist", item.get("provider_id"), item["artist_id"], {"name": item.get("artists")}))))
        owner.player.show_menu(menu)

    def pick_service(self, item):
        DownloadSheet(self, item).show()

    def download(self, items, play, service=None, quality=None):
        tracks = [i for i in items if isinstance(i, dict) and kind_of(i) == "track"]
        if not tracks:
            return
        extensions = self.owner.plugin.extensions

        def task(manager):
            queue = extensions.downloads()
            for track in tracks:
                item = queue.add(track, service, quality)
                item["play"] = bool(play) and len(tracks) == 1
            return len(tracks)

        def done(count):
            if count == 1:
                self.say("Скачиваю «%s». Ход загрузки — в «Загрузках»." % (tracks[0].get("name") or "песню"))
            else:
                self.say("В очереди на скачивание: %s" % tracks_label(count))

        self.run(task, done)


BEST_ORDER = ("HI_RES_LOSSLESS", "HI_RES", "LOSSLESS")
SIMPLE_QUALITIES = (("LOSSLESS", "Лучшее"), ("HIGH", "Экономное, меньше места"))


def simple_qualities(options):
    """A service's qualities in two plain words: the best it has, and the lightest that still sounds good."""
    lossless = [q for q in options if q.get("kind") == "lossless"]
    lossy = [q for q in options if q.get("kind") == "lossy"]
    best = None
    for wanted in BEST_ORDER:
        best = next((q for q in lossless if str(q.get("id") or "").upper() == wanted), None)
        if best is not None:
            break
    best = best or (lossless[0] if lossless else (options[0] if options else None))
    result = []
    if best is not None:
        result.append({"id": best.get("id"), "simple": True, "label": "Лучшее качество",
                       "description": "Самый чистый звук. Файл больше: обычно 20–40 МБ на песню."})
    economy = next((q for q in lossy if q is not best), None)
    if economy is not None:
        result.append({"id": economy.get("id"), "simple": True, "label": "Экономное",
                       "description": "Меньше места: обычно 5–10 МБ на песню. На слух почти не отличить."})
    return result


class OnClick(dynamic_proxy(jclass("android.view.View$OnClickListener"))):
    def __init__(self, action):
        super().__init__()
        self.action = action

    def onClick(self, view):
        if self.action is not None:
            self.action()


class SheetClosed(dynamic_proxy(jclass("android.content.DialogInterface$OnDismissListener"))):
    def __init__(self, action):
        super().__init__()
        self.action = action

    def onDismiss(self, dialog):
        action, self.action = self.action, None
        if action is not None:
            action()


class DownloadSheet:
    """"Download from": the download services as chips with their health, then the chosen one's qualities."""

    def __init__(self, screen, item):
        self.screen = screen
        self.owner = screen.owner
        self.item = item
        self.sheet = None
        self.services = []
        self.health = {}
        self.chosen = ""
        self.chips = None
        self.qualities = None
        self.keep = []
        self.chip_views = []

    def show(self):
        def task(manager):
            services = []
            for ext in manager.priorities("download"):
                man = manager.manifest(ext)
                raw = man.raw if isinstance(man.raw, dict) else {}
                services.append({"id": ext, "name": man.display_name, "icon": manager.icon_path(ext),
                                 "qualities": [dict(q, kind=man.quality_kind(q)) for q in man.quality_options],
                                 "health": bool(raw.get("serviceHealth") or raw.get("service_health"))})
            return services, manager.default_service()

        self.screen.run(task, self.build)

    def build(self, data):
        self.services, default = data
        owner = self.owner
        if not self.services:
            self.screen.say("Нет включённых сервисов скачивания. Включи их в «Расширениях».")
            return
        ids = [s["id"] for s in self.services]
        self.chosen = default if default in ids else ids[0]
        Params = jclass("android.widget.LinearLayout$LayoutParams")
        LinearLayout = jclass("android.widget.LinearLayout")
        column = LinearLayout(owner.context)
        column.setOrientation(1)
        column.setPadding(0, _dp(8), 0, _dp(16))
        head = LinearLayout(owner.context)
        head.setOrientation(0)
        head.setGravity(16)
        head.setPadding(_dp(20), _dp(8), _dp(20), _dp(12))
        head.addView(self.screen.remote_image(self.item, size=56), owner.params(56, 56))
        names = LinearLayout(owner.context)
        names.setOrientation(1)
        title = owner.text_view(18, True)
        title.setTextColor(owner.color("text"))
        title.setText(self.item.get("name") or "")
        names.addView(title)
        artist = owner.text_view(14)
        artist.setTextColor(owner.color("textSecondary"))
        artist.setText(self.item.get("artists") or "")
        names.addView(artist)
        at = Params(0, -2, 1.0)
        at.setMarginStart(_dp(14))
        head.addView(names, at)
        column.addView(head)
        column.addView(self.heading("Скачать из"))
        self.chips = LinearLayout(owner.context)
        self.chips.setOrientation(1)
        self.chips.setPadding(_dp(16), 0, _dp(16), 0)
        column.addView(self.chips)
        column.addView(self.heading("Выбрать качество"))
        self.qualities = LinearLayout(owner.context)
        self.qualities.setOrientation(1)
        column.addView(self.qualities)
        scroll = jclass("android.widget.ScrollView")(owner.context)
        scroll.addView(column)
        self.sheet = jclass("org.telegram.ui.ActionBar.BottomSheet")(owner.context, False)
        self.sheet.setCustomView(scroll)
        self.sheet.setBackgroundColor(owner.color("background"))
        self.sheet.setOnDismissListener(SheetClosed(self.release))
        self.draw_chips()
        self.draw_qualities()
        self.sheet.show()
        extensions = owner.plugin.extensions
        for service in self.services:
            if service["health"]:
                ext = service["id"]
                extensions.work(lambda m, e=ext: extensions.health(e), lambda status, e=ext: self.got_health(e, status))

    def heading(self, text):
        label = self.owner.text_view(17, True)
        label.setTextColor(self.owner.color("text"))
        label.setText(text)
        label.setPadding(_dp(20), _dp(16), _dp(20), _dp(10))
        return label

    def got_health(self, ext, status):
        if self.sheet is None:
            return
        self.health[ext] = status
        self.draw_chips()

    def draw_chips(self):
        """Chips wrap onto new lines by their measured width."""
        owner = self.owner
        for view in self.chip_views:
            view.setOnClickListener(None)
        self.chip_views = []
        self.chips.removeAllViews()
        Params = jclass("android.widget.LinearLayout$LayoutParams")
        LinearLayout = jclass("android.widget.LinearLayout")
        width = int(owner.context.getResources().getDisplayMetrics().widthPixels) - _dp(32)
        spec = jclass("android.view.View$MeasureSpec").makeMeasureSpec(0, 0)
        line, used = None, 0
        for service in self.services:
            chip = self.chip(service)
            chip.measure(spec, spec)
            need = int(chip.getMeasuredWidth()) + _dp(8)
            if line is None or used + need > width:
                line = LinearLayout(owner.context)
                line.setOrientation(0)
                place = Params(-1, -2)
                place.bottomMargin = _dp(8)
                self.chips.addView(line, place)
                used = 0
            at = Params(-2, _dp(44))
            at.setMarginEnd(_dp(8))
            line.addView(chip, at)
            used += need

    def chip(self, service):
        owner = self.owner
        chosen = service["id"] == self.chosen
        chip = jclass("android.widget.LinearLayout")(owner.context)
        chip.setOrientation(0)
        chip.setGravity(16)
        chip.setPadding(_dp(14), 0, _dp(14), 0)
        tint = jclass("androidx.core.graphics.ColorUtils").setAlphaComponent(owner.color("accent"), 60 if chosen else 22)
        chip.setBackground(owner.rounded(tint, _dp(22)))
        if chosen:
            check = jclass("android.widget.ImageView")(owner.context)
            owner.set_icon(check, ("msg_text_check",))
            owner.tint(check, owner.color("accent"))
            chip.addView(check, owner.params(18, 18))
        if service["icon"]:
            bitmap = jclass("android.graphics.BitmapFactory").decodeFile(service["icon"])
            if bitmap is not None:
                image = jclass("org.telegram.ui.Components.BackupImageView")(owner.context)
                image.setRoundRadius(_dp(5))
                image.setImageBitmap(bitmap)
                at = owner.params(20, 20)
                at.setMarginStart(_dp(4) if chosen else 0)
                chip.addView(image, at)
        name = owner.text_view(15, chosen)
        name.setTextColor(owner.color("accent") if chosen else owner.color("text"))
        name.setText(service["name"])
        at = jclass("android.widget.LinearLayout$LayoutParams")(-2, -2)
        at.setMarginStart(_dp(6))
        chip.addView(name, at)
        description = service["name"]
        if service["health"] and service["id"] in self.health:
            status = self.health[service["id"]]
            dot = jclass("android.view.View")(owner.context)
            dot.setBackground(owner.rounded(signed(HEALTH_COLORS.get(status, HEALTH_AMBER)), _dp(4)))
            at = owner.params(8, 8)
            at.setMarginStart(_dp(8))
            chip.addView(dot, at)
            description += {"online": ", работает", "offline": ", не отвечает"}.get(status, ", работает с перебоями")
        chip.setContentDescription(description + (", выбран" if chosen else ""))
        chip.setOnClickListener(OnClick(lambda: self.choose(service["id"])))
        self.chip_views.append(chip)
        return chip

    def choose(self, ext):
        self.chosen = ext
        self.draw_chips()
        self.draw_qualities()

    def draw_qualities(self):
        owner = self.owner
        for view in self.keep:
            view.setOnClickListener(None)
        self.keep = []
        self.qualities.removeAllViews()
        service = next((s for s in self.services if s["id"] == self.chosen), None)
        options = list(service["qualities"]) if service else []
        if not advanced(owner.plugin):
            options = simple_qualities(options)
        if not options:
            options = [{"id": "", "label": "Лучшее доступное", "description": "Сервис сам выберет качество"}]
        for option in options:
            qid = str(option.get("id") or "")
            if option.get("simple"):
                label, description = option["label"], option["description"]
            else:
                label, description = QUALITY_NAMES.get(qid.upper(), (str(option.get("label") or qid), ""))
                description = str(option.get("description") or "") or description
            row = jclass("android.widget.LinearLayout")(owner.context)
            row.setOrientation(0)
            row.setGravity(16)
            row.setPadding(_dp(20), _dp(12), _dp(16), _dp(12))
            row.setMinimumHeight(_dp(64))
            icon = jclass("android.widget.ImageView")(owner.context)
            owner.set_icon(icon, ("msg_filled_data_music", "msg_played"))
            owner.tint(icon, owner.color("accent"))
            row.addView(icon, owner.params(24, 24))
            column = jclass("android.widget.LinearLayout")(owner.context)
            column.setOrientation(1)
            name = owner.text_view(16, True)
            name.setTextColor(owner.color("text"))
            name.setText(label)
            column.addView(name)
            if description:
                second = owner.text_view(13)
                second.setTextColor(owner.color("textSecondary"))
                second.setText(description)
                column.addView(second)
            at = jclass("android.widget.LinearLayout$LayoutParams")(0, -2, 1.0)
            at.setMarginStart(_dp(16))
            row.addView(column, at)
            arrow = jclass("android.widget.ImageView")(owner.context)
            owner.set_icon(arrow, ("msg_arrowright",))
            owner.tint(arrow, owner.color("textSecondary"))
            row.addView(arrow, owner.params(20, 20))
            row.setBackground(owner.selector(0))
            row.setContentDescription("Скачать в качестве %s" % label)
            row.setOnClickListener(OnClick(lambda q=qid or None: self.pick(q)))
            self.keep.append(row)
            self.qualities.addView(row)

    def pick(self, quality):
        service = self.chosen
        sheet, self.sheet = self.sheet, None
        if sheet is not None:
            sheet.dismiss()
        self.screen.download([self.item], False, service, quality)

    def release(self):
        for view in self.keep + self.chip_views:
            try:
                view.setOnClickListener(None)
            except Exception:
                pass
        self.keep = []
        self.chip_views = []
        self.sheet = None


class DownloadSearchScreen(RemoteRows):
    """Mornye's search: a title, a field with the service picker and a clear button, filter chips with "All",
    results in sections on plates. As the Search tab's first screen it has no back arrow and, before a search,
    shows the recent searches and a place for the mixes that come later."""

    def __init__(self, owner, root=False):
        self.root_tab = root
        self.field = None
        self.action = None
        self.watcher = None
        self.clear_button = None
        self.pill_view = None
        super().__init__(owner, "Поиск")
        self.providers = []
        self.provider = ""
        self.filter = None
        self.query = ""
        self.results = None
        self.page()
        Params = jclass("android.widget.LinearLayout$LayoutParams")
        self.content.addView(self.search_field(), self.field_place())
        scroller, self.filters = self.sideways()
        scroller.setPadding(_dp(16), _dp(4), _dp(16), _dp(4))
        self.content.addView(scroller, Params(-1, -2))
        self.start_body()
        self.note(self.body, "Загружаю…")
        self.run(self.load_providers, self.providers_loaded)

    def header(self, large=False, trailing=None):
        owner = self.owner
        row = jclass("android.widget.LinearLayout")(owner.context)
        row.setOrientation(0)
        row.setGravity(16)
        row.setPadding(_dp(8), _dp(8), _dp(8), _dp(4))
        if not self.root_tab:
            row.addView(self.icon_button(("ic_ab_back",), "Назад", owner.back), owner.params(40, 40))
        self.title_view = self.label(30, "text", True)
        self.title_view.setText("Поиск")
        at = jclass("android.widget.LinearLayout$LayoutParams")(0, -2, 1.0)
        at.setMarginStart(_dp(12 if self.root_tab else 8))
        row.addView(self.title_view, at)
        self.subtitle_view = owner.text_view(13)
        return row

    @staticmethod
    def field_place():
        place = jclass("android.widget.LinearLayout$LayoutParams")(-1, _dp(52))
        place.setMargins(_dp(16), _dp(4), _dp(16), _dp(8))
        return place

    def search_field(self):
        """The pill: a search icon with an arrow that picks the service, the field, a clear cross."""
        owner = self.owner
        pill = jclass("android.widget.LinearLayout")(owner.context)
        pill.setOrientation(0)
        pill.setGravity(16)
        pill.setPadding(_dp(8), 0, _dp(4), 0)
        self.pill_view = pill
        self.paint_pill()
        picker = jclass("android.widget.LinearLayout")(owner.context)
        picker.setOrientation(0)
        picker.setGravity(16)
        picker.setPadding(_dp(8), 0, _dp(4), 0)
        icon = jclass("android.widget.ImageView")(owner.context)
        owner.set_icon(icon, ("outline_search_1_24", "msg_search"))
        self.tint_icon(icon, "textSecondary")
        picker.addView(icon, owner.params(22, 22))
        arrow = jclass("android.widget.ImageView")(owner.context)
        owner.set_icon(arrow, ("arrow_more", "msg_arrow_more"))
        self.tint_icon(arrow, "textSecondary")
        picker.addView(arrow, owner.params(14, 14))
        picker.setContentDescription("Сервис поиска")
        picker.setBackground(owner.selector(_dp(16)))
        self.click(picker, self.provider_menu, picker)
        pill.addView(picker, jclass("android.widget.LinearLayout$LayoutParams")(-2, -1))
        self.field = jclass("android.widget.EditText")(owner.context)
        self.field.setHint("Песня, альбом, исполнитель или ссылка")
        self.field.setTextSize(1, 17.0)
        self.field.setSingleLine(True)
        self.field.setBackground(None)
        self.field.setPadding(_dp(10), 0, _dp(8), 0)
        self.field.setImeOptions(3)  # EditorInfo.IME_ACTION_SEARCH
        self.paint_field()
        self.action = EditorAction(lambda: self.guarded(self.search))
        self.field.setOnEditorActionListener(self.action)
        self.watcher = TextChanged(lambda text: self.clear_button.setVisibility(0 if text else 8))
        self.field.addTextChangedListener(self.watcher)
        pill.addView(self.field, jclass("android.widget.LinearLayout$LayoutParams")(0, -1, 1.0))
        self.clear_button = self.icon_button(("msg_close", "ic_close_white"), "Очистить", self.clear)
        self.clear_button.setVisibility(8)
        pill.addView(self.clear_button, owner.params(40, 40))
        return pill

    def paint_pill(self):
        self.pill_view.setBackground(self.owner.rounded(self.owner.color("surfaceContainer"), _dp(26)))

    def paint_field(self):
        self.field.setTextColor(self.owner.color("text"))
        self.field.setHintTextColor(self.owner.color("textSecondary"))

    def colors_changed(self):
        self.paint_field()
        self.paint_pill()

    def clear(self):
        self.field.setText("")
        self.query = ""
        self.results = None
        self.draw()
        self.open_keyboard()

    @staticmethod
    def load_providers(manager):
        providers = []
        for ext in manager.search_providers():
            man = manager.manifest(ext)
            behavior = man.search_behavior or {}
            filters = [{"id": str(f.get("id")), "label": str(f.get("label") or f.get("id"))}
                       for f in (behavior.get("filters") or []) if isinstance(f, dict)]
            providers.append({"id": ext, "name": man.display_name, "placeholder": behavior.get("placeholder") or "", "filters": filters})
        return providers, manager.search_provider(), len(manager.manifests)

    def providers_loaded(self, data):
        self.providers, self.provider, installed = data
        if not installed:
            self.clear_body()
            self.note(self.body, "Поиск и скачивание идут через расширения Mornye: Deezer, Qobuz, Tidal, YouTube Music, "
                                 "SoundCloud и другие. Установи нужные в каталоге.", size=15)
            button = self.pill("Открыть каталог", True, self.owner.open_catalog)
            place = jclass("android.widget.LinearLayout$LayoutParams")(-2, -2)
            place.setMargins(_dp(20), _dp(16), 0, 0)
            self.body.addView(button, place)
            return
        self.draw_filters()
        self.draw()
        if not self.root_tab:
            self.open_keyboard()  # a tab is opened to look around too: there the keyboard waits for a tap

    def refresh(self):
        """An extension was installed or removed: the search tab picks the services up again."""
        if self.root_tab and self.results is None:
            self.run(self.load_providers, self.providers_loaded)

    def tab_again(self):
        """A second press on the Search tab: ready for a new query."""
        if self.field is None:
            return
        self.field.selectAll()
        self.open_keyboard()

    # -- recent searches, kept in the plugin's settings

    def history(self):
        try:
            value = json.loads(self.owner.plugin.get_setting("search_history", "[]") or "[]")
            return [str(q) for q in value if isinstance(q, str) and q.strip()][:SEARCH_HISTORY]
        except Exception:
            return []

    def remember(self, query):
        queries = [query] + [q for q in self.history() if q.lower() != query.lower()]
        self.owner.plugin.set_setting("search_history", json.dumps(queries[:SEARCH_HISTORY], ensure_ascii=False))

    def forget_all(self):
        self.owner.plugin.set_setting("search_history", "[]")
        self.draw()

    def search_again(self, query):
        self.field.setText(query)
        self.field.setSelection(len(query))
        self.search()

    def draw_start(self):
        """Before a search: what was looked for lately, and the mixes that are a plan for now."""
        queries = self.history()
        if queries:
            plate = self.card(self.body, "Недавние")
            for query in queries:
                self.item_row(plate, query, None, lambda q=query: self.search_again(q), icons=("msg_recent", "msg_clock", "msg_search"))
            clear = self.pill("Очистить недавние", False, self.forget_all)
            place = jclass("android.widget.LinearLayout$LayoutParams")(-2, -2)
            place.setMargins(_dp(20), _dp(12), 0, 0)
            self.body.addView(clear, place)
        else:
            self.note(self.body, "Что послушаем? Ищи песни, альбомы и исполнителей или вставь ссылку на трек, альбом или плейлист.", size=15)
        plate = self.card(self.body, "Миксы и подборки")
        self.note(plate, "Появятся позже: подборки по жанрам и миксы из того, что ты слушаешь.", size=15, top=12)
        spacer = jclass("android.view.View")(self.owner.context)
        plate.addView(spacer, jclass("android.widget.LinearLayout$LayoutParams")(-1, _dp(12)))

    def current(self):
        return next((p for p in self.providers if p["id"] == self.provider), None)

    def provider_menu(self, anchor):
        owner = self.owner
        menu = owner.make_menu(anchor, False)
        later = owner.player.start_menu()
        check = owner.resource("msg_text_check")
        for provider in self.providers:
            menu.add(check if provider["id"] == self.provider else 0, provider["name"],
                     later(lambda p=provider["id"]: (menu.dismiss(), self.pick_provider(p))))
        owner.player.show_menu(menu)

    def draw_filters(self):
        self.filters.removeAllViews()
        Params = jclass("android.widget.LinearLayout$LayoutParams")
        current = self.current()
        if current is None:
            return
        self.field.setHint(current["placeholder"] or "Искать в %s" % current["name"])
        for option in [{"id": None, "label": "Все"}] + current["filters"]:
            chip = self.filter_chip(option, option["id"] == self.filter)
            at = Params(-2, _dp(40))
            at.setMarginEnd(_dp(8))
            self.filters.addView(chip, at)

    def filter_chip(self, option, chosen):
        owner = self.owner
        chip = jclass("android.widget.LinearLayout")(owner.context)
        chip.setOrientation(0)
        chip.setGravity(16)
        chip.setPadding(_dp(14), 0, _dp(16), 0)
        tint = jclass("androidx.core.graphics.ColorUtils").setAlphaComponent(owner.color("accent"), 60 if chosen else 22)
        chip.setBackground(owner.rounded(tint, _dp(20)))
        key = str(option["id"] or "").lower()
        icon_name = next((name for word, name in FILTER_ICONS.items() if word in key), None)
        if icon_name:
            icon = jclass("android.widget.ImageView")(owner.context)
            owner.set_icon(icon, (icon_name,))
            self.tint_icon(icon, "accent")
            at = owner.params(18, 18)
            at.setMarginEnd(_dp(6))
            chip.addView(icon, at)
        name = self.label(15, "accent" if chosen else "text", chosen)
        name.setText(option["label"])
        chip.addView(name)
        chip.setContentDescription(option["label"] + (", выбрано" if chosen else ""))
        self.click(chip, self.pick_filter, option["id"])
        return chip

    def pick_provider(self, provider):
        self.provider = provider
        self.filter = None
        self.draw_filters()
        if self.query:
            self.search()

    def pick_filter(self, filter_id):
        self.filter = filter_id
        self.draw_filters()
        if self.query:
            self.search()

    def search(self):
        query = str(self.field.getText()).strip()
        if len(query) < 2:
            return
        self.query = query
        self.close_keyboard()
        if self.root_tab and not URL.match(query):
            self.remember(query)
        self.results = "loading"
        self.draw()
        provider, filter_id, music = self.provider, self.filter, self.owner.data

        def task(manager):
            if URL.match(query):
                ext = manager.find_url_handler(query)
                if not ext:
                    raise RuntimeError("Ни одно расширение не понимает эту ссылку. Установи расширение того сервиса, откуда она.")
                return {"url": manager.provider_call(ext, "handleUrl", [query], 45000), "provider": ext}
            if provider:
                with manager.lock:
                    manager.state["search_provider"] = provider
                    manager.save_state()
            used, items = manager.search(query, filter_id, provider or None)
            return {"items": mark_local(music, list(items)[:120]), "provider": used}

        def failed(text):
            self.results = {"error": text}
            self.draw()

        self.run(task, self.found, failed)

    def found(self, result):
        self.results = result
        items = result.get("items") or []
        if items:
            marked = sum(1 for i in items if isinstance(i, dict) and i.get("local_path"))
            _log("download search: %d results, %d already here" % (len(items), marked))
        if result.get("provider") and not self.provider:
            self.provider = result["provider"]
            self.draw_filters()
        self.draw()

    def draw(self):
        self.clear_body()
        result = self.results
        if result is None:
            if self.root_tab:
                self.draw_start()
            else:
                self.note(self.body, "Что послушаем? Ищи песни, альбомы и исполнителей или вставь ссылку на трек, альбом или плейлист.", size=15)
            return
        if result == "loading":
            self.note(self.body, "Ищу «%s»…" % self.query, size=15)
            return
        if result.get("error"):
            self.note(self.body, "Не получилось найти. %s" % result["error"], size=15)
            return
        if "url" in result:
            self.draw_url(result.get("url") or {}, result.get("provider"))
            return
        items = [i for i in (result.get("items") or []) if isinstance(i, dict)]
        if not items:
            self.note(self.body, "Ничего не нашлось по «%s». Попробуй другой запрос или другой сервис." % self.query, size=15)
            return
        for kind, title in SECTIONS:
            group = [i for i in items if kind_of(i) == kind]
            if group:
                self.item_rows(self.card(self.body, title), group)

    def draw_url(self, value, ext):
        items = ([value["track"]] if isinstance(value.get("track"), dict) else []) + list(value.get("tracks") or [])
        mark_local(self.owner.data, items)
        if items:
            self.item_rows(self.card(self.body, "Песни"), items)
        for kind in ("album", "artist"):
            found = value.get(kind)
            if isinstance(found, dict):
                found.setdefault("item_type", kind)
                found.setdefault("provider_id", ext)
                self.item_rows(self.card(self.body, KINDS.get(kind)), [found])
                if not items:
                    self.owner.open_remote(kind, ext, found.get("id"), found, loaded=found)
                return
        if not items:
            self.note(self.body, "По ссылке ничего не нашлось.", size=15)

    def open_keyboard(self):
        if self.field is not None and self.alive:
            self.field.requestFocus()
            jclass("org.telegram.messenger.AndroidUtilities").showKeyboard(self.field)

    def close_keyboard(self):
        if self.field is not None:
            try:
                jclass("org.telegram.messenger.AndroidUtilities").hideKeyboard(self.field)
                self.field.clearFocus()
            except Exception:
                pass

    def dispose(self):
        self.close_keyboard()
        if self.action is not None:
            self.action.action = None
            try:
                self.field.setOnEditorActionListener(None)
            except Exception:
                pass
        if self.watcher is not None:
            self.watcher.action = None
            try:
                self.field.removeTextChangedListener(self.watcher)
            except Exception:
                pass
        super().dispose()


class DownloadsScreen(ExtScreen):
    """What is downloading, waiting, done or failed; rows keep their views while only the progress moves."""

    STATUS = {"queued": "В очереди", "done": "Скачано, уже в медиатеке", "cancelled": "Отменено"}

    def __init__(self, owner):
        super().__init__(owner, "Загрузки")
        self.page(self.icon_button(("msg_settings",), "Настройки скачивания", owner.open_download_settings))
        self.rows = {}
        self.names = {}
        self.signature = None
        self.start_body()
        self.note(self.body, "Загружаю…")
        owner.plugin.extensions.listeners.append(self.refresh)
        self.refresh()

    def refresh(self):
        extensions = self.owner.plugin.extensions

        def task(manager):
            self.names = {ext: man.display_name for ext, man in manager.manifests.items()}
            return extensions.downloads().snapshot()

        self.run(task, self.show)

    @staticmethod
    def needs_check(item):
        return item["status"] == "failed" and (item.get("error_type") == "verification_required"
                                               or "verification required" in str(item.get("error") or "").lower())

    def check(self, ext):
        from .verify import verify
        name = self.names.get(ext, ext)
        extensions = self.owner.plugin.extensions

        def again():
            def task(manager):
                queue = extensions.downloads()
                for item in queue.snapshot():
                    if self.needs_check(item) and item.get("service") == ext:
                        queue.retry(item["id"])

            self.run(task, lambda _: self.refresh())

        verify(self.owner.plugin, ext, name, self.say, again)

    def show(self, items):
        signature = tuple((i["id"], i["status"]) for i in items)
        if signature == self.signature:
            for item in items:
                parts = self.rows.get(item["id"])
                if parts is not None:
                    self.paint(parts, item)
            return
        self.signature = signature
        self.clear_body()
        self.rows = {}
        active = sum(1 for i in items if i["status"] in ("queued", "running"))
        self.set_subtitle("идёт: %d" % active if active else "")
        if not items:
            self.note(self.body, "Пока ничего не скачивалось. Найди песню в поиске вкладки Mornye: строка «Найти песню для скачивания».", size=15)
            return
        if any(i["status"] in ("done", "failed", "cancelled") for i in items):
            self.item_row(self.body, "Убрать завершённые", "Файлы останутся на телефоне.", self.clear_finished, icons=("msg_clear", "msg_delete"))
        for item in reversed(items):
            self.add_row(item)

    def add_row(self, item):
        owner = self.owner
        Params = jclass("android.widget.LinearLayout$LayoutParams")
        holder = jclass("android.widget.LinearLayout")(owner.context)
        holder.setOrientation(1)
        image = jclass("org.telegram.ui.Components.BackupImageView")(owner.context)
        image.setRoundRadius(_dp(6))
        image.setBackground(owner.rounded(owner.color("surfaceContainer"), _dp(6)))
        if item.get("cover"):
            image.setImage(str(item["cover"]), "96_96", None)
        status = item["status"]
        if status in ("queued", "running"):
            button = self.icon_button(("msg_close", "ic_close_white"), "Отменить загрузку", self.act, "cancel", item["id"])
        elif self.needs_check(item) and item.get("service"):
            button = self.pill("Проверить", True, lambda e=item["service"]: self.check(e))
            button.setContentDescription("Пройти проверку сессии сервиса")
        elif status in ("failed", "cancelled"):
            button = self.icon_button(("msg_retry", "msg_reset", "msg_redo"), "Скачать снова", self.act, "retry", item["id"])
        else:
            button = self.icon_button(("msg_delete",), "Убрать из списка", self.act, "remove", item["id"])
        action = (lambda: self.play(item["path"])) if status == "done" and item.get("path") else None
        self.item_row(holder, item.get("title") or "", item.get("artist") or "", action, image=image, trailing=button)
        status_line = self.label(13, "accent" if status == "failed" else "textSecondary")
        status_line.setSingleLine(False)
        status_line.setMaxLines(3)
        place = Params(-1, -2)
        place.setMargins(_dp(76), 0, _dp(16), 0)
        holder.addView(status_line, place)
        bar = jclass("android.widget.ProgressBar")(owner.context, None, 16842872)  # android.R.attr.progressBarStyleHorizontal
        bar.setMax(1000)
        bar.setProgressTintList(jclass("android.content.res.ColorStateList").valueOf(owner.color("accent")))
        place = Params(-1, _dp(4))
        place.setMargins(_dp(76), _dp(4), _dp(16), _dp(8))
        holder.addView(bar, place)
        self.body.addView(holder, Params(-1, -2))
        parts = {"status": status_line, "bar": bar}
        self.rows[item["id"]] = parts
        self.paint(parts, item)

    def paint(self, parts, item):
        status = item["status"]
        if status == "running":
            stage = STAGES.get(item.get("stage") or "", "Скачиваю")
            percent = int(round((item.get("progress") or 0.0) * 100))
            parts["status"].setText("%s… %d%%" % (stage, percent) if percent else "%s…" % stage)
        elif self.needs_check(item):
            name = self.names.get(item.get("service") or "", item.get("service") or "Сервис")
            parts["status"].setText("Сервис «%s» просит пройти проверку сессии. Нажми «Проверить»: откроется его страница, "
                                    "после проверки загрузка начнётся снова." % name)
        elif status == "failed":
            parts["status"].setText("Не скачалось. %s" % describe(item.get("error") or "неизвестная ошибка"))
        else:
            parts["status"].setText(self.STATUS.get(status, status))
        running = status == "running"
        parts["bar"].setVisibility(0 if running else 8)
        if running:
            parts["bar"].setProgress(int((item.get("progress") or 0.0) * 1000))

    def act(self, what, item_id):
        extensions = self.owner.plugin.extensions
        self.run(lambda m: getattr(extensions.downloads(), what)(item_id), lambda _: self.refresh())

    def clear_finished(self):
        extensions = self.owner.plugin.extensions
        self.run(lambda m: extensions.downloads().clear_finished(), lambda _: self.refresh())

    def play(self, path):
        track = self.owner.data.by_path.get(path)
        if track is None:
            self.say("Песни ещё нет в медиатеке: она появится через пару секунд после скачивания.")
            return
        self.owner.play([track], 0, "Скачанное")

    def dispose(self):
        listeners = self.owner.plugin.extensions.listeners
        if self.refresh in listeners:
            listeners.remove(self.refresh)
        super().dispose()


class DownloadSettingsScreen(ExtScreen):
    """Which service downloads, in what quality, what comes next when it fails, and whose metadata wins."""

    def __init__(self, owner):
        super().__init__(owner, "Скачивание")
        self.page()
        self.start_body()
        self.note(self.body, "Загружаю…")
        self.refresh()

    def refresh(self):
        def task(manager):
            names = {ext: man.display_name for ext, man in manager.manifests.items()}
            return {"names": names, "download": manager.priorities("download"), "metadata": manager.priorities("metadata"),
                    "service": manager.default_service(), "quality": manager.state.get("quality") or "LOSSLESS",
                    "fallback": manager.state.get("auto_fallback", True), "search": manager.state.get("search_provider") or "",
                    "searchers": manager.search_providers()}

        self.run(task, self.show)

    def show(self, data):
        self.clear_body()
        names = data["names"]

        def name(ext):
            return names.get(ext, ext)

        plugin = self.owner.plugin
        full = advanced(plugin)
        self.choice("Основной сервис скачивания", name(data["service"]) if data["service"] else "Нет включённых",
                    [(ext, name(ext)) for ext in data["download"]], data["service"], lambda v: self.save("default_service", v))
        qualities = list(QUALITIES) if full else list(SIMPLE_QUALITIES)
        current = dict(qualities).get(data["quality"]) or ("Лучшее" if data["quality"] in BEST_ORDER else "Экономное")
        self.choice("Качество", current, qualities, data["quality"], lambda v: self.save("quality", v))
        direct = self.switch(plugin.get_setting("download_direct", False),
                             lambda on: plugin.set_setting("download_direct", bool(on)), "Качать сразу основным сервисом")
        self.item_row(self.body, "Качать сразу основным сервисом",
                      "Нажатие на песню в поиске скачивает её без вопроса «Скачать из».", trailing=direct)
        switch = self.switch(data["fallback"], lambda on: self.save("auto_fallback", on), "Запасные сервисы")
        self.item_row(self.body, "Запасные сервисы", "Если основной сервис не нашёл песню, пробовать следующие по порядку.", trailing=switch)
        if not full:
            self.note(self.body, "Сервис поиска, порядок сервисов и приоритет метаданных — в расширенном режиме: Настройки → Звук.",
                      size=13, top=16)
            return
        searchers = [("", "Автоматически")] + [(ext, name(ext)) for ext in data["searchers"]]
        self.choice("Сервис поиска", name(data["search"]) if data["search"] else "Автоматически", searchers, data["search"],
                    lambda v: self.save("search_provider", v))
        self.order("Порядок сервисов скачивания", "download", data["download"], name,
                   "Сверху тот, кого пробовать первым, когда основной не справился.")
        self.order("Приоритет метаданных", "metadata", data["metadata"], name,
                   "Чьи название, альбом, обложка и теги берутся первыми при поиске и скачивании.")

    def choice(self, label, current, options, value, chosen):
        row, _, _ = self.item_row(self.body, label, current, None)
        row.setBackground(self.owner.selector(0))
        self.click(row, self.menu, row, options, value, chosen)

    def menu(self, row, options, value, chosen):
        owner = self.owner
        menu = owner.make_menu(row, False)
        later = owner.player.start_menu()
        check = owner.resource("msg_text_check")
        for key, label in options:
            menu.add(check if key == value else 0, label, later(lambda k=key: (menu.dismiss(), chosen(k))))
        owner.player.show_menu(menu)

    def order(self, title, kind, ids, name, hint):
        self.section(self.body, title)
        self.note(self.body, hint, size=12, top=0)
        if not ids:
            self.note(self.body, "Нет включённых расширений этого вида.", size=14)
            return
        for index, ext in enumerate(ids):
            buttons = jclass("android.widget.LinearLayout")(self.owner.context)
            buttons.setOrientation(0)
            if index > 0:
                buttons.addView(self.icon_button(("msg_go_up",), "Выше: %s" % name(ext), self.move, kind, ids, index, -1), self.owner.params(40, 40))
            if index < len(ids) - 1:
                buttons.addView(self.icon_button(("msg_go_down",), "Ниже: %s" % name(ext), self.move, kind, ids, index, 1), self.owner.params(40, 40))
            self.item_row(self.body, "%d. %s" % (index + 1, name(ext)), "", trailing=buttons)

    def move(self, kind, ids, index, step):
        order = list(ids)
        order[index], order[index + step] = order[index + step], order[index]
        self.run(lambda m: m.set_priority(kind, order), lambda _: self.refresh())

    def save(self, key, value):
        def task(manager):
            with manager.lock:
                manager.state[key] = value
                manager.save_state()

        self.run(task, lambda _: self.refresh())
