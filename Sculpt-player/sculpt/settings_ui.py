# Sculpt Player for exteraGram. Copyright 2026 BroNik (@BroZYTnikkkk).

"""Settings of the player and of Mornye in one place: the gear in the bottom panel opens them.

Only sections with something in them are listed; playback and sound join when their features do."""

from java import jclass

from .common import RADIUS_LABELS, VIS_COLORS, VIS_DENSITIES, VIS_HEIGHTS, VIS_STYLES, _dp
from .ext_ui import ExtScreen
from .library_ui import Screen
from .mornye_ui import MornyeView


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
        self.nav_row(content, ("msg_download",), "Скачивание", owner.open_download_settings)
        self.nav_row(content, ("msg_plugins", "msg_bots"), "Расширения", owner.open_extensions)
        self.nav_row(content, ("msg_info",), "О Mornye", owner.open_about)
        note = self.label(13, "textSecondary")
        note.setSingleLine(False)
        note.setText("Воспроизведение и звук появятся здесь вместе с таймером сна, кроссфейдом и эквалайзером.")
        note.setPadding(_dp(20), _dp(16), _dp(20), 0)
        content.addView(note, Params(-1, -2))


class LookScreen(ExtScreen):
    """The player's look: the visualizer, the cover, the progress line. Each change shows in the player at once."""

    def __init__(self, owner):
        super().__init__(owner, "Вид плеера")
        self.plugin = owner.plugin
        self.page()
        self.start_body()
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
        self.section(self.body, "Прогресс")
        self.toggle("flat_seek", "Ровная линия", "Выключено: волна, как в обычном плеере exteraGram.")

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


class SettingsView(MornyeView):
    """The settings tab: Mornye's own screens (downloads, extensions, about) under one root with the player's."""

    def first_screen(self):
        return SettingsRoot(self)

    def open_look(self):
        self.push(LookScreen(self))
