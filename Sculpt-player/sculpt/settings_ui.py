# Sculpt Player for exteraGram. Copyright 2026 BroNik (@BroZYTnikkkk).

"""Settings of the player and of Mornye in one place: the gear in the bottom panel opens them, two parts switched on
top. Sizes are sliders, like exteraGram's own settings."""

from android_utils import run_on_ui_thread
from java import dynamic_proxy, jclass

from .i18n import tr
from .common import CONFIG, SETTINGS_SHEET, SHEET, advanced, VIS_COLORS, VIS_STYLES, _dp
from .ext_ui import ExtScreen
from .lyrics_fx import ALIGN_LABELS
from .library_ui import Screen
from .mornye_ui import MornyeView


SPOTIFY_REPO = "com.exteragram.messenger.player.motion.SpotifyCanvasRepository"
SPOTIFY_AUTH = "com.exteragram.messenger.player.motion.SpotifyAuth"
LYRICS_PROGRESS = (tr("Выключен"), tr("По горизонтали"), tr("По вертикали"))


class SpotifyLogin(dynamic_proxy(jclass(SPOTIFY_AUTH + "$Callback"))):
    def __init__(self, action):
        super().__init__()
        self.action = action

    def onResult(self, ok):
        action, self.action = self.action, None
        if action is not None:
            run_on_ui_thread(lambda: action(bool(ok)))


def sheet_options(plugin, sheet):
    """(the interface, an object of it): the sheet's own answers to a changed setting (MusicPlayerSheet's anonymous
    PlayerSettingsSheet.Delegate), found by what it implements, since an anonymous class's number can change."""
    Class = jclass("java.lang.Class")
    sheet_class = plugin.sheet_fields.cls
    loader = sheet_class.getClassLoader()
    wanted = Class.forName(SETTINGS_SHEET + "$Delegate", True, loader)
    for number in range(1, 60):
        try:
            found = Class.forName("%s$%d" % (SHEET, number), False, loader)
        except Exception:
            continue
        if wanted.isAssignableFrom(found):
            maker = found.getDeclaredConstructor(sheet_class)
            maker.setAccessible(True)
            return wanted, maker.newInstance(sheet)
    raise RuntimeError("the player's settings delegate is not there")


