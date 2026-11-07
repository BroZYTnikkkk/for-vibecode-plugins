# Sculpt Player for exteraGram. Copyright 2026 BroNik (@BroZYTnikkkk).
# The "About Mornye" screen credits Mornye by zarzet (GNU LGPL v3.0); code taken from Mornye keeps that license.

from java import jclass

from .common import _dp
from .library_ui import BlankScreen, LibraryView, Screen

MORNYE_LINKS = (
    ("Mornye на GitHub", "https://github.com/mornyeapp/Mornye"),
    ("Mornye Desktop на GitHub", "https://github.com/mornyeapp/Mornye-Desktop"),
    ("Новости Mornye в Telegram", "https://t.me/mornyeupdates"),
    ("Сообщество Mornye в Telegram", "https://t.me/mornyecommunity"),
)
MORNYE_SUPPORT = (
    ("Ko-fi", "https://ko-fi.com/zarzet"),
    ("GitHub Sponsors", "https://github.com/sponsors/zarzet"),
)
MORNYE_CONTRIBUTORS = "Amonoman, Ruubiiiii, binimum, sachinsenal0x64, Pedro Marcondes, Serhii Ilchenko"


class MornyeRoot(Screen):
    """The first level of the Mornye tab: search for songs to download, then the places to go."""

    def __init__(self, owner):
        super().__init__(owner, "Mornye")
        LinearLayout = jclass("android.widget.LinearLayout")
        Params = jclass("android.widget.LinearLayout$LayoutParams")
        page = LinearLayout(owner.context)
        page.setOrientation(1)
        extensions = self.icon_button(("msg_plugins", "filter_plugins", "msg_bots"), "Расширения", owner.open_extensions)
        page.addView(self.header(True, extensions))
        scroll = jclass("android.widget.ScrollView")(owner.context)
        scroll.setVerticalScrollBarEnabled(False)
        scroll.setOverScrollMode(2)
        content = LinearLayout(owner.context)
        content.setOrientation(1)
        content.setPadding(0, 0, 0, _dp(16))
        scroll.addView(content)
        page.addView(scroll, Params(-1, 0, 1.0))
        self.view = page

        self.search_pill(content, "Найти песню для скачивания", owner.open_download_search)
        self.nav_row(content, ("msg_download",), "Загрузки", owner.open_downloads)
        self.nav_row(content, ("menu_tag_edit", "msg_edit"), "Метаданные песен", owner.open_metadata)
        self.nav_row(content, ("msg_info",), "О Mornye", owner.open_about)

        note = self.label(13, "textSecondary")
        note.setSingleLine(False)
        note.setText("Скачивание, поиск метаданных и расширения пришли сюда из Mornye, музыкального плеера zarzet.")
        note.setPadding(_dp(20), _dp(16), _dp(20), 0)
        content.addView(note, Params(-1, -2))

    def colors_changed(self):
        self.paint_pills()


