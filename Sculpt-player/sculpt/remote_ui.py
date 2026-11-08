# SPDX-License-Identifier: LGPL-3.0-only
# Sculpt Player for exteraGram. Copyright 2026 BroNik (@BroZYTnikkkk).
# The layout follows Mornye's artist and album pages (Mornye by zarzet, https://github.com/mornyeapp/Mornye, LGPL-3.0-only).

"""An author, an album or a playlist from a service, laid out the way Mornye shows them: a large picture fading
into the page, the name over its lower edge, round buttons, then the songs and the releases."""

import random

from java import dynamic_proxy, jarray, jclass, jfloat, jint

from .i18n import plural, tr
from .common import _dp, advanced
from .dl_ui import KINDS, RemoteRows, mark_local, tracks_label
from .music import find_group

RELEASE_TYPES = {"album": tr("Альбом"), "single": tr("Сингл"), "ep": "EP", "compilation": tr("Сборник")}
SHELVES = (("album", tr("Альбомы")), ("single", tr("Синглы и EP")), ("compilation", tr("Сборники")))
SHELF_TILE = 140  # dp of a release cover on the shelves that scroll sideways


def listeners_text(value):
    try:
        count = int(value or 0)
    except (TypeError, ValueError):
        return ""
    if count <= 0:
        return ""
    if count >= 1000000:
        number = ("%.1f" % (count / 1000000.0)).rstrip("0").rstrip(".").replace(".", ",") + tr(" млн")
        word = tr("слушателей")
    elif count >= 1000:
        number = tr("%d тыс.") % (count // 1000)
        word = tr("слушателей")
    else:
        number = str(count)
        word = plural(count, tr("слушатель"), tr("слушателя"), tr("слушателей"))
    return tr("%s %s в месяц") % (number, word)


def year_of(item):
    value = str(item.get("release_date") or item.get("year") or "")[:4]
    return value if value.isdigit() else ""


def release_type(item):
    kind = str(item.get("album_type") or item.get("type") or "album").lower()
    return "single" if kind == "ep" else (kind if kind in RELEASE_TYPES else "album")


def release_line(item):
    kind = str(item.get("album_type") or item.get("type") or "album").lower()
    return " · ".join(p for p in (RELEASE_TYPES.get(kind, ""), year_of(item)) if p)


def image_url(item):
    for key in ("header_image", "cover_url", "images", "image_url", "cover_art"):
        url = item.get(key)
        if isinstance(url, list):
            url = url[0] if url else ""
        if isinstance(url, dict):
            url = url.get("url") or ""
        if url:
            return str(url)
    return ""


def total_minutes(tracks):
    seconds = 0
    for track in tracks:
        try:
            ms = int(track.get("duration_ms") or 0)
            seconds += ms // 1000 if ms else int(track.get("duration") or 0)
        except (TypeError, ValueError):
            pass
    minutes = (seconds + 30) // 60
    if not minutes:
        return ""
    if minutes >= 60:
        return tr("%d ч %d мин") % (minutes // 60, minutes % 60)
    return tr("%d мин") % minutes


class Scrolled(dynamic_proxy(jclass("android.view.View$OnScrollChangeListener"))):
    def __init__(self, screen):
        super().__init__()
        self.screen = screen

    def onScrollChange(self, view, x, y, old_x, old_y):
        if self.screen is not None:
            self.screen.guarded(self.screen.scrolled, y)


class RemoteScreen(RemoteRows):
    """An album, a playlist or an author from a service."""

    METHODS = {"album": "getAlbum", "playlist": "getPlaylist", "artist": "getArtist"}

    def __init__(self, owner, kind, ext, item_id, preview, loaded=None):
        preview = dict(preview or {})
        super().__init__(owner, preview.get("name") or KINDS.get(kind, ""), KINDS.get(kind, ""))
        self.kind, self.ext, self.item_id = kind, ext, item_id
        self.data = None
        self.local = []  # the songs of this author or album that are on the phone
        self.local_group = None
        self.build_page()
        self.start_body()
        if loaded is not None and (loaded.get("tracks") or loaded.get("top_tracks") or loaded.get("releases")):
            self.show(loaded)
            return
        self.draw_header(preview, loading=True)
        method = self.METHODS.get(kind)

        def failed(text):
            self.clear_body()
            self.draw_header(preview, loading=None)
            self.note(self.body, tr("Не получилось открыть. %s") % text, size=15, top=16)

        self.run(lambda m: m.provider_call(ext, method, [item_id], 45000), self.show, failed)

    # -- the page: a scrolling column under a back button that stays put

    def build_page(self):
        owner = self.owner
        FrameLayout = jclass("android.widget.FrameLayout")
        page = FrameLayout(owner.context)
        scroll = jclass("android.widget.ScrollView")(owner.context)
        scroll.setVerticalScrollBarEnabled(False)
        scroll.setOverScrollMode(2)
        self.content = jclass("android.widget.LinearLayout")(owner.context)
        self.content.setOrientation(1)
        self.content.setPadding(0, 0, 0, _dp(24))
        scroll.addView(self.content)
        page.addView(scroll, FrameLayout.LayoutParams(-1, -1))
        # Mornye's bar: once the picture has gone up, a bar with the name comes in under the back button, so the
        # button never hangs over the covers of the rows
        self.bar = jclass("android.widget.LinearLayout")(owner.context)
        self.bar.setOrientation(0)
        self.bar.setGravity(16)
        self.bar.setPadding(_dp(68), 0, _dp(16), 0)
        self.bar_title = self.label(18, "text", True)
        self.bar.addView(self.bar_title, jclass("android.widget.LinearLayout$LayoutParams")(0, -2, 1.0))
        self.bar.setAlpha(0.0)
        self.paint_bar()
        page.addView(self.bar, FrameLayout.LayoutParams(-1, _dp(60)))
        self.scroll_listener = Scrolled(self)
        scroll.setOnScrollChangeListener(self.scroll_listener)
        self.scroll = scroll
        self.hero_height = 0
        back = jclass("android.widget.ImageView")(owner.context)
        owner.set_icon(back, ("ic_ab_back",))
        back.setScaleType(jclass("android.widget.ImageView$ScaleType").CENTER)
        back.setContentDescription(tr("Назад"))
        back.setBackground(owner.rounded(jclass("androidx.core.graphics.ColorUtils").setAlphaComponent(-16777216, 90), _dp(22)))
        owner.tint(back, -1)
        self.click(back, owner.back)
        place = FrameLayout.LayoutParams(_dp(44), _dp(44))
        place.setMargins(_dp(12), _dp(8), 0, 0)
        page.addView(back, place)
        self.view = page
        # stand-ins for the shared screen's header, which this page does without
        self.title_view = owner.text_view(13)
        self.subtitle_view = owner.text_view(13)

    def paint_bar(self):
        colors = self.owner.colors
        if colors is not None:
            self.bar.setBackgroundColor(jclass("androidx.core.graphics.ColorUtils").setAlphaComponent(colors.background, 245))

    def colors_changed(self):
        self.paint_bar()

    def scrolled(self, y):
        """The bar shows over the last part of the picture's way up and stays while the page is scrolled."""
        start = max(0, self.hero_height - _dp(140))
        alpha = max(0.0, min(1.0, (y - start) / float(_dp(60))))
        if abs(self.bar.getAlpha() - alpha) > 0.01:
            self.bar.setAlpha(alpha)

    def dispose(self):
        if self.scroll_listener is not None:
            self.scroll_listener.screen = None
            try:
                self.scroll.setOnScrollChangeListener(None)
            except Exception:
                pass
            self.scroll_listener = None
        super().dispose()

    def pane_width(self):
        owner = self.owner
        try:
            width = int(owner.plugin.layout_fields.int(owner.player.layout, "paneWidth"))
        except Exception:
            width = 0
        return width or int(owner.context.getResources().getDisplayMetrics().widthPixels)

    def hero(self, url, ratio, round_image=False):
        """The picture across the page; its lower part fades out, so the name reads over the glow beneath."""
        owner = self.owner
        width = self.pane_width()
        height = int(width * ratio)
        self.hero_height = height
        Params = jclass("android.widget.LinearLayout$LayoutParams")
        if not url:
            icon = jclass("android.widget.ImageView")(owner.context)
            owner.set_icon(icon, ("msg_contacts", "msg_filled_data_music") if round_image else ("msg_filled_data_music", "msg_played"))
            icon.setScaleType(jclass("android.widget.ImageView$ScaleType").CENTER)
            self.tint_icon(icon, "textSecondary")
            self.content.addView(icon, Params(-1, int(height * 0.6)))
            return
        image = jclass("org.telegram.ui.Components.BackupImageView")(owner.context)
        density = float(owner.context.getResources().getDisplayMetrics().density) or 1.0
        image.setImage(url, "%d_%d" % (int(width / density), int(height / density)), None)
        mask = jclass("android.graphics.drawable.ShapeDrawable")(jclass("android.graphics.drawable.shapes.RectShape")())
        paint = mask.getPaint()
        paint.setShader(jclass("android.graphics.LinearGradient")(
            0.0, float(height * 0.45), 0.0, float(height),
            jarray(jint)([-16777216, 0]), jarray(jfloat)([0.0, 1.0]),
            jclass("android.graphics.Shader$TileMode").CLAMP))
        paint.setXfermode(jclass("android.graphics.PorterDuffXfermode")(jclass("android.graphics.PorterDuff$Mode").DST_IN))
        image.setForeground(mask)
        image.setLayerType(2, None)  # View.LAYER_TYPE_HARDWARE: the mask cuts the picture inside its own layer
        self.content.addView(image, Params(-1, height))

    def centered(self, size, role, text, bold=False, top=0):
        view = self.label(size, role, bold)
        view.setText(text)
        view.setGravity(17)
        view.setSingleLine(False)
        view.setMaxLines(2)
        place = jclass("android.widget.LinearLayout$LayoutParams")(-1, -2)
        place.setMargins(_dp(24), _dp(top), _dp(24), 0)
        self.content.addView(view, place)
        return view

    def circle(self, icons, description, action, size=50, filled=False):
        owner = self.owner
        button = jclass("android.widget.ImageView")(owner.context)
        owner.set_icon(button, icons)
        button.setScaleType(jclass("android.widget.ImageView$ScaleType").CENTER)
        button.setContentDescription(description)
        ColorUtils = jclass("androidx.core.graphics.ColorUtils")
        color = owner.color("accent") if filled else ColorUtils.setAlphaComponent(owner.color("text"), 28)
        button.setBackground(owner.rounded(color, _dp(size / 2.0)))
        self.tint_icon(button, "onAccent" if filled else "accent")
        self.click(button, action)
        place = owner.params(size, size)
        place.setMargins(_dp(12), 0, _dp(12), 0)
        return button, place

    def big_pill(self, text, action):
        """Mornye's album button: an icon and a word on the accent color."""
        owner = self.owner
        pill = jclass("android.widget.LinearLayout")(owner.context)
        pill.setOrientation(0)
        pill.setGravity(17)
        pill.setPadding(_dp(22), 0, _dp(26), 0)
        pill.setBackground(owner.rounded(owner.color("accent"), _dp(26)))
        icon = jclass("android.widget.ImageView")(owner.context)
        owner.set_icon(icon, ("msg_download",))
        self.tint_icon(icon, "onAccent")
        pill.addView(icon, owner.params(24, 24))
        name = self.label(17, "onAccent", True)
        name.setText(text)
        at = jclass("android.widget.LinearLayout$LayoutParams")(-2, -2)
        at.setMarginStart(_dp(8))
        pill.addView(name, at)
        pill.setContentDescription(text)
        self.click(pill, action)
        place = jclass("android.widget.LinearLayout$LayoutParams")(-2, _dp(52))
        place.setMargins(_dp(12), 0, _dp(12), 0)
        return pill, place

    def button_row(self, buttons):
        row = jclass("android.widget.LinearLayout")(self.owner.context)
        row.setOrientation(0)
        row.setGravity(17)
        for view, place in buttons:
            row.addView(view, place)
        place = jclass("android.widget.LinearLayout$LayoutParams")(-1, _dp(76))
        place.setMargins(0, _dp(12), 0, _dp(4))
        self.content.addView(row, place)

    # -- what the service returned

    def show(self, data):
        self.clear_body()
        if not isinstance(data, dict):
            self.draw_header({}, loading=None)
            self.note(self.body, tr("Сервис ничего не вернул."), size=15, top=16)
            return
        self.data = data
        kind = self.kind
        listed = data.get("top_tracks") if kind == "artist" else data.get("tracks")
        tracks = [t for t in (listed or []) if isinstance(t, dict)]
        for track in tracks:
            if not track.get("cover_url") and data.get("cover_url") and kind != "artist":
                track["cover_url"] = data["cover_url"]
            track.setdefault("provider_id", self.ext)
        mark_local(self.owner.data, tracks)
        if kind == "artist":
            self.local_group = find_group(self.owner.data, "artists", data.get("name") or self.title_text)
            self.local = list(self.local_group["tracks"]) if self.local_group else []
        else:
            library = self.owner.data.by_path
            self.local = [library[t["local_path"]] for t in tracks if t.get("local_path") in library]
        self.draw_header(data)
        if kind == "artist":
            self.draw_artist(data, tracks)
        else:
            self.draw_album(data, tracks)

    def draw_header(self, data, loading=False):
        """The picture, the name, a line under it, the buttons. It is part of the body, rebuilt with the data.

        loading: True while the service answers, None when it failed (no buttons then), False when it answered.
        """
        content, self.content = self.content, self.body
        try:
            artist = self.kind == "artist"
            self.hero(image_url(data), 1.05 if artist else 1.0, artist)
            name = data.get("name") or self.title_text
            self.bar_title.setText(name)
            title = self.centered(32 if artist else 26, "text", name, True, -64)
            title.setShadowLayer(float(_dp(12)), 0.0, 0.0, jclass("androidx.core.graphics.ColorUtils").setAlphaComponent(-16777216, 120))
            if artist:
                line = listeners_text(data.get("listeners") or data.get("monthly_listeners"))
                if line:
                    self.centered(14, "textSecondary", line, top=4)
            else:
                who = data.get("artists") or data.get("owner")
                if who:
                    view = self.centered(17, "accent", str(who), top=4)
                    if data.get("artist_id"):
                        self.click(view, self.open_artist)
                meta = [p for p in (data.get("genre"), year_of(data), self.quality_word(data)) if p]
                if meta:
                    self.centered(13, "textSecondary", " · ".join(str(p) for p in meta), top=4)
            if loading:
                self.note(self.body, tr("Загружаю…"), size=15, top=16)
            elif loading is not None:
                if artist:
                    self.artist_buttons()
                else:
                    self.album_buttons()
        finally:
            self.content = content

    @staticmethod
    def quality_word(data):
        quality = str(data.get("audio_quality") or "").upper()
        if "HI_RES" in quality:
            return "Hi-Res"
        if "LOSSLESS" in quality:
            return "Lossless"
        return ""

    # -- an author

    def releases(self):
        data = self.data or {}
        items = [r for r in (data.get("albums") or data.get("releases") or []) if isinstance(r, dict)]
        for release in items:
            release.setdefault("item_type", "album")
            release.setdefault("provider_id", self.ext)
        return sorted(items, key=lambda r: str(r.get("release_date") or ""), reverse=True)

    def artist_buttons(self):
        buttons = []
        if self.local:
            buttons.append(self.circle(("player_new_shuffle", "player_shuffle", "msg_shuffle"),
                                       tr("Перемешать: случайная песня этого исполнителя с телефона"), self.shuffle))
        if self.releases() or (self.data or {}).get("top_tracks"):
            buttons.append(self.circle(("msg_download",), tr("Скачать…"), self.download_menu, 60, True))
        if self.local:
            buttons.append(self.circle(("msg_folders", "msg2_folder"), tr("Открыть в медиатеке"), self.open_in_library))
        if buttons:
            self.button_row(buttons)

    def draw_artist(self, data, tracks):
        releases = self.releases()
        if releases:
            self.featured(releases[0])
        if tracks:
            self.section(self.body, tr("Популярное"))
            for track in tracks:
                self.track_row(self.body, track, second=track.get("album_name") or track.get("artists"))
        shelves = [(title, [r for r in releases if release_type(r) == kind]) for kind, title in SHELVES]
        shelves = [(title, items) for title, items in shelves if items]
        if not shelves and releases:
            shelves = [(tr("Релизы"), releases)]
        for title, items in shelves:
            self.shelf(title, items)
        if not tracks and not releases:
            self.note(self.body, tr("У этого исполнителя в сервисе пока пусто."), size=15, top=16)
            return
        count = (plural(len(releases), tr("%d релиз"), tr("%d релиза"), tr("%d релизов")) % len(releases)) if releases else ""
        self.ending(" · ".join(p for p in (count, self.source()) if p))

    def featured(self, release):
        """The newest release on a plate of its own, as Mornye opens an author's page."""
        owner = self.owner
        Params = jclass("android.widget.LinearLayout$LayoutParams")
        plate = jclass("android.widget.LinearLayout")(owner.context)
        plate.setOrientation(0)
        plate.setGravity(16)
        plate.setPadding(_dp(12), _dp(12), _dp(12), _dp(12))
        plate.setBackground(owner.rounded(owner.color("surfaceContainer"), _dp(20)))
        image = self.remote_image(release, False, 88)
        image.setRoundRadius(_dp(10))
        plate.addView(image, owner.params(88, 88))
        column = jclass("android.widget.LinearLayout")(owner.context)
        column.setOrientation(1)
        head = self.label(13, "textSecondary")
        head.setText(tr("Последний релиз"))
        column.addView(head)
        name = self.label(17, "text", True)
        name.setText(release.get("name") or "")
        column.addView(name)
        line = self.label(13, "textSecondary")
        line.setText(release_line(release))
        column.addView(line)
        place = Params(0, -2, 1.0)
        place.setMarginStart(_dp(14))
        plate.addView(column, place)
        button, at = self.circle(("msg_download",), tr("Скачать «%s»") % (release.get("name") or tr("релиз")),
                                 lambda: self.download_releases([release]), 40)
        at.setMargins(_dp(8), 0, _dp(4), 0)
        plate.addView(button, at)
        plate.setContentDescription(tr("Последний релиз: %s, %s") % (release.get("name") or "", release_line(release)))
        self.click(plate, self.open_release, release)
        place = Params(-1, -2)
        place.setMargins(_dp(16), _dp(16), _dp(16), _dp(4))
        self.body.addView(plate, place)

    def shelf(self, title, releases):
        owner = self.owner
        Params = jclass("android.widget.LinearLayout$LayoutParams")
        self.section(self.body, title)
        scroller, row = self.sideways()
        for release in releases:
            tile = jclass("android.widget.LinearLayout")(owner.context)
            tile.setOrientation(1)
            image = self.remote_image(release, False, SHELF_TILE)
            image.setRoundRadius(_dp(12))
            tile.addView(image, owner.params(SHELF_TILE, SHELF_TILE))
            name = self.label(14, "text", True)
            name.setText(release.get("name") or "")
            top = Params(_dp(SHELF_TILE), -2)
            top.topMargin = _dp(6)
            tile.addView(name, top)
            second = self.label(12, "textSecondary")
            second.setText(release_line(release) if title == tr("Релизы") else year_of(release))
            tile.addView(second, Params(_dp(SHELF_TILE), -2))
            tile.setContentDescription("%s, %s" % (release.get("name") or "", release_line(release)))
            self.click(tile, self.open_release, release)
            at = Params(-2, -2)
            at.setMarginEnd(_dp(12))
            row.addView(tile, at)
        self.body.addView(scroller, Params(-1, -2))

    def download_menu(self):
        """The big button: what of this author to download. Songs already on the phone are skipped."""
        owner = self.owner
        menu = owner.make_menu(self.view, False)
        later = owner.player.start_menu()
        icon = owner.resource
        releases = self.releases()
        top = [t for t in (self.data or {}).get("top_tracks") or [] if isinstance(t, dict)]
        if top:
            menu.add(icon("msg_download"), tr("Популярное (%s)") % tracks_label(len(top)),
                     later(lambda: (menu.dismiss(), self.download_new(top))))
        if releases:
            menu.add(icon("msg_download"), tr("Вся дискография (%s)") % (plural(len(releases), tr("%d релиз"), tr("%d релиза"), tr("%d релизов")) % len(releases)),
                     later(lambda: (menu.dismiss(), self.download_releases(releases))))
        albums = [r for r in releases if release_type(r) == "album"]
        if albums and len(albums) != len(releases):
            menu.add(icon("msg_media"), tr("Только альбомы (%d)") % len(albums),
                     later(lambda: (menu.dismiss(), self.download_releases(albums))))
        singles = [r for r in releases if release_type(r) == "single"]
        if singles and len(singles) != len(releases):
            menu.add(icon("msg_played"), tr("Только синглы и EP (%d)") % len(singles),
                     later(lambda: (menu.dismiss(), self.download_releases(singles))))
        owner.player.show_menu(menu)

    def download_releases(self, releases):
        ext, music, extensions = self.ext, self.owner.data, self.owner.plugin.extensions
        wanted = [r for r in releases if r.get("id")]
        self.say(tr("Собираю песни: %s…") % (plural(len(wanted), tr("%d релиз"), tr("%d релиза"), tr("%d релизов")) % len(wanted)))

        def task(manager):
            tracks = []
            for release in wanted:
                provider = release.get("provider_id") or ext
                try:
                    album = manager.provider_call(provider, "getAlbum", [release["id"]], 45000) or {}
                except Exception:
                    continue
                for track in album.get("tracks") or []:
                    if isinstance(track, dict):
                        track.setdefault("provider_id", provider)
                        if not track.get("cover_url"):
                            track["cover_url"] = album.get("cover_url") or release.get("cover_url") or ""
                        tracks.append(track)
            return queue_new(extensions, music, tracks)

        self.run(task, self.queued)

    def download_new(self, tracks):
        extensions, music = self.owner.plugin.extensions, self.owner.data
        copies = [dict(t) for t in tracks]
        self.run(lambda manager: queue_new(extensions, music, copies), self.queued)

    def queued(self, counts):
        found, new = counts
        if not found:
            self.say(tr("Сервис не отдал песен."))
        elif not new:
            self.say(tr("Всё это уже есть на телефоне."))
        elif new == found:
            self.say(tr("В очереди на скачивание: %s. Ход — в «Загрузках».") % tracks_label(new))
        else:
            self.say(tr("В очереди: %s, ещё %d уже есть на телефоне.") % (tracks_label(new), found - new))

    def shuffle(self):
        """A random song of this author or album from the phone; whether the rest plays mixed is the player's choice."""
        if not self.local:
            self.say(tr("На телефоне нет песен отсюда."))
            return
        self.owner.play(self.local, random.randrange(len(self.local)), (self.data or {}).get("name") or self.title_text)

    def open_in_library(self):
        if self.local_group is not None:
            self.owner.player.open_group("artists", self.local_group["name"])

    def open_release(self, release):
        self.owner.open_remote("album", release.get("provider_id") or self.ext, release.get("id"), release)

    # -- an album or a playlist

    def album_buttons(self):
        buttons = []
        if self.local:
            buttons.append(self.circle(("player_new_shuffle", "player_shuffle", "msg_shuffle"),
                                       tr("Перемешать: случайная песня отсюда с телефона"), self.shuffle))
        tracks = [t for t in (self.data or {}).get("tracks") or [] if isinstance(t, dict)]
        if tracks:
            buttons.append(self.big_pill(tr("Скачать"), lambda: self.download_new(tracks)))
        buttons.append(self.circle(("ic_ab_other", "msg_more"), tr("Ещё"), self.album_menu))
        self.button_row(buttons)

    def album_menu(self):
        owner = self.owner
        menu = owner.make_menu(self.view, False)
        later = owner.player.start_menu()
        icon = owner.resource
        data = self.data or {}
        tracks = [t for t in data.get("tracks") or [] if isinstance(t, dict)]
        if tracks:
            menu.add(icon("msg_download"), tr("Скачать всё, даже то, что есть"),
                     later(lambda: (menu.dismiss(), self.download(tracks, False))))
        if data.get("artist_id"):
            menu.add(icon("msg_contacts"), tr("Открыть исполнителя"), later(lambda: (menu.dismiss(), self.open_artist())))
        if self.local:
            menu.add(icon("msg_played"), tr("Слушать с телефона по порядку"),
                     later(lambda: (menu.dismiss(), self.owner.play(self.local, 0, data.get("name") or ""))))
        owner.player.show_menu(menu)

    def open_artist(self):
        data = self.data or {}
        self.owner.open_remote("artist", data.get("provider_id") or self.ext, data.get("artist_id"), {"name": data.get("artists")})

    def draw_album(self, data, tracks):
        if not tracks:
            self.note(self.body, tr("Здесь пусто."), size=15, top=16)
            return
        numbered = self.kind == "album"
        for index, track in enumerate(tracks):
            self.track_row(self.body, track, number=(track.get("track_number") or index + 1) if numbered else None)
        parts = [tracks_label(len(tracks)), total_minutes(tracks)]
        if data.get("label") and advanced(self.owner.plugin):
            parts.append(str(data["label"]))
        parts.append(self.source())
        self.ending(" · ".join(p for p in parts if p))

    # -- the page's end: how much there is and where it came from

    def source(self):
        try:
            manifest = self.owner.plugin.extensions.get().manifest(self.ext)
            return tr("из %s") % manifest.display_name if manifest is not None else ""
        except Exception:
            return ""

    def ending(self, text):
        if text:
            self.note(self.body, text[0].upper() + text[1:], size=13, top=20)


def queue_new(extensions, music, tracks):
    """Off the UI thread: the songs not on the phone yet go to the download queue. Returns (found, queued)."""
    mark_local(music, tracks)
    new = [t for t in tracks if not t.get("local_path")]
    queue = extensions.downloads()
    for track in new:
        queue.add(track, None, None)
    return len(tracks), len(new)
