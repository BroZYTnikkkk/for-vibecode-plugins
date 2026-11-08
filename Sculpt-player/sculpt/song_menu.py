# Sculpt Player for exteraGram. Copyright 2026 BroNik (@BroZYTnikkkk).

"""A song's menu in the Queue tab, the way Musicolet has it: the title with a heart on top, then what to do."""

import os
from types import SimpleNamespace

from android_utils import OnClickListener
from java import jarray, jclass
from java.lang import Integer as JInteger

from .common import MEDIA_CONTROLLER, _ctx, _dp, _java_class, _log
from .library_ui import Run
from .music import local_path


TITLE_MAX_DP = 220


def human_size(size):
    for unit in ("Б", "КБ", "МБ", "ГБ"):
        if size < 1024 or unit == "ГБ":
            return ("%.1f %s" % (size, unit)) if unit != "Б" else ("%d %s" % (size, unit))
        size /= 1024.0
    return ""


class SongMenu:
    def __init__(self, screen, row, anchor):
        self.screen = screen
        self.player = screen.player
        self.plugin = screen.plugin
        self.row = row
        self.anchor = anchor
        self.heart = None
        self.menu = None

    def icon(self, *names):
        for name in names:
            resource = self.screen.resource(name)
            if resource:
                return resource
        return 0

    def show(self):
        menu = self.plugin.sheet_menu(self.player.sheet, self.anchor, True)
        self.menu = menu
        later = self.player.start_menu()
        menu.addView(self.header())
        menu.add(self.icon("msg_info", "menu_info"), "Информация о песне", later(self.info))
        menu.add(self.icon("msg_remove", "msg_delete"), "Убрать из этой очереди", later(self.remove))
        menu.addGap()
        menu.add(self.icon("player_new_next", "msg_forward", "msg_arrowright"), "Играть после текущей", later(self.play_next))
        self.add_to_queue(menu, later)
        self.player.add_playlist_item(menu, self.row.path)
        menu.addGap()
        stopping = self.plugin.stop_after is not None and self.plugin.stop_after == self.identity()
        menu.add(self.icon("msg_round_pause_m", "player_pause", "ic_pause"),
                 "Не останавливаться после этой песни" if stopping else "Остановиться после этой песни", later(self.stop_after))
        menu.add(self.icon("menu_tag_edit", "msg_edit"), "Изменить теги", later(self.edit_tags))
        menu.add(self.icon("msg_share"), "Поделиться", later(self.share))
        menu.add(self.icon("msg_delete"), "Удалить навсегда", later(self.delete))
        self.player.show_menu(menu)

    # -- the title and the heart ---------------------------------------------------------------

    def header(self):
        context = self.screen.context
        LinearLayout = jclass("android.widget.LinearLayout")
        head = LinearLayout(context)
        head.setOrientation(0)
        head.setGravity(16)
        head.setPadding(_dp(18), _dp(10), _dp(8), _dp(6))
        title = self.screen.text(18, bold=True)
        title.setText(self.row.title or "Без названия")
        # a long title runs by instead of stretching the menu across the screen
        title.setMaxWidth(_dp(TITLE_MAX_DP))
        title.setEllipsize(jclass("android.text.TextUtils$TruncateAt").MARQUEE)
        title.setMarqueeRepeatLimit(-1)
        title.setSelected(True)
        colors = self.screen.colors
        if colors is not None:
            title.setTextColor(colors.text)
        head.addView(title, LinearLayout.LayoutParams(0, -2, 1.0))
        self.heart = jclass("android.widget.ImageView")(context)
        self.heart.setScaleType(jclass("android.widget.ImageView$ScaleType").CENTER)
        self.paint_heart()
        self.heart.setOnClickListener(OnClickListener(lambda v: self.screen.guarded(self.toggle_favorite)))
        head.addView(self.heart, LinearLayout.LayoutParams(_dp(44), _dp(44)))
        # the heart's listener holds this menu: it goes when the menu closes
        heart = self.heart
        drop = Run(None)
        drop.cleanup = lambda: heart.setOnClickListener(None)
        self.player.menu_runs.append(drop)
        return head

    def paint_heart(self):
        favorite = self.row.path is not None and self.plugin.music.is_favorite(self.row.path)
        self.heart.setImageResource(self.icon("media_like_active" if favorite else "media_like"))
        self.heart.setContentDescription("Убрать из любимых" if favorite else "В любимые")
        colors = self.screen.colors
        if colors is not None:
            color = colors.accent if favorite else colors.icon
            if self.row.path is None:
                color = jclass("androidx.core.graphics.ColorUtils").setAlphaComponent(colors.icon, 90)
            self.heart.setColorFilter(jclass("android.graphics.PorterDuffColorFilter")(color, jclass("android.graphics.PorterDuff$Mode").SRC_IN))

    def toggle_favorite(self):
        if self.row.path is None:
            self.screen.say("В любимые можно добавить только песню с телефона.")
            return
        added = self.plugin.music.toggle_favorite(self.row.path)
        self.paint_heart()
        self.player.update_like()
        self.screen.say("Добавлено в любимые" if added else "Убрано из любимых", "saved_messages" if added else "ic_delete")

    # -- items -----------------------------------------------------------------------------------

    def identity(self):
        if self.row.path is not None:
            return ("path", self.row.path)
        return self.plugin.song_identity(self.row.message)

    def file(self):
        """The song's file on the phone, also for a chat's song that is already downloaded."""
        if self.row.path is not None:
            return self.row.path
        message = self.row.message
        if message is None:
            return None
        try:
            path = jclass("org.telegram.messenger.FileLoader").getInstance(message.currentAccount).getPathToMessage(message.messageOwner)
            if path is not None and path.exists():
                return str(path.getAbsolutePath())
        except Exception:
            pass
        return None

    def info(self):
        from .song_info import SongInfo
        fallback = {"title": self.row.title, "artist": self.row.artist, "album": self.row.album, "seconds": self.row.seconds}
        SongInfo(self.player, self.file(), self.row.path, fallback).show()

    def edit_tags(self):
        if self.row.path is None:
            self.screen.say("Теги можно записать только в песню с телефона.")
            return
        self.player.edit_tags(self.row.path)

    def remove(self):
        screen = self.screen
        entry = screen.shown_entry()
        row = self.row
        if entry is None or screen.is_active():
            controller = jclass(MEDIA_CONTROLLER).getInstance()
            playing = controller.getPlayingMessageObject()
            if row.message is None:
                return
            if playing is not None and playing.getId() == row.message.getId() and playing.getDialogId() == row.message.getDialogId():
                self.screen.say("Эта песня играет сейчас. Включите другую, чтобы убрать её.")
                return
            controller.getPlaylist().remove(row.message)
            shuffled = self.plugin.media_fields.get(controller, "shuffledPlaylist")
            if shuffled is not None:
                shuffled.remove(row.message)
            table = self.plugin.media_fields.get(controller, "playlistMap")
            if table is not None:
                table.remove(JInteger(row.message.getId()))
            screen.keep_position()
        elif entry["kind"] == "library":
            entry["paths"] = [p for p in entry["paths"] if p != row.path]
            self.plugin.queues.save()
        else:
            java = entry.get("java")
            if java is not None:
                java.remove(row.message)
        screen.refresh()

    def play_next(self):
        screen = self.screen
        rows = screen.rows
        index = rows.index(self.row)
        current = screen.current_index()
        if current < 0:
            self.screen.say("Сначала включите песню из этой очереди.")
            return
        if index == current:
            return
        target = current + 1 if index > current else current
        if target != index:
            screen.moved(index, target)
            screen.refresh()
        self.screen.say("«%s» заиграет следующей." % (self.row.title or "Песня"), "info")

    def add_to_queue(self, menu, later):
        """Another queue from the library takes the song at its end."""
        if self.row.path is None:
            menu.add(self.icon("msg_list", "msg_add"), "Добавить в очередь", later(
                lambda: self.screen.say("В другую очередь можно добавить только песню с телефона.")))
            return
        store = self.plugin.queues
        others = [e for e in store.entries if e["kind"] == "library" and e["key"] != self.screen.shown_key]
        if not others:
            menu.add(self.icon("msg_list", "msg_add"), "Добавить в очередь", later(
                lambda: self.screen.say("Других очередей из Медиатеки пока нет.")))
            return
        submenu = menu.makeSwipeback()
        submenu.add(self.icon("ic_ab_back"), "Назад", later(menu.closeSwipeback))
        submenu.addGap()
        for entry in others:
            number = self.screen.number(entry["key"])
            submenu.add(0, "%d. %s" % (number, entry["title"]), later(lambda k=entry["key"]: self.append_to(k)))
        menu.add(self.icon("msg_list", "msg_add"), "Добавить в очередь", later(lambda: menu.openSwipeback(submenu)))
        last = menu.getLast()
        if last is not None:
            last.setRightIcon(self.icon("msg_arrowright"))

    def append_to(self, key):
        store = self.plugin.queues
        entry = store.find(key)
        if entry is None:
            return
        if key == store.active:
            # the queue that plays: the song joins MediaController's own list at the end of the play order
            track = self.plugin.music.by_path.get(self.row.path)
            if track is None:
                return
            message = self.plugin.music.message_for(track)
            controller = jclass(MEDIA_CONTROLLER).getInstance()
            playlist = controller.getPlaylist()
            config = jclass("org.telegram.messenger.SharedConfig")
            if config.playOrderReversed:
                playlist.add(message)
            else:
                playlist.add(0, message)
            shuffled = self.plugin.media_fields.get(controller, "shuffledPlaylist")
            if config.shuffleMusic and shuffled is not None and not shuffled.isEmpty():
                shuffled.add(0, message)  # shuffle plays towards index 0 too: the end of what is left
            self.screen.keep_position()
            table = self.plugin.media_fields.get(controller, "playlistMap")
            if table is not None:
                table.put(JInteger(message.getId()), message)
        entry["paths"] = entry["paths"] + [self.row.path]
        store.save()
        self.screen.say("Добавлено в очередь «%s»." % entry["title"], "info")

    def stop_after(self):
        identity = self.identity()
        if self.plugin.stop_after == identity:
            self.plugin.stop_after = None
            self.screen.say("Музыка продолжит играть после этой песни.")
        else:
            self.plugin.stop_after = identity
            self.screen.say("Музыка остановится после «%s»." % (self.row.title or "этой песни"))

    def share(self):
        path = self.file()
        if path is None:
            self.screen.say("Песня ещё не скачана. Включите её, чтобы она загрузилась, и попробуйте снова.")
            return
        context = self.screen.context
        Intent = jclass("android.content.Intent")
        application = jclass("org.telegram.messenger.ApplicationLoader").getApplicationId()
        uri = jclass("androidx.core.content.FileProvider").getUriForFile(context, application + ".provider", jclass("java.io.File")(path))
        intent = Intent(Intent.ACTION_SEND)
        intent.setType("audio/*")
        intent.putExtra(Intent.EXTRA_STREAM, uri)
        intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        chooser = Intent.createChooser(intent, "Поделиться песней")
        chooser.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        context.startActivity(chooser)

    def delete(self):
        """Android asks the person itself before a file another app owns is deleted; this only starts the ask."""
        if self.row.path is None:
            self.screen.say("Удалить навсегда можно только песню с телефона.")
            return
        activity = jclass("org.telegram.ui.LaunchActivity").instance
        MediaStore = jclass("android.provider.MediaStore")
        resolver = _ctx().getContentResolver()
        external = MediaStore.Audio.Media.getContentUri("external")
        String = jclass("java.lang.String")
        cursor = resolver.query(external, jarray(String)(["_id"]), "_data=?", jarray(String)([self.row.path]), None)
        uri = None
        if cursor is not None:
            try:
                if cursor.moveToFirst():
                    uri = jclass("android.content.ContentUris").withAppendedId(external, cursor.getLong(0))
            finally:
                cursor.close()
        if uri is None or activity is None or jclass("android.os.Build$VERSION").SDK_INT < 30:
            self.screen.say("Android не дал удалить этот файл отсюда.")
            return
        uris = jclass("java.util.ArrayList")()
        uris.add(uri)
        pending = MediaStore.createDeleteRequest(resolver, uris)
        activity.startIntentSenderForResult(pending.getIntentSender(), 7302, None, 0, 0, 0)
        _log("delete asked: %s" % os.path.basename(self.row.path))


