# SPDX-License-Identifier: LGPL-3.0-only
# Sculpt Player for exteraGram. Copyright 2026 BroNik (@BroZYTnikkkk).
# Search and downloads go through Mornye extensions (Mornye by zarzet, https://github.com/mornyeapp/Mornye, LGPL-3.0-only).

"""The Mornye tab's search for songs to download, albums and authors from a service, the downloads, their settings."""

import re

from java import dynamic_proxy, jclass

from .common import _dp, _log
from .extensions import QUALITIES, STAGES, describe
from .ext_ui import ExtScreen

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


class RemoteRows(ExtScreen):
    """Shared by the search and the album, playlist and author screens: rows of what a service returned."""

    def remote_image(self, item, round_image=False):
        owner = self.owner
        radius = _dp(20 if round_image else 6)
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

    def item_rows(self, container, items):
        for item in items:
            if not isinstance(item, dict):
                continue
            kind = kind_of(item)
            if kind == "track":
                self.track_row(container, item)
                continue
            details = KINDS.get(kind, kind) + (" · %s" % item["artists"] if item.get("artists") else "")
            self.item_row(container, item.get("name") or "", details,
                          lambda i=item, k=kind: self.owner.open_remote(k, i.get("provider_id"), i.get("id"), i),
                          image=self.remote_image(item, kind == "artist"))

    def track_row(self, container, item):
        details = item.get("artists") or ""
        if item.get("album_name"):
            details += " · " + item["album_name"]
        local = bool(item.get("local_path"))
        end = self.label(13, "accent" if local else "textSecondary", local)
        end.setText("есть" if local else seconds_of(item))
        holder = {}
        row, _, _ = self.item_row(container, item.get("name") or "", details, lambda: self.track_pressed(item, holder["row"]),
                                  image=self.remote_image(item), trailing=end)
        holder["row"] = row
        self.long_click(row, lambda view: self.track_menu(item, view))
        if local:
            row.setContentDescription("%s, уже есть на телефоне" % (item.get("name") or ""))

    def track_pressed(self, item, row):
        if item.get("local_path"):
            self.play_local(item)
        else:
            self.track_menu(item, row)

    def play_local(self, item):
        track = self.owner.data.by_path.get(item["local_path"])
        if track is not None:
            self.owner.play([track], 0, item.get("name") or "")

    def track_menu(self, item, anchor):
        owner = self.owner
        menu = owner.make_menu(anchor, False)
        later = owner.player.start_menu()
        icon = owner.resource
        if item.get("local_path"):
            menu.add(icon("msg_played"), "Слушать с телефона", later(lambda: (menu.dismiss(), self.play_local(item))))
        menu.add(icon("msg_download"), "Скачать и слушать", later(lambda: (menu.dismiss(), self.download([item], True))))
        menu.add(icon("msg_download"), "Скачать", later(lambda: (menu.dismiss(), self.download([item], False))))
        if item.get("album_id"):
            menu.add(icon("msg_media"), "Открыть альбом", later(lambda: (menu.dismiss(), owner.open_remote(
                "album", item.get("provider_id"), item["album_id"], {"name": item.get("album_name"), "cover_url": item.get("cover_url")}))))
        if item.get("artist_id"):
            menu.add(icon("msg_contacts"), "Открыть исполнителя", later(lambda: (menu.dismiss(), owner.open_remote(
                "artist", item.get("provider_id"), item["artist_id"], {"name": item.get("artists")}))))
        owner.player.show_menu(menu)

    def download(self, items, play):
        tracks = [i for i in items if isinstance(i, dict) and kind_of(i) == "track"]
        if not tracks:
            return
        extensions = self.owner.plugin.extensions

        def task(manager):
            queue = extensions.downloads()
            for track in tracks:
                item = queue.add(track)
                item["play"] = bool(play) and len(tracks) == 1
            return len(tracks)

        def done(count):
            if count == 1:
                self.say("Скачиваю «%s». Ход загрузки — в «Загрузках»." % (tracks[0].get("name") or "песню"))
            else:
                self.say("В очереди на скачивание: %s" % tracks_label(count))

        self.run(task, done)


