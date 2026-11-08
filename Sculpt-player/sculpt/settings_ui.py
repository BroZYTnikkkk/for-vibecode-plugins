# Sculpt Player for exteraGram. Copyright 2026 BroNik (@BroZYTnikkkk).

"""Settings of the player and of Mornye in one place: the gear in the bottom panel opens them.

Only sections with something in them are listed; playback and sound join when their features do."""

from android_utils import run_on_ui_thread
from java import dynamic_proxy, jclass

from .common import CONFIG, SETTINGS_SHEET, SHEET, RADIUS_LABELS, advanced, VIS_COLORS, VIS_DENSITIES, VIS_HEIGHTS, VIS_STYLES, _dp
from .ext_ui import ExtScreen
from .library_ui import Screen
from .mornye_ui import MornyeView


SPOTIFY_REPO = "com.exteragram.messenger.player.motion.SpotifyCanvasRepository"
SPOTIFY_AUTH = "com.exteragram.messenger.player.motion.SpotifyAuth"
LYRICS_PROGRESS = ("Выключен", "По горизонтали", "По вертикали")


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
    def __init__(self, owner):
        super().__init__(owner, "Настройки")
        LinearLayout = jclass("android.widget.LinearLayout")
        Params = jclass("android.widget.LinearLayout$LayoutParams")
        page = LinearLayout(owner.context)
        page.setOrientation(1)
        page.addView(self.header(True))
        scroll = jclass("android.widget.ScrollView")(owner.context)
        scroll.setVerticalScrollBarEnabled(False)
        scroll.setOverScrollMode(2)
        content = LinearLayout(owner.context)
        content.setOrientation(1)
        content.setPadding(0, 0, 0, _dp(16))
        scroll.addView(content)
        page.addView(scroll, Params(-1, 0, 1.0))
        self.view = page
        self.nav_row(content, ("msg_photo_settings", "msg_settings"), "Вид плеера", owner.open_look)
        self.nav_row(content, ("msg_voice_headphones", "filled_sound_on"), "Звук", owner.open_sound)
        self.nav_row(content, ("msg_download",), "Скачивание", owner.open_download_settings)
        self.nav_row(content, ("msg_plugins", "msg_bots"), "Расширения", owner.open_extensions)
        self.nav_row(content, ("msg_info",), "О Mornye", owner.open_about)
        note = self.label(13, "textSecondary")
        note.setSingleLine(False)
        note.setText("Воспроизведение появится здесь вместе с таймером сна и кроссфейдом.")
        note.setPadding(_dp(20), _dp(16), _dp(20), 0)
        content.addView(note, Params(-1, -2))