class PlayerMenuScreen:
    """What a song's menu needs from the screen it opened on, for the menu opened from the player itself."""

    def __init__(self, player):
        self.player = player
        self.plugin = player.plugin
        self.context = player.context

    @property
    def colors(self):
        return self.plugin.sheet_fields.get(self.player.sheet, "colors")

    def resource(self, name):
        return self.context.getResources().getIdentifier(name, "drawable", self.context.getPackageName())

    def text(self, size, bold=False):
        view = jclass("android.widget.TextView")(self.context)
        view.setTextSize(1, float(size))
        view.setSingleLine(True)
        view.setEllipsize(jclass("android.text.TextUtils$TruncateAt").END)
        if bold:
            view.setTypeface(jclass("org.telegram.messenger.AndroidUtilities").bold())
        return view

    def guarded(self, action, *args):
        try:
            action(*args)
        except Exception as e:
            self.plugin.report("song menu", e)

    def say(self, text, animation="info"):
        self.plugin.bulletin(self.player.sheet, animation, text)


class PlayerSongMenu(SongMenu):
    """The ⋯ beside the title: everything here is about this song. The player's own settings are behind the gear."""

    ITEM_OPTIONS = "org.telegram.ui.Components.ItemOptions"
    MESSAGE = "org.telegram.messenger.MessageObject"

    def __init__(self, player, message):
        path = local_path(message)
        track = player.plugin.music.by_path.get(path) if path else None
        title, author = message.getMusicTitle(), message.getMusicAuthor()
        row = SimpleNamespace(title=str(title) if title else "", artist=str(author) if author else "", album=(track or {}).get("album") or "",
                              seconds=int(float(message.getDuration() or 0)), path=path, message=message)
        super().__init__(PlayerMenuScreen(player), row, player.moreButton)

    def stock(self, name, menu, message):
        """One of the player's own builders, for what only Telegram knows how to do with a song in a chat."""
        method = self.plugin.sheet_method(name, _java_class(self.ITEM_OPTIONS), _java_class(self.MESSAGE))
        return method.invoke(self.player.sheet, menu, message)

    def chat_items(self, menu, later):
        message = self.row.message
        actions = self.plugin.sheet_actions(self.player.sheet)
        saving = self.stock("buildSaveOptions", menu, message)
        menu.add(self.icon("msg_stories_save", "msg_download"), "Сохранить в…", later(lambda: menu.openSwipeback(saving)))
        last = menu.getLast()
        if last is not None:
            last.setRightIcon(self.icon("msg_arrowright"))
        self.stock("addForwardAndShare", menu, message)
        menu.add(self.icon("menu_download_round", "msg_download"), "Сохранить в музыку", later(lambda: actions.saveToMusic(message)))
        menu.add(self.icon("msg_message"), "Показать в чате", later(lambda: actions.showInChat(message)))

    def show(self):
        menu = self.plugin.sheet_menu(self.player.sheet, self.anchor, True)
        self.menu = menu
        later = self.player.start_menu()
        on_phone = self.row.path is not None
        menu.addView(self.header())
        menu.add(self.icon("msg_info", "menu_info"), "Информация о песне", later(self.info))
        if on_phone:
            menu.add(self.icon("menu_tag_edit", "msg_edit"), "Изменить теги", later(self.edit_tags))
        menu.addGap()
        if on_phone:
            menu.add(self.icon("msg_share"), "Поделиться", later(self.share))
        else:
            self.chat_items(menu, later)
        stopping = self.plugin.stop_after is not None and self.plugin.stop_after == self.identity()
        menu.add(self.icon("msg_round_pause_m", "player_pause", "ic_pause"),
                 "Не останавливаться после этой песни" if stopping else "Остановиться после этой песни", later(self.stop_after))
        if on_phone:
            menu.addGap()
            menu.add(self.icon("msg_delete"), "Удалить навсегда", later(self.delete))
        # exteraGram's own menu, with whatever other plugins put there: people will look for its settings
        menu.addGap()
        menu.add(self.icon("msg_settings"), "Настройки плеера и плагины", later(self.player.open_stock_menu))
        last = menu.getLast()
        if last is not None:
            last.setRightIcon(self.icon("msg_arrowright"))
        self.player.show_menu(menu)