class DownloadSearchScreen(RemoteRows):
    """A query or a link; results from the chosen service; a tap on a song downloads it, or plays it if it is here."""

    def __init__(self, owner):
        self.field = None
        self.action = None
        super().__init__(owner, "Поиск песен")
        self.providers = []
        self.provider = ""
        self.filter = None
        self.query = ""
        self.results = None
        self.page()
        Params = jclass("android.widget.LinearLayout$LayoutParams")
        scroller, self.chips = self.sideways()
        scroller.setPadding(_dp(16), _dp(4), _dp(16), _dp(4))
        self.content.addView(scroller, Params(-1, -2))
        scroller2, self.filters = self.sideways()
        scroller2.setPadding(_dp(16), 0, _dp(16), _dp(4))
        self.content.addView(scroller2, Params(-1, -2))
        self.start_body()
        self.note(self.body, "Загружаю…")
        self.run(self.load_providers, self.providers_loaded)

    def header(self, large=False, trailing=None):
        owner = self.owner
        row = jclass("android.widget.LinearLayout")(owner.context)
        row.setOrientation(0)
        row.setGravity(16)
        row.setPadding(_dp(8), _dp(8), _dp(8), _dp(8))
        row.addView(self.icon_button(("ic_ab_back",), "Назад", owner.back), owner.params(40, 40))
        self.field = jclass("android.widget.EditText")(owner.context)
        self.field.setHint("Песня, альбом, исполнитель или ссылка")
        self.field.setTextSize(1, 17.0)
        self.field.setSingleLine(True)
        self.field.setBackground(None)
        self.field.setPadding(_dp(12), 0, _dp(8), 0)
        self.field.setImeOptions(3)  # EditorInfo.IME_ACTION_SEARCH
        self.field.setTextColor(owner.color("text"))
        self.field.setHintTextColor(owner.color("textSecondary"))
        self.action = EditorAction(lambda: self.guarded(self.search))
        self.field.setOnEditorActionListener(self.action)
        row.addView(self.field, jclass("android.widget.LinearLayout$LayoutParams")(0, _dp(48), 1.0))
        row.addView(self.icon_button(("outline_search_1_24", "msg_search"), "Искать", self.search), owner.params(40, 40))
        self.title_view = owner.text_view(13)
        self.subtitle_view = owner.text_view(13)
        return row

    def colors_changed(self):
        self.field.setTextColor(self.owner.color("text"))
        self.field.setHintTextColor(self.owner.color("textSecondary"))

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
        self.draw_chips()
        self.draw()
        self.open_keyboard()

    def draw_chips(self):
        self.chips.removeAllViews()
        self.filters.removeAllViews()
        Params = jclass("android.widget.LinearLayout$LayoutParams")
        for provider in self.providers:
            chip = self.pill(provider["name"], provider["id"] == self.provider, lambda p=provider["id"]: self.pick_provider(p))
            at = Params(-2, -2)
            at.setMarginEnd(_dp(8))
            self.chips.addView(chip, at)
        current = next((p for p in self.providers if p["id"] == self.provider), None)
        if current and current["placeholder"]:
            self.field.setHint(current["placeholder"])
        for option in (current["filters"] if current else []):
            chip = self.pill(option["label"], option["id"] == self.filter, lambda f=option["id"]: self.pick_filter(f))
            at = Params(-2, -2)
            at.setMarginEnd(_dp(8))
            self.filters.addView(chip, at)

    def pick_provider(self, provider):
        self.provider = provider
        self.filter = None
        self.draw_chips()
        if self.query:
            self.search()

    def pick_filter(self, filter_id):
        self.filter = None if filter_id == self.filter else filter_id
        self.draw_chips()
        if self.query:
            self.search()

    def search(self):
        query = str(self.field.getText()).strip()
        if not query:
            return
        self.query = query
        self.close_keyboard()
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
        if items and isinstance(items[0], dict):
            marked = sum(1 for i in items if isinstance(i, dict) and i.get("local_path"))
            sample = {k: items[0][k] for k in ("name", "artists", "item_type", "album_name") if k in items[0]}
            _log("download search: %d results, %d already here; first: %s" % (len(items), marked, sample))
        if result.get("provider") and not self.provider:
            self.provider = result["provider"]
            self.draw_chips()
        self.draw()

    def draw(self):
        self.clear_body()
        result = self.results
        if result is None:
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
        items = result.get("items") or []
        if not items:
            self.note(self.body, "Ничего не нашлось по «%s». Попробуй другой запрос или другой сервис." % self.query, size=15)
            return
        self.item_rows(self.body, items)

    def draw_url(self, value, ext):
        items = ([value["track"]] if isinstance(value.get("track"), dict) else []) + list(value.get("tracks") or [])
        mark_local(self.owner.data, items)
        self.item_rows(self.body, items)
        for kind in ("album", "artist"):
            found = value.get(kind)
            if isinstance(found, dict):
                found.setdefault("item_type", kind)
                found.setdefault("provider_id", ext)
                self.item_rows(self.body, [found])
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
        super().dispose()