class AboutScreen(Screen):
    """Who made Mornye, where to find it, its license."""

    def __init__(self, owner):
        super().__init__(owner, "О Mornye")
        LinearLayout = jclass("android.widget.LinearLayout")
        Params = jclass("android.widget.LinearLayout$LayoutParams")
        page = LinearLayout(owner.context)
        page.setOrientation(1)
        page.addView(self.header())
        scroll = jclass("android.widget.ScrollView")(owner.context)
        scroll.setVerticalScrollBarEnabled(False)
        scroll.setOverScrollMode(2)
        content = LinearLayout(owner.context)
        content.setOrientation(1)
        content.setPadding(0, _dp(8), 0, _dp(24))
        scroll.addView(content)
        page.addView(scroll, Params(-1, 0, 1.0))
        self.view = page
        self.content = content

        name = self.label(40, "text", True)
        name.setText("Mornye")
        self.text_block(name, 0)
        about = self.label(15, "textSecondary")
        about.setSingleLine(False)
        about.setText("Музыкальный плеер для Android и компьютера. Sculpt Player берёт из него расширения для скачивания, "
                      "поиск метаданных и, позже, Mornye Link.")
        self.text_block(about, 8)

        self.section("Автор")
        self.pair("zarzet", "© 2026 Zarz Eleutherius")
        self.section("Участники")
        people = self.label(15, "text")
        people.setSingleLine(False)
        people.setText(MORNYE_CONTRIBUTORS)
        self.text_block(people, 0)
        self.section("Ссылки")
        for title, url in MORNYE_LINKS:
            self.link(title, url)
        self.section("Поддержать автора")
        for title, url in MORNYE_SUPPORT:
            self.link(title, url)
        self.section("Лицензия")
        license_text = self.label(15, "text")
        license_text.setSingleLine(False)
        license_text.setText("GNU LGPL v3.0. Код из Mornye в Sculpt Player распространяется на тех же условиях и с указанием авторства.")
        self.text_block(license_text, 0)

    def text_block(self, view, top):
        place = jclass("android.widget.LinearLayout$LayoutParams")(-1, -2)
        place.setMargins(_dp(20), _dp(top), _dp(20), 0)
        self.content.addView(view, place)

    def section(self, title):
        label = self.label(14, "accent", True)
        label.setText(title)
        place = jclass("android.widget.LinearLayout$LayoutParams")(-1, -2)
        place.setMargins(_dp(20), _dp(24), _dp(20), _dp(4))
        self.content.addView(label, place)

    def pair(self, first, second):
        top = self.label(16, "text")
        top.setText(first)
        self.text_block(top, 0)
        bottom = self.label(13, "textSecondary")
        bottom.setText(second)
        self.text_block(bottom, 2)

    def link(self, title, url):
        owner = self.owner
        Params = jclass("android.widget.LinearLayout$LayoutParams")
        row = jclass("android.widget.LinearLayout")(owner.context)
        row.setOrientation(0)
        row.setGravity(16)
        row.setPadding(_dp(20), 0, _dp(16), 0)
        row.setBackground(owner.selector(0))
        icon = jclass("android.widget.ImageView")(owner.context)
        owner.set_icon(icon, ("msg_link", "msg_link2"))
        self.tint_icon(icon, "icon")
        row.addView(icon, owner.params(24, 24))
        column = jclass("android.widget.LinearLayout")(owner.context)
        column.setOrientation(1)
        name = self.label(16, "text")
        name.setText(title)
        column.addView(name)
        address = self.label(13, "textSecondary")
        address.setText(url.replace("https://", ""))
        column.addView(address)
        place = Params(0, -2, 1.0)
        place.setMarginStart(_dp(16))
        row.addView(column, place)
        row.setContentDescription("%s, открыть ссылку" % title)
        self.click(row, owner.open_link, url)
        self.content.addView(row, Params(-1, _dp(60)))


class MornyeView(LibraryView):
    """The Mornye tab: the same stack of screens as the library, with its own first screen."""

    OWNS_COVERS = False

    def first_screen(self):
        return MornyeRoot(self)

    def shown(self):
        self.data_changed()

    def open_extensions(self):
        self.push(BlankScreen(self, "Расширения", "Здесь будут расширения Mornye: каталог, установка из файла и свои репозитории. "
                                                  "Они ищут и скачивают песни. Появятся в следующем обновлении."))

    def open_download_search(self):
        self.push(BlankScreen(self, "Поиск песен", "Искать песни для скачивания можно будет, когда появятся расширения: "
                                                   "поиск и скачивание идут через них."))

    def open_downloads(self):
        self.push(BlankScreen(self, "Загрузки", "Здесь будут песни, которые ты скачиваешь, с ходом загрузки. "
                                                "Готовые попадут в папку Music/Mornye и сразу в медиатеку."))

    def open_metadata(self):
        self.push(BlankScreen(self, "Метаданные песен", "Здесь можно будет найти название, автора, альбом и обложку для песни "
                                                        "и записать их в файл после проверки «было → станет»."))

    def open_about(self):
        self.push(AboutScreen(self))

    def open_link(self, url):
        """A Telegram link opens its chat, which lies under the player: the player steps aside first."""
        if url.startswith("https://t.me/"):
            self.close_player()
        jclass("org.telegram.messenger.browser.Browser").openUrl(self.context, url)
