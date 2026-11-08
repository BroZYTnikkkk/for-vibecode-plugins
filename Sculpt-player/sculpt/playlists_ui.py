# Sculpt Player for exteraGram. Copyright 2026 BroNik (@BroZYTnikkkk).

"""The Playlists tab: the list of playlists, one playlist's songs, the dialog that names one."""

from java import jarray, jclass

from .common import _dp
from .ext_ui import ButtonClick, ExtScreen
from .library_ui import LibraryView, SongsScreen, songs_label

NAME_MAX = 100


def ask_name(player, title, initial, done, button="Сохранить"):
    """A dialog with one field; done(name) with what was typed, when it is not empty."""
    context = player.context
    Theme = jclass("org.telegram.ui.ActionBar.Theme")
    field = jclass("android.widget.EditText")(context)
    field.setSingleLine(True)
    field.setText(initial or "")
    field.setSelection(len(initial or ""))
    field.setHint("Название")
    field.setContentDescription("Название плейлиста")
    field.setTextSize(1, 16.0)
    field.setTextColor(Theme.getColor(Theme.key_dialogTextBlack))
    field.setHintTextColor(Theme.getColor(Theme.key_dialogTextHint))
    field.setFilters(jarray(jclass("android.text.InputFilter"))([jclass("android.text.InputFilter$LengthFilter")(NAME_MAX)]))
    frame = jclass("android.widget.FrameLayout")(context)
    place = jclass("android.widget.FrameLayout$LayoutParams")(-1, -2)
    place.setMargins(_dp(24), _dp(8), _dp(24), 0)
    frame.addView(field, place)

    def confirmed():
        name = str(field.getText()).strip()
        if name:
            done(name)
        else:
            player.plugin.bulletin(player.sheet, "info", "Плейлисту нужно название.")

    builder = jclass("org.telegram.ui.ActionBar.AlertDialog$Builder")(context)
    builder.setTitle(title)
    builder.setView(frame)
    builder.setPositiveButton(button, ButtonClick(confirmed))
    builder.setNegativeButton("Отмена", ButtonClick(None))
    builder.create().show()
    field.requestFocus()


class PlaylistsRoot(ExtScreen):
    def __init__(self, owner):
        super().__init__(owner, "Плейлисты")
        LinearLayout = jclass("android.widget.LinearLayout")
        Params = jclass("android.widget.LinearLayout$LayoutParams")
        page = LinearLayout(owner.context)
        page.setOrientation(1)
        page.addView(self.header(True, self.icon_button(("msg_add",), "Создать плейлист", self.create)))
        scroll = jclass("android.widget.ScrollView")(owner.context)
        scroll.setVerticalScrollBarEnabled(False)
        scroll.setOverScrollMode(2)
        scroll.setFillViewport(True)
        self.content = LinearLayout(owner.context)
        self.content.setOrientation(1)
        self.content.setPadding(0, 0, 0, _dp(16))
        scroll.addView(self.content)
        page.addView(scroll, Params(-1, 0, 1.0))
        self.view = page
        self.start_body()
        self.refresh()

    def create(self):
        store = self.owner.plugin.playlists
        ask_name(self.owner.player, "Новый плейлист", "", lambda name: self.owner.open_playlist(store.create(name)["id"]), "Создать")

    def refresh(self):
        self.clear_body()
        store = self.owner.plugin.playlists
        if not store.items:
            self.empty_state()
            return
        for item in store.items:
            tracks = store.tracks(item["id"])
            image = self.owner.cover_view(8, 40)
            self.owner.bind_cover(image, tracks[0]["path"] if tracks else None, 40)
            self.item_row(self.body, item["name"], songs_label(len(tracks)) if tracks else "Пока без песен",
                          lambda i=item["id"]: self.owner.open_playlist(i), image=image)

    def empty_state(self):
        Params = jclass("android.widget.LinearLayout$LayoutParams")
        title = self.label(20, "text", True)
        title.setText("Плейлистов пока нет")
        title.setGravity(17)
        place = Params(-1, -2)
        place.setMargins(_dp(32), _dp(120), _dp(32), 0)
        self.body.addView(title, place)
        note = self.label(15, "textSecondary")
        note.setSingleLine(False)
        note.setGravity(17)
        note.setText("Собери свои песни в списки. Создай первый плейлист, а песни добавляй через «В плейлист» в меню песни.")
        place = Params(-1, -2)
        place.setMargins(_dp(32), _dp(8), _dp(32), _dp(20))
        self.body.addView(note, place)
        button = self.pill("Создать плейлист", True, self.create)
        place = Params(-2, -2)
        place.gravity = 1
        self.body.addView(button, place)


class PlaylistScreen(SongsScreen):
    def __init__(self, owner, playlist_id):
        self.playlist_id = playlist_id
        self.store = owner.plugin.playlists
        super().__init__(owner, self.store.find(playlist_id)["name"], lambda: self.store.tracks(playlist_id),
                         empty_text="В этом плейлисте пока нет песен. Добавь их через «В плейлист» в меню песни.")

    def build(self, trailing=None, empty_text=""):
        super().build(self.icon_button(("ic_ab_other",), "Действия с плейлистом", self.actions), empty_text)

    def actions(self):
        owner = self.owner
        menu = owner.make_menu(self.title_view, False)
        later = owner.player.start_menu()
        menu.add(owner.resource("msg_edit"), "Переименовать", later(lambda: owner.menu_action(menu, self.rename)))
        menu.add(owner.resource("msg_delete"), "Удалить плейлист", later(lambda: owner.menu_action(menu, self.confirm_delete)))
        owner.player.show_menu(menu)

    def rename(self):
        item = self.store.find(self.playlist_id)

        def renamed(name):
            self.store.rename(self.playlist_id, name)
            self.title_text = name
            self.title_view.setText(name)

        ask_name(self.owner.player, "Переименовать плейлист", item["name"], renamed)

    def confirm_delete(self):
        item = self.store.find(self.playlist_id)
        builder = jclass("org.telegram.ui.ActionBar.AlertDialog$Builder")(self.owner.context)
        builder.setTitle("Удалить «%s»?" % item["name"])
        builder.setMessage("Удалится только этот список. Сами песни останутся на телефоне.")
        builder.setPositiveButton("Удалить", ButtonClick(self.delete))
        builder.setNegativeButton("Отмена", ButtonClick(None))
        dialog = builder.create()
        dialog.show()
        button = dialog.getButton(-1)
        if button is not None:
            Theme = jclass("org.telegram.ui.ActionBar.Theme")
            button.setTextColor(Theme.getColor(Theme.key_text_RedBold))

    def delete(self):
        self.owner.back()
        self.store.delete(self.playlist_id)

    def row_long_clicked(self, index, view):
        path = self.tracks[index]["path"]

        def extra(menu, later):
            menu.add(self.owner.resource("msg_remove") or self.owner.resource("msg_delete"), "Убрать из плейлиста",
                     later(lambda: self.owner.menu_action(menu, self.store.remove_song, self.playlist_id, path)))

        self.owner.song_menu(view, self.tracks[index], extra)


class PlaylistsView(LibraryView):
    OWNS_COVERS = False

    def first_screen(self):
        return PlaylistsRoot(self)

    def open_playlist(self, playlist_id):
        if self.plugin.playlists.find(playlist_id) is not None:
            self.push(PlaylistScreen(self, playlist_id))