class LookScreen(ExtScreen):
    """The player's look: the visualizer, the cover, the progress line. Each change shows in the player at once."""

    def __init__(self, owner):
        super().__init__(owner, "Вид плеера")
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
        row, _, _ = self.item_row(self.body, "Прогресс строки", current, None)
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
        self.item_row(self.body, "Spotify Canvas", "Короткие видео вместо обложки. Нужен вход в Spotify.", trailing=switch)
        if logged:
            self.item_row(self.body, "Выйти из Spotify", None, self.spotify_logout)

    def spotify_answered(self, ok):
        if not self.alive:
            return
        if ok:
            jclass(CONFIG).setPlayerSpotifyCanvas(True)
            self.notify("onSpotifyCanvasChanged")
        else:
            self.say("Не получилось войти в Spotify. Попробуй ещё раз.")
        self.guarded(self.show)

    def spotify_logout(self):
        from .player_taps import DialogButton
        builder = jclass("org.telegram.ui.ActionBar.AlertDialog$Builder")(self.owner.context)
        builder.setTitle("Выйти из Spotify?")
        builder.setMessage("Spotify Canvas выключится, пока ты не войдёшь снова.")
        builder.setPositiveButton("Выйти", DialogButton(lambda: self.guarded(self.spotify_left)))
        builder.setNegativeButton("Отмена", DialogButton(None))
        builder.show()

    def spotify_left(self):
        jclass(SPOTIFY_REPO).logout()
        jclass(CONFIG).setPlayerSpotifyCanvas(False)
        self.notify("onSpotifyCanvasChanged")
        self.show()

    def show(self):
        self.clear_body()
        self.section(self.body, "Визуализатор")
        self.toggle("vis_top", "Над обложкой", "Столбики растут вверх от края обложки.")
        self.toggle("vis_bottom", "Под обложкой", "Столбики растут вниз от края обложки.")
        self.choice("vis_style", "Форма столбиков", VIS_STYLES, 0)
        self.choice("vis_height", "Высота", VIS_HEIGHTS, 1)
        self.choice("vis_density", "Количество", VIS_DENSITIES, 1)
        self.choice("vis_color_mode", "Цвет", VIS_COLORS, 0)
        self.section(self.body, "Обложка")
        self.choice("cover_radius", "Скругление углов", RADIUS_LABELS, 1)
        self.native("getPlayerCoverColors", "setPlayerCoverColors", "Цвета обложки в плеере",
                    "Плеер окрашивается в цвета обложки.", "onCoverColorsChanged")
        self.native("getPlayerMiniCoverColors", "setPlayerMiniCoverColors", "Цвета обложки в мини-плеере",
                    "Мини-плеер в чатах окрашивается в цвета обложки.", "onCoverColorsChanged")
        self.native("getPlayerMotionCovers", "setPlayerMotionCovers", "Живые обложки",
                    "Анимированные обложки там, где они есть.", "onMotionCoversChanged")
        self.section(self.body, "Фон")
        self.toggle("glow_under_tabs", "Живое свечение под вкладками",
                    "Фон плеера продолжает двигаться под Медиатекой, Поиском и другими вкладками. "
                    "Выключи, если телефон греется: тогда свечение под вкладками замирает.")
        self.native("getPlayerRhythmBackground", "setPlayerRhythmBackground", "Фон в такт музыке",
                    "Свечение за обложкой двигается под музыку.", "onRhythmBackgroundChanged")
        self.native("getPlayerParticles", "setPlayerParticles", "Частицы", "Частицы на фоне плеера.", "onRhythmBackgroundChanged")
        self.section(self.body, "Прогресс")
        self.toggle("flat_seek", "Ровная линия", "Выключено: волна, как в обычном плеере exteraGram.")
        self.spotify()
        self.section(self.body, "Текст песни")
        self.native("getLyricsOnline", "setLyricsOnline", "Тексты из сети",
                    "Сначала расширения с текстами, если они установлены, затем LRCLIB.", "onLyricsOnlineChanged")
        self.lyrics_progress()

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


class SoundScreen(ExtScreen):
    """Sound: for now the switch that shows the details of sound to those who want them."""

    def __init__(self, owner):
        super().__init__(owner, "Звук")
        self.plugin = owner.plugin
        self.page()
        switch = self.switch(advanced(self.plugin), self.changed, "Расширенный режим")
        self.item_row(self.content, "Расширенный режим",
                      "Показывает форматы и качество (FLAC, Hi-Res, битность, частота), порядок сервисов и источников "
                      "метаданных, репозитории и журналы расширений. Без него всё названо простыми словами.",
                      trailing=switch)
        self.note(self.content, "Эквалайзер и громкость пока — кнопками в самом плеере, по краям от кнопок управления.", top=16)

    def changed(self, on):
        self.plugin.set_setting("advanced_mode", bool(on))
        self.say("Расширенный режим включён" if on else "Расширенный режим выключен")


class SettingsView(MornyeView):
    """The settings tab: Mornye's own screens (downloads, extensions, about) under one root with the player's."""

    def first_screen(self):
        return SettingsRoot(self)

    def open_look(self):
        self.push(LookScreen(self))

    def open_sound(self):
        self.push(SoundScreen(self))
