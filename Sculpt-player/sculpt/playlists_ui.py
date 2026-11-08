# Sculpt Player for exteraGram. Copyright 2026 BroNik (@BroZYTnikkkk).

"""The Playlists tab: the list of playlists, one playlist's songs, the dialog that names one."""

import random

from java import jarray, jclass

from .i18n import tr
from . import chat_songs
from .common import MEDIA_CONTROLLER, PANEL_ACTIVE, _dp
from .ext_ui import ButtonClick, ExtScreen
from .library_ui import LibraryView, SongsScreen, format_time, songs_label

NAME_MAX = 100
TELEGRAM_TITLE = tr("Песни из Telegram")


def ask_name(player, title, initial, done, button=tr("Сохранить")):
    """A dialog with one field; done(name) with what was typed, when it is not empty."""
    context = player.context
    Theme = jclass("org.telegram.ui.ActionBar.Theme")
    field = jclass("android.widget.EditText")(context)
    field.setSingleLine(True)
    field.setText(initial or "")
    field.setSelection(len(initial or ""))
    field.setHint(tr("Название"))
    field.setContentDescription(tr("Название плейлиста"))
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
            player.plugin.bulletin(player.sheet, "info", tr("Плейлисту нужно название."))

    builder = jclass("org.telegram.ui.ActionBar.AlertDialog$Builder")(context)
    builder.setTitle(title)
    builder.setView(frame)
    builder.setPositiveButton(button, ButtonClick(confirmed))
    builder.setNegativeButton(tr("Отмена"), ButtonClick(None))
    builder.create().show()
    field.requestFocus()


class PlaylistsRoot(ExtScreen):
    def __init__(self, owner):
        super().__init__(owner, tr("Плейлисты"))
        LinearLayout = jclass("android.widget.LinearLayout")
        Params = jclass("android.widget.LinearLayout$LayoutParams")
        page = LinearLayout(owner.context)
        page.setOrientation(1)
        page.addView(self.header(True, self.icon_button(("msg_add",), tr("Создать плейлист"), self.create)))
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
        ask_name(self.owner.player, tr("Новый плейлист"), "", lambda name: self.owner.open_playlist(store.create(name)["id"]), tr("Создать"))

    def refresh(self):
        self.clear_body()
        store = self.owner.plugin.playlists
        if not store.items and not store.telegram:
            self.empty_state()
            return
        if store.telegram:
            self.item_row(self.body, TELEGRAM_TITLE, songs_label(len(store.telegram)), self.owner.open_telegram, icons=("msg_filled_data_music", "msg_played"))
        for item in store.items:
            tracks = store.tracks(item["id"])
            image = self.owner.cover_view(8, 40)
            self.owner.bind_cover(image, tracks[0]["path"] if tracks else None, 40)
            self.item_row(self.body, item["name"], songs_label(len(tracks)) if tracks else tr("Пока без песен"),
                          lambda i=item["id"]: self.owner.open_playlist(i), image=image)

    def empty_state(self):
        Params = jclass("android.widget.LinearLayout$LayoutParams")
        title = self.label(20, "text", True)
        title.setText(tr("Плейлистов пока нет"))
        title.setGravity(17)
        place = Params(-1, -2)
        place.setMargins(_dp(32), _dp(120), _dp(32), 0)
        self.body.addView(title, place)
        note = self.label(15, "textSecondary")
        note.setSingleLine(False)
        note.setGravity(17)
        note.setText(tr("Собери свои песни в списки. Создай первый плейлист, а песни добавляй через «В плейлист» в меню песни."))
        place = Params(-1, -2)
        place.setMargins(_dp(32), _dp(8), _dp(32), _dp(20))
        self.body.addView(note, place)
        button = self.pill(tr("Создать плейлист"), True, self.create)
        place = Params(-2, -2)
        place.gravity = 1
        self.body.addView(button, place)