class SettingsRoot(Screen):
    """Two parts under one tab, switched on top like Mornye's bottom bar: the player's settings and Mornye's."""

    def __init__(self, owner):
        super().__init__(owner, tr("Настройки"))
        from .kit import segments
        self.plugin = owner.plugin
        LinearLayout = jclass("android.widget.LinearLayout")
        Params = jclass("android.widget.LinearLayout$LayoutParams")
        page = LinearLayout(owner.context)
        page.setOrientation(1)
        page.addView(self.header(True))
        self.part = int(self.plugin.get_setting("settings_tab", 0))
        bar, self.paint_parts = segments(self, ((("tab_music", "msg_filled_data_music"), tr("Плеер")),
                                                (("menu_download_round", "msg_download"), "Mornye")), self.part, self.choose)
        page.addView(bar, Params(-1, -2))
        scroll = jclass("android.widget.ScrollView")(owner.context)
        scroll.setVerticalScrollBarEnabled(False)
        scroll.setOverScrollMode(2)
        holder = jclass("android.widget.FrameLayout")(owner.context)
        self.parts = [LinearLayout(owner.context), LinearLayout(owner.context)]
        for column in self.parts:
            column.setOrientation(1)
            column.setPadding(0, 0, 0, _dp(16))
            holder.addView(column, jclass("android.widget.FrameLayout$LayoutParams")(-1, -2))
        scroll.addView(holder)
        page.addView(scroll, Params(-1, 0, 1.0))
        self.view = page

        player = self.parts[0]
        self.nav_row(player, ("msg_photo_settings", "msg_settings"), tr("Вид плеера"), owner.open_look)
        self.nav_row(player, ("msg_message", "msg_text_outline"), tr("Текст песни"), owner.open_lyrics_settings)
        self.nav_row(player, ("msg_stats",), tr("Статистика"), owner.open_stats)

        mornye = self.parts[1]
        self.nav_row(mornye, ("msg_plugins", "msg_bots"), tr("Расширения"), owner.open_extensions)
        self.nav_row(mornye, ("msg_download",), tr("Скачивание"), owner.open_download_settings)
        self.nav_row(mornye, ("msg2_devices", "menu_devices", "msg_link"), "Mornye Link", owner.open_mornye_link)
        self.advanced_row(mornye)
        self.nav_row(mornye, ("msg_info",), tr("О Mornye"), owner.open_about)
        self.show_part()

    def advanced_row(self, container):
        """The switch that shows the details of sound and services, right on the first screen."""
        owner = self.owner
        Params = jclass("android.widget.LinearLayout$LayoutParams")
        row = jclass("android.widget.LinearLayout")(owner.context)
        row.setOrientation(0)
        row.setGravity(16)
        row.setPadding(_dp(20), _dp(8), _dp(16), _dp(8))
        texts = jclass("android.widget.LinearLayout")(owner.context)
        texts.setOrientation(1)
        name = self.label(16, "text")
        name.setText(tr("Расширенный режим"))
        texts.addView(name)
        hint = self.label(13, "textSecondary")
        hint.setSingleLine(False)
        hint.setText(tr("Форматы и качество, порядок сервисов, репозитории и журналы расширений."))
        texts.addView(hint)
        row.addView(texts, Params(0, -2, 1.0))
        switch = jclass("android.widget.Switch")(owner.context)
        switch.setChecked(bool(advanced(self.plugin)))
        switch.setContentDescription(tr("Расширенный режим"))
        from .ext_ui import Checked
        listener = Checked(lambda on: self.guarded(self.plugin.set_setting, "advanced_mode", bool(on)))
        switch.setOnCheckedChangeListener(listener)
        self.switch_listener = (switch, listener)
        row.addView(switch)
        container.addView(row, Params(-1, -2))

    def choose(self, index):
        if index == self.part:
            return
        self.part = index
        self.plugin.set_setting("settings_tab", index)
        self.paint_parts(index)
        self.show_part()

    def show_part(self):
        for index, column in enumerate(self.parts):
            column.setVisibility(0 if index == self.part else 8)

    def colors_changed(self):
        self.paint_parts(self.part)

    def dispose(self):
        switch = getattr(self, "switch_listener", None)
        if switch is not None:
            switch[0].setOnCheckedChangeListener(None)
            switch[1].action = None
            self.switch_listener = None
        super().dispose()