class RemoteScreen(RemoteRows):
    """An album, a playlist or an author from a service: its songs, a button to download them all."""

    METHODS = {"album": "getAlbum", "playlist": "getPlaylist", "artist": "getArtist"}

    def __init__(self, owner, kind, ext, item_id, preview, loaded=None):
        preview = preview or {}
        super().__init__(owner, preview.get("name") or KINDS.get(kind, ""), KINDS.get(kind, ""))
        self.kind, self.ext, self.item_id = kind, ext, item_id
        self.page()
        self.start_body()
        if loaded is not None and (loaded.get("tracks") or loaded.get("top_tracks") or loaded.get("releases")):
            self.show(loaded)
            return
        self.note(self.body, "Загружаю…", size=15)
        method = self.METHODS.get(kind)

        def failed(text):
            self.clear_body()
            self.note(self.body, "Не получилось открыть. %s" % text, size=15)

        self.run(lambda m: m.provider_call(ext, method, [item_id], 45000), self.show, failed)

    def show(self, data):
        self.clear_body()
        if not isinstance(data, dict):
            self.note(self.body, "Сервис ничего не вернул.", size=15)
            return
        kind = self.kind
        tracks = list(data.get("top_tracks") or []) if kind == "artist" else list(data.get("tracks") or [])
        for track in tracks:
            if isinstance(track, dict):
                if not track.get("cover_url") and data.get("cover_url"):
                    track["cover_url"] = data["cover_url"]
                track.setdefault("provider_id", self.ext)
        mark_local(self.owner.data, tracks)
        if data.get("name"):
            self.title_view.setText(data["name"])
        parts = [KINDS.get(kind, "")]
        if kind != "artist":
            if data.get("artists"):
                parts.append(data["artists"])
            if data.get("release_date"):
                parts.append(str(data["release_date"])[:4])
            if tracks:
                parts.append(tracks_label(len(tracks)))
        self.set_subtitle(" · ".join(p for p in parts if p))
        if tracks:
            button = self.pill("Скачать популярное" if kind == "artist" else "Скачать всё", True, lambda: self.download(tracks, False))
            place = jclass("android.widget.LinearLayout$LayoutParams")(-2, -2)
            place.setMargins(_dp(20), _dp(8), 0, _dp(8))
            self.body.addView(button, place)
            if kind == "artist":
                self.section(self.body, "Популярное")
            self.item_rows(self.body, tracks)
        releases = list(data.get("releases") or data.get("albums") or []) if kind == "artist" else []
        if releases:
            self.section(self.body, "Релизы")
            for release in releases:
                if isinstance(release, dict):
                    release.setdefault("item_type", "album")
                    release.setdefault("provider_id", self.ext)
            self.item_rows(self.body, releases)
        if not tracks and not releases:
            self.note(self.body, "Здесь пусто.", size=15)


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
        super().__init__(owner, "Настройки скачивания")
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

        self.choice("Основной сервис скачивания", name(data["service"]) if data["service"] else "Нет включённых",
                    [(ext, name(ext)) for ext in data["download"]], data["service"], lambda v: self.save("default_service", v))
        self.choice("Качество", dict(QUALITIES).get(data["quality"], data["quality"]), list(QUALITIES), data["quality"],
                    lambda v: self.save("quality", v))
        switch = self.switch(data["fallback"], lambda on: self.save("auto_fallback", on), "Запасные сервисы")
        self.item_row(self.body, "Запасные сервисы", "Если основной сервис не нашёл песню, пробовать следующие по порядку.", trailing=switch)
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
