# Sculpt Player for exteraGram. Copyright 2026 BroNik (@BroZYTnikkkk).

"""The Queue tab, as Musicolet has it: which queue on top, its numbers below, the songs, a search at the bottom.

The queue on screen is either the one playing (MediaController's own list, live) or one of the others kept by
QueueStore, shown as they were left: a tap on a song of another queue switches to it.
"""

import os
import random

from android_utils import OnClickListener, run_on_ui_thread
from java import dynamic_proxy, jarray, jclass
from java.lang import Boolean as JBoolean, Integer as JInteger

from .common import MARGIN, MEDIA_CONTROLLER, _dp, _log, sculpt_class
from .music import local_path

ROW, MENU, MOVED = 1, 2, 3  # sculpt.QueueList's events


class Events(dynamic_proxy(jclass("android.os.Handler$Callback"))):
    """QueueList's events, passed on while the screen lives; dropped after, so nothing keeps it alive."""

    def __init__(self, screen):
        super().__init__()
        self.screen = screen

    def handleMessage(self, message):
        screen = self.screen
        if screen is not None:
            screen.event(message.what, message.arg1, message.arg2, message.obj)
        return True


class Watcher(dynamic_proxy(jclass("android.text.TextWatcher"))):
    def __init__(self, action):
        super().__init__()
        self.action = action

    def afterTextChanged(self, text):
        if self.action is not None:
            self.action(str(text))

    def beforeTextChanged(self, text, start, count, after):
        pass

    def onTextChanged(self, text, start, before, count):
        pass