class LookScreen(ExtScreen):
    """The player's look: the visualizer, the cover, the progress line. Each change shows in the player at once."""

    def __init__(self, owner):
        super().__init__(owner, tr("Вид плеера"))
        self.plugin = owner.plugin
        self.options = None
        self.page()
        self.start_body()
        self.show()

    # -- exteraGram's own settings

    def notify(self, event):
        if self.options is None:
            self.options = sheet_options(self.plugin, self.owner.player.sheet)
        wanted, delegate = self.options
        wanted.getMethod(event).invoke(delegate)

    def native(self, getter, setter, title, hint, event):
        config = jclass(CONFIG)

        def changed(on):
            getattr(config, setter)(bool(on))
            self.notify(event)

        switch = self.switch(bool(getattr(config, getter)()), changed, title)
        self.item_row(self.body, title, hint, trailing=switch)

    def lyrics_progress(self):
        config = jclass(CONFIG)
        value = int(config.getLyricsProgress())
        current = LYRICS_PROGRESS[value] if 0 <= value < len(LYRICS_PROGRESS) else LYRICS_PROGRESS[0]
        row, _, _ = self.item_row(self.body, tr("Прогресс строки"), current, None)
        row.setBackground(self.owner.selector(0))
        self.click(row, self.progress_menu, row, value)

    def progress_menu(self, row, value):
        owner = self.owner
        menu = owner.make_menu(row, False)
        later = owner.player.start_menu()
        check = owner.resource("msg_text_check")
        for index, label in enumerate(LYRICS_PROGRESS):
            menu.add(check if index == value else 0, label, later(lambda i=index: (menu.dismiss(), self.set_progress(i))))
        owner.player.show_menu(menu)

    def set_progress(self, value):
        jclass(CONFIG).setLyricsProgress(value)
        self.notify("onLyricsProgressChanged")
        self.show()

    def spotify(self):
        repository = jclass(SPOTIFY_REPO)
        if not repository.isSupported():
            return
        config = jclass(CONFIG)
        logged = bool(repository.isLoggedIn())
        self.section(self.body, "Spotify Canvas")

        def changed(on):
            if on and not repository.isLoggedIn():
                jclass(SPOTIFY_AUTH).login(self.owner.context, SpotifyLogin(self.spotify_answered))
                return
            config.setPlayerSpotifyCanvas(bool(on))
            self.notify("onSpotifyCanvasChanged")

        switch = self.switch(bool(config.getPlayerSpotifyCanvas()) and logged, changed, "Spotify Canvas")
        self.item_row(self.body, "Spotify Canvas", tr("Короткие видео вместо обложки. Нужен вход в Spotify."), trailing=switch)
        if logged:
            self.item_row(self.body, tr("Выйти из Spotify"), None, self.spotify_logout)

    def spotify_answered(self, ok):
        if not self.alive:
            return
        if ok:
            jclass(CONFIG).setPlayerSpotifyCanvas(True)
            self.notify("onSpotifyCanvasChanged")
        else:
            self.say(tr("Не получилось войти в Spotify. Попробуй ещё раз."))
        self.guarded(self.show)

    def spotify_logout(self):
        from .player_taps import DialogButton
        builder = jclass("org.telegram.ui.ActionBar.AlertDialog$Builder")(self.owner.context)
        builder.setTitle(tr("Выйти из Spotify?"))
        builder.setMessage(tr("Spotify Canvas выключится, пока ты не войдёшь снова."))
        builder.setPositiveButton(tr("Выйти"), DialogButton(lambda: self.guarded(self.spotify_left)))
        builder.setNegativeButton(tr("Отмена"), DialogButton(None))
        builder.show()

    def spotify_left(self):
        jclass(SPOTIFY_REPO).logout()
        jclass(CONFIG).setPlayerSpotifyCanvas(False)
        self.notify("onSpotifyCanvasChanged")
        self.show()

    def show(self):
        from .kit import slider_row
        from .common import RADIUS_VALUES, VIS_BARS, VIS_HEIGHT_DP
        from .kit import release_sliders
        release_sliders(self)
        self.clear_body()
        get = self.plugin.get_setting
        self.section(self.body, tr("Визуализатор"))
        self.toggle("vis_top", tr("Над обложкой"), tr("Столбики растут вверх от края обложки."))
        self.toggle("vis_bottom", tr("Под обложкой"), tr("Столбики растут вниз от края обложки."))
        self.choice("vis_style", tr("Форма столбиков"), VIS_STYLES, 0)
        height = get("vis_height_dp", None) or VIS_HEIGHT_DP[min(2, max(0, int(get("vis_height", 1))))]
        slider_row(self, self.body, tr("Высота"), 24, 120, 8, float(height), lambda v: "%d dp" % v,
                   lambda v: self.save("vis_height_dp", int(v)))
        bars = get("vis_bars", None) or VIS_BARS[min(2, max(0, int(get("vis_density", 1))))]
        slider_row(self, self.body, tr("Количество столбиков"), 16, 96, 8, float(bars), lambda v: "%d" % v,
                   lambda v: self.save("vis_bars", int(v)))
        self.choice("vis_color_mode", tr("Цвет"), VIS_COLORS, 0)
        self.section(self.body, tr("Обложка"))
        radius = get("cover_radius_dp", None)
        if radius is None:
            radius = RADIUS_VALUES[min(3, max(0, int(get("cover_radius", 1))))]
        slider_row(self, self.body, tr("Скругление углов"), 0, 40, 2, float(radius),
                   lambda v: tr("Нет") if v == 0 else "%d dp" % v, lambda v: self.save("cover_radius_dp", int(v)))
        slider_row(self, self.body, tr("Обложка над Spotify Canvas"), 0, 100, 5, float(get("canvas_cover_alpha", 50)),
                   lambda v: tr("Скрыта") if v == 0 else "%d%%" % v, lambda v: self.canvas_alpha(int(v)))
        self.choice("quality_pill", tr("Качество песни"), [tr("Не показывать"), tr("Под обложкой"), tr("В углу обложки")], 1)
        self.native("getPlayerCoverColors", "setPlayerCoverColors", tr("Цвета обложки в плеере"),
                    tr("Плеер окрашивается в цвета обложки."), "onCoverColorsChanged")
        self.native("getPlayerMiniCoverColors", "setPlayerMiniCoverColors", tr("Цвета обложки в мини-плеере"),
                    tr("Мини-плеер в чатах окрашивается в цвета обложки."), "onCoverColorsChanged")
        self.native("getPlayerMotionCovers", "setPlayerMotionCovers", tr("Живые обложки"),
                    tr("Анимированные обложки там, где они есть."), "onMotionCoversChanged")
        self.section(self.body, tr("Фон"))
        self.toggle("glow_under_tabs", tr("Живое свечение под вкладками"),
                    tr("Фон плеера продолжает двигаться под Медиатекой, Поиском и другими вкладками. "
                    "Выключи, если телефон греется: тогда свечение под вкладками замирает."))
        self.native("getPlayerRhythmBackground", "setPlayerRhythmBackground", tr("Фон в такт музыке"),
                    tr("Свечение за обложкой двигается под музыку."), "onRhythmBackgroundChanged")
        self.native("getPlayerParticles", "setPlayerParticles", tr("Частицы"), tr("Частицы на фоне плеера."), "onRhythmBackgroundChanged")
        self.section(self.body, tr("Прогресс"))
        self.toggle("flat_seek", tr("Ровная линия"), tr("Выключено: волна, как в обычном плеере exteraGram."))
        self.spotify()

    def toggle(self, key, title, hint):
        switch = self.switch(self.plugin.get_setting(key, True), lambda on: self.save(key, on), title)
        self.item_row(self.body, title, hint, trailing=switch)

    def choice(self, key, title, labels, default):
        value = int(self.plugin.get_setting(key, default))
        current = labels[value] if 0 <= value < len(labels) else labels[default]
        row, _, _ = self.item_row(self.body, title, current, None)
        row.setBackground(self.owner.selector(0))
        self.click(row, self.menu, row, key, labels, value)

    def menu(self, row, key, labels, value):
        owner = self.owner
        menu = owner.make_menu(row, False)
        later = owner.player.start_menu()
        check = owner.resource("msg_text_check")
        for index, label in enumerate(labels):
            menu.add(check if index == value else 0, label, later(lambda i=index: (menu.dismiss(), self.save(key, i), self.show())))
        owner.player.show_menu(menu)

    def save(self, key, value):
        self.plugin.set_setting(key, value)
        self.plugin.settings_changed()

    def canvas_alpha(self, value):
        self.plugin.set_setting("canvas_cover_alpha", value)
        player = self.plugin.player
        if player is not None:
            try:
                self.plugin.sheet_method("applyTransitions").invoke(player.sheet)  # the cover takes it at once
            except Exception as e:
                self.plugin.report("applyTransitions", e)


class LyricsScreen(LookScreen):
    """The lyrics: looking them up, how the line fills, where they stand, where the bars go meanwhile."""

    def __init__(self, owner):
        ExtScreen.__init__(self, owner, tr("Текст песни"))
        self.plugin = owner.plugin
        self.options = None
        self.page()
        self.start_body()
        self.show()

    def show(self):
        self.clear_body()
        self.native("getLyricsOnline", "setLyricsOnline", tr("Автоматический поиск текста"),
                    tr("Если в файле нет текста, он ищется сам: сначала в расширениях с текстами, затем на LRCLIB и lrcmux."), "onLyricsOnlineChanged")
        self.lyrics_progress()
        self.choice("lyrics_align", tr("Выравнивание текста"), ALIGN_LABELS, 0)
        self.choice("lyrics_vis", tr("Визуализатор при тексте"), (tr("Над названием"), tr("Сверху")), 0)


class SettingsView(MornyeView):
    """The settings tab: Mornye's own screens (downloads, extensions, about) under one root with the player's."""

    def first_screen(self):
        return SettingsRoot(self)

    def open_look(self):
        self.push(LookScreen(self))

    def open_lyrics_settings(self):
        self.push(LyricsScreen(self))