class PlaylistScreen(SongsScreen):
    def __init__(self, owner, playlist_id):
        self.playlist_id = playlist_id
        self.store = owner.plugin.playlists
        super().__init__(owner, self.store.find(playlist_id)["name"], lambda: self.store.tracks(playlist_id),
                         empty_text=tr("В этом плейлисте пока нет песен. Добавь их через «В плейлист» в меню песни."))

    def build(self, trailing=None, empty_text=""):
        super().build(self.icon_button(("ic_ab_other",), tr("Действия с плейлистом"), self.actions), empty_text)

    def actions(self):
        owner = self.owner
        menu = owner.make_menu(self.title_view, False)
        later = owner.player.start_menu()
        menu.add(owner.resource("msg_edit"), tr("Переименовать"), later(lambda: owner.menu_action(menu, self.rename)))
        menu.add(owner.resource("msg_delete"), tr("Удалить плейлист"), later(lambda: owner.menu_action(menu, self.confirm_delete)))
        owner.player.show_menu(menu)

    def rename(self):
        item = self.store.find(self.playlist_id)

        def renamed(name):
            self.store.rename(self.playlist_id, name)
            self.title_text = name
            self.title_view.setText(name)

        ask_name(self.owner.player, tr("Переименовать плейлист"), item["name"], renamed)

    def confirm_delete(self):
        item = self.store.find(self.playlist_id)
        builder = jclass("org.telegram.ui.ActionBar.AlertDialog$Builder")(self.owner.context)
        builder.setTitle(tr("Удалить «%s»?") % item["name"])
        builder.setMessage(tr("Удалится только этот список. Сами песни останутся на телефоне."))
        builder.setPositiveButton(tr("Удалить"), ButtonClick(self.delete))
        builder.setNegativeButton(tr("Отмена"), ButtonClick(None))
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
            menu.add(self.owner.resource("msg_remove") or self.owner.resource("msg_delete"), tr("Убрать из плейлиста"),
                     later(lambda: self.owner.menu_action(menu, self.store.remove_song, self.playlist_id, path)))

        self.owner.song_menu(view, self.tracks[index], extra)


class TelegramSongsScreen(SongsScreen):
    """The songs from chats, in a list of their own: they are shown at once and their messages arrive after."""

    def __init__(self, owner):
        self.store = owner.plugin.playlists
        self.found = {}
        super().__init__(owner, TELEGRAM_TITLE, self.rows, empty_text=tr("Здесь будут песни из чатов. Добавь их через «В плейлист» в меню «+» в плеере."))
        chat_songs.load(self.store.telegram, self.loaded)

    def rows(self):
        return [{"path": "tg:%d:%d" % chat_songs.key_of(s), "title": s["title"], "artist": s["artist"], "album": "", "duration": s["duration"],
                 "key": chat_songs.key_of(s)} for s in self.store.telegram]

    def loaded(self, found):
        if self.list is not None:
            self.found = found
            self.guarded(self.refresh)

    def row_view(self, position, convert):
        owner = self.owner
        if convert is None:
            convert = owner.song_row(self.holders)
        holder = self.holders[convert.hashCode()]
        track = self.tracks[position]
        message = self.found.get(track["key"])
        receiver = holder["image"].getImageReceiver()
        if message is not None:
            jclass("com.exteragram.messenger.player.PlayerCovers").setCover(receiver, message, 48, True)
        else:
            receiver.clearImage()
        holder["title"].setText(track["title"])
        holder["subtitle"].setText(track["artist"])
        holder["time"].setText(format_time(track["duration"]))
        for name, role in (("title", "text"), ("subtitle", "textSecondary"), ("time", "textSecondary")):
            holder[name].setTextColor(owner.color(role))
        return convert

    def start(self, index):
        messages = [self.found[t["key"]] for t in self.tracks if t["key"] in self.found]
        first = self.found.get(self.tracks[index]["key"])
        if first is None:
            self.owner.plugin.bulletin(self.owner.player.sheet, "info", tr("Эта песня ещё загружается или удалена из чата."))
            return
        self.close_keyboard()
        queue = jclass("java.util.ArrayList")()
        for message in reversed(messages):
            queue.add(message)  # the player walks its list towards the start
        jclass(MEDIA_CONTROLLER).getInstance().setPlaylist(queue, first, 0, False, None)
        entry = self.owner.plugin.queues.find("tg:%d" % first.getDialogId())
        if entry is not None:
            entry["title"] = TELEGRAM_TITLE
            self.owner.plugin.queues.changed()
        self.owner.player.show_tab(PANEL_ACTIVE)

    def row_clicked(self, index, view):
        self.start(index)

    def shuffle(self):
        if self.tracks:
            self.start(random.randrange(len(self.tracks)))

    def row_long_clicked(self, index, view):
        owner = self.owner
        track = self.tracks[index]
        menu = owner.make_menu(view)
        later = owner.player.start_menu()
        menu.add(owner.resource("msg_remove") or owner.resource("msg_delete"), tr("Убрать из плейлиста"),
                 later(lambda: owner.menu_action(menu, self.store.remove_telegram, track["key"])))
        owner.player.show_menu(menu)


class PlaylistsView(LibraryView):
    OWNS_COVERS = False

    def first_screen(self):
        return PlaylistsRoot(self)

    def open_telegram(self):
        self.push(TelegramSongsScreen(self))

    def open_playlist(self, playlist_id):
        if self.plugin.playlists.find(playlist_id) is not None:
            self.push(PlaylistScreen(self, playlist_id))