def clock(seconds):
    seconds = max(0, int(seconds))
    if seconds >= 3600:
        return "%d:%02d:%02d" % (seconds // 3600, seconds // 60 % 60, seconds % 60)
    return "%d:%02d" % (seconds // 60, seconds % 60)


class Row:
    """One song as the screen shows it, and what is needed to play it."""

    __slots__ = ("title", "artist", "album", "seconds", "path", "message")

    def __init__(self, title, artist, album, seconds, path=None, message=None):
        self.title, self.artist, self.album, self.seconds, self.path, self.message = title, artist, album, seconds, path, message


class QueueScreen:
    def __init__(self, player, context):
        self.player = player
        self.plugin = player.plugin
        self.store = self.plugin.queues
        self.music = self.plugin.music
        self.context = context
        self.visible = False
        self.shown_key = None
        self.rows = []
        self.order = []  # positions in rows of what the list shows (the search narrows it)
        self.query = ""
        self.refresh_posted = False
        self.clicks = []
        self.events = Events(self)
        self.watcher = None
        self.list = None
        self.methods = {}
        self.colors = None

        FrameLayout = jclass("android.widget.FrameLayout")
        LinearLayout = jclass("android.widget.LinearLayout")
        self.root = FrameLayout(context)
        self.root.setClickable(True)
        self.root.setVisibility(8)
        column = LinearLayout(context)
        column.setOrientation(1)
        self.root.addView(column, FrameLayout.LayoutParams(-1, -1))

        # which queue: "6. Все песни ⌄" in a frame, and ✕ to let it go
        head = LinearLayout(context)
        head.setOrientation(0)
        head.setGravity(16)
        head.setPadding(_dp(MARGIN), _dp(8), _dp(4), _dp(4))
        self.picker = LinearLayout(context)
        self.picker.setOrientation(0)
        self.picker.setGravity(16)
        self.picker.setPadding(_dp(16), 0, _dp(12), 0)
        self.picker_text = self.text(20, bold=True)
        self.picker.addView(self.picker_text, LinearLayout.LayoutParams(0, -2, 1.0))
        self.chevron = self.icon(("arrow_more", "ic_arrow_drop_down", "msg_arrowright"), "Выбрать очередь", None)
        self.picker.addView(self.chevron, LinearLayout.LayoutParams(_dp(28), _dp(28)))
        self.on_click(self.picker, self.pick_queue)
        head.addView(self.picker, LinearLayout.LayoutParams(0, _dp(56), 1.0))
        self.close = self.icon(("ic_close_white", "msg_close", "ic_ab_close"), "Убрать очередь", self.remove_queue)
        head.addView(self.close, LinearLayout.LayoutParams(_dp(48), _dp(48)))
        column.addView(head, LinearLayout.LayoutParams(-1, -2))

        # ▶  ≡   position / count, ⏱ length   💾  ⋯
        bar = LinearLayout(context)
        bar.setOrientation(0)
        bar.setGravity(16)
        bar.setPadding(_dp(8), 0, _dp(8), 0)
        self.play_button = self.icon(("player_new_play", "msg_play_mini", "msg_played"), "Играть эту очередь", self.play_queue)
        bar.addView(self.play_button, LinearLayout.LayoutParams(_dp(48), _dp(48)))
        self.sort_button = self.icon(("msg_sort", "msg2_sort", "msg_list"), "Упорядочить", self.sort_menu)
        bar.addView(self.sort_button, LinearLayout.LayoutParams(_dp(48), _dp(48)))
        counts = LinearLayout(context)
        counts.setOrientation(1)
        counts.setGravity(17)
        self.position_text = self.text(15)
        self.position_text.setGravity(17)
        self.length_text = self.text(14)
        self.length_text.setGravity(17)
        counts.addView(self.position_text, LinearLayout.LayoutParams(-1, -2))
        counts.addView(self.length_text, LinearLayout.LayoutParams(-1, -2))
        bar.addView(counts, LinearLayout.LayoutParams(0, -2, 1.0))
        self.save_button = self.icon(("msg_saved", "msg_download", "msg_save"), "Сохранить как плейлист", self.save_queue)
        bar.addView(self.save_button, LinearLayout.LayoutParams(_dp(48), _dp(48)))
        self.more_button = self.icon(("ic_ab_other", "msg_more"), "Меню очереди", self.queue_menu)
        bar.addView(self.more_button, LinearLayout.LayoutParams(_dp(48), _dp(48)))
        column.addView(bar, LinearLayout.LayoutParams(-1, _dp(60)))
        self.divider = jclass("android.view.View")(context)
        column.addView(self.divider, LinearLayout.LayoutParams(-1, max(1, _dp(1) // 2)))

        # the songs: this plugin's own RecyclerView, or a note when its Java code is not there
        holder = FrameLayout(context)
        self.empty = self.text(15)
        self.empty.setGravity(17)
        self.empty.setSingleLine(False)
        self.empty.setPadding(_dp(32), 0, _dp(32), 0)
        holder.addView(self.empty, FrameLayout.LayoutParams(-1, -1))
        cls = sculpt_class("sculpt.QueueList")
        if cls is not None:
            try:
                for method in cls.getMethods():
                    self.methods[str(method.getName())] = method
                # made by Java inside the holder; Python keeps only the holder, never a QueueList, which Chaquopy
                # cannot wrap after a reinstall loads the DEX again
                self.methods["attach"].invoke(None, context, self.events, holder)
                self.list = holder
                handle = self.resource("list_reorder") or self.resource("msg_list")
                self.call("setIcons", JInteger(handle), JInteger(self.resource("ic_ab_other")))
            except Exception as e:
                _log("queue list: %s" % e)
                self.list = None
        column.addView(holder, LinearLayout.LayoutParams(-1, 0, 1.0))

        # search at the bottom, above the tabs
        search = LinearLayout(context)
        search.setOrientation(0)
        search.setGravity(16)
        search.setPadding(_dp(MARGIN), 0, _dp(MARGIN), 0)
        self.search_icon = self.icon(("outline_search_1_24", "msg_search"), "Поиск", None)
        search.addView(self.search_icon, LinearLayout.LayoutParams(_dp(32), _dp(32)))
        self.search = jclass("android.widget.EditText")(context)
        self.search.setHint("Искать в этой очереди…")
        self.search.setTextSize(1, 16.0)
        self.search.setSingleLine(True)
        self.search.setBackground(None)
        self.search.setPadding(_dp(12), 0, 0, 0)
        self.watcher = Watcher(self.searched)
        self.search.addTextChangedListener(self.watcher)
        search.addView(self.search, LinearLayout.LayoutParams(0, -1, 1.0))
        self.search_line = jclass("android.view.View")(context)
        column.addView(self.search_line, LinearLayout.LayoutParams(-1, max(1, _dp(1) // 2)))
        column.addView(search, LinearLayout.LayoutParams(-1, _dp(52)))

        player.layout.addOwnView(self.root)

    # -- small helpers ------------------------------------------------------------------

    def text(self, size, bold=False):
        view = jclass("android.widget.TextView")(self.context)
        view.setTextSize(1, float(size))
        view.setSingleLine(True)
        view.setEllipsize(jclass("android.text.TextUtils$TruncateAt").END)
        if bold:
            view.setTypeface(jclass("org.telegram.messenger.AndroidUtilities").bold())
        return view

    def resource(self, name):
        return self.context.getResources().getIdentifier(name, "drawable", self.context.getPackageName())

    def icon(self, names, description, action):
        view = jclass("android.widget.ImageView")(self.context)
        view.setScaleType(jclass("android.widget.ImageView$ScaleType").CENTER)
        for name in names:
            resource = self.resource(name)
            if resource:
                view.setImageResource(resource)
                break
        view.setContentDescription(description)
        if action is not None:
            self.on_click(view, action)
        return view

    def on_click(self, view, action):
        view.setOnClickListener(OnClickListener(lambda v: self.guarded(action)))
        self.clicks.append(view)

    def guarded(self, action, *args):
        try:
            action(*args)
        except Exception as e:
            self.plugin.report("queue tab", e)

    # QueueList's static entry points: Python holds only the FrameLayout the list lives in (see QueueList.attach)
    STATIC = {"setRows": "rows", "setCurrent": "current", "setCover": "cover", "setDragEnabled": "drag",
              "setColors": "colors", "setIcons": "icons", "scrollTo": "scroll"}

    def call(self, name, *args):
        if self.list is not None:
            self.methods[self.STATIC[name]].invoke(None, self.list, *args)

    def say(self, text, animation="info"):
        self.plugin.bulletin(self.player.sheet, animation, text)

    @staticmethod
    def controller():
        return jclass(MEDIA_CONTROLLER).getInstance()

    @staticmethod
    def config():
        return jclass("org.telegram.messenger.SharedConfig")

    # -- showing -----------------------------------------------------------------------

    def show(self):
        self.visible = True
        self.root.setVisibility(0)
        self.root.setAlpha(0.0)
        self.root.animate().alpha(1.0).setDuration(150).start()
        self.root.setPadding(0, self.plugin.layout_fields.int(self.player.layout, "contentTop"), 0, 0)
        if self.store.find(self.shown_key) is None or self.shown_key != self.store.active:
            self.shown_key = self.store.active
        self.set_colors(self.plugin.sheet_fields.get(self.player.sheet, "colors"))
        self.refresh(scroll=True)

    def hide(self):
        self.visible = False
        self.root.animate().cancel()
        self.root.setVisibility(8)
        self.hide_keyboard()

    def hide_keyboard(self):
        try:
            jclass("org.telegram.messenger.AndroidUtilities").hideKeyboard(self.search)
            self.search.clearFocus()
        except Exception:
            pass

    def set_colors(self, colors):
        if colors is None:
            return
        self.colors = colors
        self.root.setBackgroundColor(colors.background)
        PorterDuffColorFilter = jclass("android.graphics.PorterDuffColorFilter")
        mode = jclass("android.graphics.PorterDuff$Mode").SRC_IN
        for view in (self.chevron, self.close, self.play_button, self.sort_button, self.save_button, self.more_button,
                     self.search_icon):
            view.setColorFilter(PorterDuffColorFilter(colors.icon, mode))
        frame = jclass("android.graphics.drawable.GradientDrawable")()
        frame.setCornerRadius(float(_dp(14)))
        frame.setStroke(_dp(1.5), jclass("androidx.core.graphics.ColorUtils").setAlphaComponent(colors.icon, 110))
        self.picker.setBackground(frame)
        self.picker_text.setTextColor(colors.text)
        self.position_text.setTextColor(colors.text)
        self.length_text.setTextColor(colors.textSecondary)
        self.empty.setTextColor(colors.textSecondary)
        self.divider.setBackgroundColor(colors.divider)
        self.search_line.setBackgroundColor(colors.divider)
        self.search.setTextColor(colors.text)
        self.search.setHintTextColor(colors.textSecondary)
        self.call("setColors", JInteger(colors.text), JInteger(colors.textSecondary), JInteger(colors.accent), JInteger(colors.icon))

    def shown_entry(self):
        return self.store.find(self.shown_key)

    def is_active(self):
        return self.shown_key is not None and self.shown_key == self.store.active

    def number(self, key):
        for index, entry in enumerate(self.store.entries):
            if entry["key"] == key:
                return index + 1
        return 0

    # -- rows -----------------------------------------------------------------------------

    def message_row(self, message):
        path = local_path(message)
        if path is not None:
            track = self.music.by_path.get(path)
            if track is not None:
                return Row(track.get("title") or os.path.basename(path), track.get("artist") or "", track.get("album") or "",
                           track.get("duration") or 0, path, message)
        title = message.getMusicTitle()
        author = message.getMusicAuthor()
        return Row(str(title) if title else "", str(author) if author else "", "", int(message.getDuration() or 0), path, message)

    def active_list(self):
        """The list MediaController plays from, and whether it walks it towards index 0.

        With shuffle on it plays shuffledPlaylist, the current song at its end, always towards index 0; otherwise
        playlist, towards index 0 unless the order is reversed."""
        controller = self.controller()
        if self.config().shuffleMusic:
            shuffled = self.plugin.media_fields.get(controller, "shuffledPlaylist")
            if shuffled is not None and not shuffled.isEmpty():
                return shuffled, True
        return controller.getPlaylist(), not self.config().playOrderReversed

    @staticmethod
    def in_play_order(playlist, backwards):
        items = [playlist.get(i) for i in range(playlist.size())]
        if backwards:
            items.reverse()
        return items

    def build_rows(self):
        entry = self.shown_entry()
        if entry is None or self.is_active():
            return [self.message_row(m) for m in self.in_play_order(*self.active_list())]
        if entry["kind"] == "library":
            by_path = self.music.by_path
            return [Row(t.get("title") or "", t.get("artist") or "", t.get("album") or "", t.get("duration") or 0, t["path"])
                    for t in (by_path.get(p) for p in entry["paths"]) if t is not None]
        java = entry.get("java")
        return [] if java is None else [self.message_row(m) for m in self.in_play_order(java, not self.config().playOrderReversed)]

    def current_index(self):
        """Where the playing song is among the rows; for another queue, the song it was left at."""
        entry = self.shown_entry()
        if entry is None or self.is_active():
            playing = self.controller().getPlayingMessageObject()
            if playing is None:
                return -1
            for index, row in enumerate(self.rows):
                if row.message is not None and row.message.getId() == playing.getId() and row.message.getDialogId() == playing.getDialogId():
                    return index
            return -1
        current = entry.get("current")
        for index, row in enumerate(self.rows):
            if (entry["kind"] == "library" and row.path == current) or (row.message is not None and row.message.getId() == current):
                return index
        return -1

    def refresh(self, scroll=False):
        if not self.visible:
            return
        entry = self.shown_entry()
        if entry is not None:
            self.picker_text.setText("%d. %s" % (self.number(entry["key"]), entry["title"]))
        elif self.controller().getPlaylist().isEmpty():
            self.picker_text.setText("Очередей пока нет")
        else:
            self.picker_text.setText("Очередь")
        self.close.setAlpha(1.0 if entry is not None else 0.3)
        self.rows = self.build_rows()
        self.apply_filter()
        current = self.current_index()
        self.position_text.setText("%d / %d" % (current + 1 if current >= 0 else 0, len(self.rows)))
        self.length_text.setText("⏱ " + clock(sum(r.seconds for r in self.rows)))
        self.show_rows(current, scroll)

    def refresh_soon(self):
        """The queue grew or was replaced: one refresh shortly after, however many parts arrive meanwhile."""
        if self.refresh_posted or not self.visible:
            return
        self.refresh_posted = True

        def later():
            self.refresh_posted = False
            self.guarded(self.refresh)

        run_on_ui_thread(later, 400)

    def apply_filter(self):
        words = self.query.lower().split()
        if not words:
            self.order = list(range(len(self.rows)))
            return
        self.order = [i for i, r in enumerate(self.rows)
                      if all(w in ("%s %s %s" % (r.title, r.artist, r.album)).lower() for w in words)]

    def show_rows(self, current=None, scroll=False):
        if current is None:
            current = self.current_index()
        if self.list is None:
            self.empty.setText("Список очереди не загрузился. Переустановите плагин.")
            self.empty.setVisibility(0)
            return
        rows = [self.rows[i] for i in self.order]
        String = jclass("java.lang.String")
        covers = self.music.covers
        cover_paths = [covers.cached(r.path)[1] if r.path else None for r in rows]
        shown_current = self.order.index(current) if current in self.order else -1
        self.call("setRows", jarray(String)([r.title for r in rows]), jarray(String)([r.artist for r in rows]),
                  jarray(String)([r.album for r in rows]), jarray(String)([clock(r.seconds) for r in rows]),
                  jarray(String)(cover_paths), JInteger(shown_current))
        self.call("setDragEnabled", JBoolean(not self.query))
        missing = [r.path for r, c in zip(rows, cover_paths) if r.path and c is None]
        if missing:
            covers.warm(missing[:200])
        if not rows:
            self.empty.setText("Ничего не нашлось." if self.query else "Очередь пуста. Включите песню в Медиатеке или в чате.")
        self.empty.setVisibility(0 if not rows else 8)
        if scroll and shown_current >= 0:
            self.call("scrollTo", JInteger(shown_current), JInteger(_dp(120)))

    def cover_ready(self, path):
        """A cover read from its file: the row showing it gets it."""
        if not self.visible:
            return
        for position, index in enumerate(self.order):
            if self.rows[index].path == path:
                self.call("setCover", JInteger(position), self.music.covers.cached(path)[1])

    def playing_changed(self):
        if not self.visible:
            return
        if not self.is_active() and self.shown_key != self.store.active:
            self.shown_key = self.store.active
            self.refresh(scroll=True)
            return
        current = self.current_index()
        if current < 0 and self.rows:
            self.refresh()  # another list began: MediaController's queue changed under it
            return
        self.call("setCurrent", JInteger(self.order.index(current) if current in self.order else -1))
        self.position_text.setText("%d / %d" % (current + 1 if current >= 0 else 0, len(self.rows)))

    def searched(self, text):
        """Each letter narrows the rows already built; an emptied search goes back to the playing song."""
        query = text.strip()
        if query == self.query:
            return
        self.query = query
        self.apply_filter()
        self.guarded(self.show_rows, None, not query)

    # -- list events -------------------------------------------------------------------------

    def event(self, what, first, second, view):
        if what == ROW:
            self.guarded(self.row_pressed, self.order[first])
        elif what == MENU:
            self.guarded(self.song_menu, self.order[first], view)
        elif what == MOVED:
            self.guarded(self.moved, first, second)

    def row_pressed(self, index):
        row = self.rows[index]
        entry = self.shown_entry()
        self.hide_keyboard()
        if entry is None or self.is_active():
            if row.message is not None:
                self.controller().playMessage(row.message)
            return
        # a song of another queue: that queue plays, from this song
        if entry["kind"] == "library":
            tracks = [self.music.by_path[r.path] for r in self.rows if r.path in self.music.by_path]
            position = next((i for i, t in enumerate(tracks) if t["path"] == row.path), 0)
            self.music.play(tracks, position, entry["title"])
        else:
            entry["current"] = row.message.getId()
            entry["progress"] = 0.0
            self.store.switch(entry["key"])

    def moved(self, first, second):
        """A song dragged to another place: the queue that plays (or is kept) takes the new order."""
        entry = self.shown_entry()
        if entry is None or self.is_active():
            playlist, backwards = self.active_list()
            size = playlist.size()
            target = size - 1 - second if backwards else second
            message = self.rows[first].message
            playlist.remove(message)
            playlist.add(target, message)
            self.keep_position()
        elif entry["kind"] == "library":
            shown = [r.path for r in self.rows]
            shown.insert(second, shown.pop(first))
            entry["paths"] = shown
            self.store.save()
        self.rows.insert(second, self.rows.pop(first))
        self.order = list(range(len(self.rows)))
        current = self.current_index()
        self.position_text.setText("%d / %d" % (current + 1 if current >= 0 else 0, len(self.rows)))

    def keep_position(self):
        """After a change to the list that plays, MediaController's position points at the playing song again."""
        controller = self.controller()
        playing = controller.getPlayingMessageObject()
        if playing is None:
            return
        index = self.active_list()[0].indexOf(playing)
        if index >= 0:
            self.plugin.media_fields.set_int(controller, "currentPlaylistNum", index)

    # -- the queue picker and the bar ------------------------------------------------------------

    def pick_queue(self):
        if not self.store.entries:
            self.say("Очереди появятся, когда вы включите песню в Медиатеке или в чате.")
            return
        menu = self.plugin.sheet_menu(self.player.sheet, self.picker, False)
        later = self.player.start_menu()
        playing = self.resource("msg_played") or self.resource("player_new_play")
        for index, entry in enumerate(self.store.entries):
            mark = playing if entry["key"] == self.store.active else 0
            menu.add(mark, "%d. %s" % (index + 1, entry["title"]), later(lambda k=entry["key"]: self.show_queue(k)))
        self.player.show_menu(menu)

    def show_queue(self, key):
        self.shown_key = key
        self.query = ""
        self.search.setText("")
        self.refresh(scroll=True)

    def remove_queue(self):
        entry = self.shown_entry()
        if entry is None:
            return
        removed = self.store.remove(entry["key"])
        self.shown_key = self.store.active or (self.store.entries[-1]["key"] if self.store.entries else None)
        self.refresh(scroll=True)

        def undo():
            self.store.restore(removed)
            self.shown_key = entry["key"]
            self.refresh(scroll=True)

        self.plugin.bulletin_undo(self.player.sheet, "Очередь «%s» убрана." % entry["title"], lambda: self.guarded(undo))

    def play_queue(self):
        entry = self.shown_entry()
        controller = self.controller()
        if entry is None or self.is_active():
            playing = controller.getPlayingMessageObject()
            if playing is not None and controller.isMessagePaused():
                controller.playMessage(playing)
            return
        self.store.switch(entry["key"])

    def save_queue(self):
        self.say("Сохранение очереди в плейлист появится вместе с плейлистами.")

    def library_tracks(self):
        """The shown queue as library songs, or None when it is a chat's queue."""
        entry = self.shown_entry()
        if entry is not None and entry["kind"] != "library":
            return None
        paths = [r.path for r in self.rows]
        if not paths or any(p is None for p in paths):
            return None
        by_path = self.music.by_path
        return [by_path[p] for p in paths if p in by_path]

    def reorder(self, key=None, shuffle=False, reverse=False):
        tracks = self.library_tracks()
        if tracks is None:
            self.say("Упорядочить можно очередь из Медиатеки.")
            return
        current = self.current_index()
        current_path = self.rows[current].path if current >= 0 else None
        if shuffle:
            random.shuffle(tracks)
        elif reverse:
            tracks.reverse()
        else:
            tracks.sort(key=lambda t: (t.get(key) or "").lower())
        entry = self.shown_entry()
        if entry is not None and not self.is_active():
            entry["paths"] = [t["path"] for t in tracks]
            self.store.save()
            self.refresh(scroll=True)
            return
        title = entry["title"] if entry is not None else self.music.queue_title
        playing = self.controller().getPlayingMessageObject()
        progress = float(playing.audioProgress) if playing is not None and current_path else 0.0
        index = next((i for i, t in enumerate(tracks) if t["path"] == current_path), 0)
        self.music.play(tracks, index, title, progress)

    def sort_menu(self):
        menu = self.plugin.sheet_menu(self.player.sheet, self.sort_button, False)
        later = self.player.start_menu()
        menu.add(self.resource("player_new_shuffle") or self.resource("msg_shuffle"), "Перемешать", later(lambda: self.reorder(shuffle=True)))
        menu.add(self.resource("msg_sort"), "По названию", later(lambda: self.reorder("title")))
        menu.add(self.resource("msg_contacts"), "По автору", later(lambda: self.reorder("artist")))
        menu.add(self.resource("msg_folders") or self.resource("msg2_folder"), "По альбому", later(lambda: self.reorder("album")))
        menu.add(self.resource("msg_reorder") or self.resource("msg_sort"), "В обратном порядке", later(lambda: self.reorder(reverse=True)))
        self.player.show_menu(menu)

    def queue_menu(self):
        menu = self.plugin.sheet_menu(self.player.sheet, self.more_button, False)
        later = self.player.start_menu()
        menu.add(self.resource("msg_go_up") or self.resource("msg_arrowright"), "К текущей песне", later(lambda: self.refresh(scroll=True)))
        menu.add(self.resource("msg_delete"), "Убрать очередь", later(self.remove_queue))
        self.player.show_menu(menu)

    # -- a song's menu ----------------------------------------------------------------------

    def song_menu(self, index, anchor):
        from .song_menu import SongMenu
        SongMenu(self, self.rows[index], anchor).show()

    # -- end ------------------------------------------------------------------------------------

    def dispose(self):
        self.visible = False
        self.events.screen = None
        if self.watcher is not None:
            self.watcher.action = None
            try:
                self.search.removeTextChangedListener(self.watcher)
            except Exception:
                pass
        for view in self.clicks:
            try:
                view.setOnClickListener(None)
            except Exception:
                pass
        self.clicks = []
        self.rows = []
