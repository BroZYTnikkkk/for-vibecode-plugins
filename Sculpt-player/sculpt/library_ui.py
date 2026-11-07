# Sculpt Player for exteraGram. Copyright 2026 BroNik (@BroZYTnikkkk).

import random
import re
import time

from android_utils import OnClickListener, run_on_ui_thread
from java import dynamic_proxy, jarray, jclass

from .common import COLORS_SECONDS, COVERS_DELIVERY_MS, GROUP_COVER_TRIES, NO_TRACK_NUMBER, PANEL_ACTIVE, PERMISSION_POLLS, PERMISSION_REQUEST, PREVIEW_MAX, SORT_MODES, THUMB_AREA, THUMB_H, THUMB_MIN_ROWS, TILE_RADIUS, TILE_SIZE, _dp, tab_scrim
from .music import first_letter, format_time, local_path, songs_label, sort_text, track_number


# ---------------------------------------------------------------------------
# Media library: the screens
# ---------------------------------------------------------------------------


class Run(dynamic_proxy(jclass("java.lang.Runnable"))):
    def __init__(self, action):
        super().__init__()
        self.action = action

    def run(self):
        if self.action is not None:
            self.action()


def release_on_dismiss(menu, runs):
    """Chaquopy cannot collect a cycle that runs through Java and Python, and a menu item's Runnable holds the
    menu that holds it. When the menu closes, the Runnables let go of everything they captured."""

    def release():
        for run in runs:
            # a view of the menu's own (a header with a button) lets go of its listener here too
            cleanup = getattr(run, "cleanup", None)
            if cleanup is not None:
                run.cleanup = None
                cleanup()
            run.action = None

    closer = Run(release)
    runs.append(closer)
    menu.setOnDismiss(closer)


class LongClick(dynamic_proxy(jclass("android.view.View$OnLongClickListener"))):
    def __init__(self, action):
        super().__init__()
        self.action = action

    def onLongClick(self, view):
        self.action(view)
        return True


class RowClick(dynamic_proxy(jclass("android.widget.AdapterView$OnItemClickListener"))):
    def __init__(self, screen):
        super().__init__()
        self.screen = screen

    def onItemClick(self, parent, view, position, row_id):
        index = position - self.screen.list.getHeaderViewsCount()
        if index >= 0:
            self.screen.guarded(self.screen.row_clicked, index, view)


class RowLongClick(dynamic_proxy(jclass("android.widget.AdapterView$OnItemLongClickListener"))):
    def __init__(self, screen):
        super().__init__()
        self.screen = screen

    def onItemLongClick(self, parent, view, position, row_id):
        index = position - self.screen.list.getHeaderViewsCount()
        if index < 0:
            return False
        self.screen.guarded(self.screen.row_long_clicked, index, view)
        return True


class RowsAdapter(dynamic_proxy(jclass("android.widget.ListAdapter"))):
    """RecyclerView.Adapter is a class and a proxy can only be an interface, so the long lists are ListViews."""

    def __init__(self, screen):
        super().__init__()
        self.screen = screen
        self.observers = []

    def changed(self):
        for observer in list(self.observers):
            observer.onChanged()

    def registerDataSetObserver(self, observer):
        self.observers.append(observer)

    def unregisterDataSetObserver(self, observer):
        self.observers = [o for o in self.observers if not o.equals(observer)]

    def getCount(self):
        return self.screen.count()

    def getItem(self, position):
        return None

    def getItemId(self, position):
        return position

    def hasStableIds(self):
        return False

    def getView(self, position, convert, parent):
        try:
            return self.screen.row_view(position, convert)
        except Exception as e:
            self.screen.owner.plugin.report("row", e)
            return convert if convert is not None else jclass("android.view.View")(parent.getContext())

    def getItemViewType(self, position):
        return 0

    def getViewTypeCount(self):
        return 1

    def isEmpty(self):
        return self.screen.count() == 0

    def areAllItemsEnabled(self):
        return True

    def isEnabled(self, position):
        return True

    def getAutofillOptions(self):
        return None


class TextChanged(dynamic_proxy(jclass("android.text.TextWatcher"))):
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


class ThumbTouch(dynamic_proxy(jclass("android.view.View$OnTouchListener"))):
    def __init__(self, screen):
        super().__init__()
        self.screen = screen

    def onTouch(self, view, event):
        try:
            return self.screen.thumb_touched(view, event)
        except Exception as e:
            self.screen.owner.plugin.report("thumb", e)
            return False


class ListScrolled(dynamic_proxy(jclass("android.widget.AbsListView$OnScrollListener"))):
    def __init__(self, screen):
        super().__init__()
        self.screen = screen

    def onScrollStateChanged(self, view, state):
        self.screen.scroll_state_changed(state)

    def onScroll(self, view, first, visible, total):
        self.screen.list_scrolled(first, visible, total)


class Screen:
    """One level of the library: a header and a body. It stays alive under the next one, so going back keeps its place."""

    def __init__(self, owner, title, subtitle=""):
        self.owner = owner
        self.tints = []
        self.keep = []
        self.title_text = title
        self.subtitle_text = subtitle
        self.view = None
        self.title_view = None
        self.subtitle_view = None

    def guarded(self, action, *args):
        try:
            action(*args)
        except Exception as e:
            self.owner.plugin.report("library", e)

    def click(self, view, action, *args):
        listener = OnClickListener(lambda _: self.guarded(action, *args))
        self.keep.append((view, "click"))
        view.setOnClickListener(listener)

    def long_click(self, view, action):
        listener = LongClick(lambda v: self.guarded(action, v))
        self.keep.append((view, "long"))
        view.setOnLongClickListener(listener)

    def dispose(self):
        """Lets go of every listener by hand.

        A Python listener held by a Java view, whose closure holds this screen and its views, is a cycle that
        Chaquopy never collects: a screen left like that stays in memory with all its views and covers.
        """
        for view, kind in self.keep:
            try:
                if kind == "click":
                    view.setOnClickListener(None)
                else:
                    view.setOnLongClickListener(None)
            except Exception:
                pass
        self.keep = []
        self.tints = []

    def tint_text(self, view, role):
        self.tints.append((True, view, role))
        view.setTextColor(self.owner.color(role))
        return view

    def tint_icon(self, view, role):
        self.tints.append((False, view, role))
        self.owner.tint(view, self.owner.color(role))
        return view

    def retint(self):
        owner = self.owner
        for is_text, view, role in self.tints:
            if is_text:
                view.setTextColor(owner.color(role))
            else:
                owner.tint(view, owner.color(role))
        self.colors_changed()

    def colors_changed(self):
        pass

    def label(self, size, role, bold=False):
        return self.tint_text(self.owner.text_view(size, bold), role)

    def icon_button(self, icons, description, action, *args):
        owner = self.owner
        button = jclass("android.widget.ImageView")(owner.context)
        owner.set_icon(button, icons)
        button.setScaleType(jclass("android.widget.ImageView$ScaleType").CENTER)
        button.setContentDescription(description)
        button.setBackground(owner.selector(_dp(20)))
        self.tint_icon(button, "icon")
        self.click(button, action, *args)
        return button

    def header(self, large=False, trailing=None):
        owner = self.owner
        LinearLayout = jclass("android.widget.LinearLayout$LayoutParams")
        row = jclass("android.widget.LinearLayout")(owner.context)
        row.setOrientation(0)
        row.setGravity(16)  # center vertically
        row.setPadding(_dp(8), _dp(8), _dp(8), _dp(8))
        if large:
            row.addView(self.icon_button(("arrow_more",), "Закрыть плеер", owner.close_player), owner.params(40, 40))
        else:
            row.addView(self.icon_button(("ic_ab_back",), "Назад", owner.back), owner.params(40, 40))
        column = jclass("android.widget.LinearLayout")(owner.context)
        column.setOrientation(1)
        self.title_view = self.label(28 if large else 20, "text", True)
        self.title_view.setText(self.title_text)
        column.addView(self.title_view)
        self.subtitle_view = self.label(13, "textSecondary")
        self.subtitle_view.setText(self.subtitle_text)
        self.subtitle_view.setVisibility(0 if self.subtitle_text else 8)
        column.addView(self.subtitle_view)
        place = LinearLayout(0, -2, 1.0)
        place.setMarginStart(_dp(8))
        row.addView(column, place)
        if trailing is not None:
            row.addView(trailing, owner.params(40, 40))
        return row

    def set_subtitle(self, text):
        self.subtitle_view.setText(text)
        self.subtitle_view.setVisibility(0 if text else 8)

    def refresh(self):
        pass

    def tile(self, image_path, title, subtitle, action, long_action=None):
        """A cover with two lines under it, for the rows that scroll sideways."""
        owner = self.owner
        Params = jclass("android.widget.LinearLayout$LayoutParams")
        tile = jclass("android.widget.LinearLayout")(owner.context)
        tile.setOrientation(1)
        image = owner.cover_view(TILE_RADIUS, TILE_SIZE)
        owner.bind_cover(image, image_path, TILE_SIZE)
        tile.addView(image, owner.params(TILE_SIZE, TILE_SIZE))
        name = self.label(14, "text", True)
        name.setText(title)
        top = Params(_dp(TILE_SIZE), -2)
        top.topMargin = _dp(6)
        tile.addView(name, top)
        second = self.label(12, "textSecondary")
        second.setText(subtitle)
        tile.addView(second, Params(_dp(TILE_SIZE), -2))
        self.click(tile, action)
        if long_action is not None:
            self.long_click(tile, long_action)
        return {"view": tile, "image": image, "name": name, "second": second}

    def nav_row(self, container, icons, title, action):
        """A place to go: an icon, the name, room for a count, an arrow. Returns the count's view."""
        owner = self.owner
        Params = jclass("android.widget.LinearLayout$LayoutParams")
        ImageView = jclass("android.widget.ImageView")
        row = jclass("android.widget.LinearLayout")(owner.context)
        row.setOrientation(0)
        row.setGravity(16)
        row.setPadding(_dp(20), 0, _dp(16), 0)
        row.setBackground(owner.selector(0))
        icon = ImageView(owner.context)
        owner.set_icon(icon, icons)
        self.tint_icon(icon, "icon")
        row.addView(icon, owner.params(24, 24))
        name = self.label(16, "text")
        name.setText(title)
        name_at = Params(0, -2, 1.0)
        name_at.setMarginStart(_dp(16))
        row.addView(name, name_at)
        count = self.label(14, "textSecondary")
        row.addView(count)
        arrow = ImageView(owner.context)
        owner.set_icon(arrow, ("msg_arrowright",))
        self.tint_icon(arrow, "textSecondary")
        arrow_at = owner.params(24, 24)
        arrow_at.setMarginStart(_dp(4))
        row.addView(arrow, arrow_at)
        self.click(row, action)
        container.addView(row, Params(-1, _dp(56)))
        return count

    def search_pill(self, container, text, action):
        """A field-shaped button that opens a search screen; the field itself, with the keyboard, is there."""
        owner = self.owner
        Params = jclass("android.widget.LinearLayout$LayoutParams")
        pill = jclass("android.widget.LinearLayout")(owner.context)
        pill.setOrientation(0)
        pill.setGravity(16)
        pill.setPadding(_dp(16), 0, _dp(16), 0)
        icon = jclass("android.widget.ImageView")(owner.context)
        owner.set_icon(icon, ("outline_search_1_24", "msg_search"))
        self.tint_icon(icon, "textSecondary")
        pill.addView(icon, owner.params(24, 24))
        label = self.label(16, "textSecondary")
        label.setText(text)
        label_at = Params(0, -2, 1.0)
        label_at.setMarginStart(_dp(12))
        pill.addView(label, label_at)
        pill.setContentDescription(text)
        self.click(pill, action)
        place = Params(-1, _dp(48))
        place.setMargins(_dp(16), _dp(4), _dp(16), _dp(8))
        container.addView(pill, place)
        self.pills = getattr(self, "pills", []) + [pill]
        self.paint_pills()
        return pill

    def paint_pills(self):
        owner = self.owner
        for pill in getattr(self, "pills", ()):
            pill.setBackground(owner.rounded(owner.color("surfaceContainer"), _dp(24)))

    def sideways(self):
        """(scroller, row) for covers in a line."""
        owner = self.owner
        scroller = jclass("android.widget.HorizontalScrollView")(owner.context)
        scroller.setHorizontalScrollBarEnabled(False)
        scroller.setOverScrollMode(2)
        scroller.setClipToPadding(False)
        scroller.setPadding(_dp(20), 0, _dp(8), 0)
        row = jclass("android.widget.LinearLayout")(owner.context)
        row.setOrientation(0)
        scroller.addView(row)
        return scroller, row


class ListScreen(Screen):
    """A header and a long list with a slider at the edge that jumps through it and names the place."""

    def __init__(self, owner, title, subtitle="", list_header=None):
        super().__init__(owner, title, subtitle)
        self.list_header = list_header
        self.holders = {}  # row view id -> its parts; the screen's own, so the rows go when the screen does
        self.adapter = None
        self.list = None
        self.empty = None
        self.track_view = None
        self.thumb = None
        self.bubble = None
        self.scrolling = False
        self.change_waiting = False

    def build(self, trailing=None, empty_text=""):
        owner = self.owner
        context = owner.context
        Linear = jclass("android.widget.LinearLayout$LayoutParams")
        Frame = jclass("android.widget.FrameLayout$LayoutParams")
        page = jclass("android.widget.LinearLayout")(context)
        page.setOrientation(1)
        page.addView(self.header(False, trailing))
        bar = self.toolbar()
        if bar is not None:
            page.addView(bar)
        body = jclass("android.widget.FrameLayout")(context)
        page.addView(body, Linear(-1, 0, 1.0))
        self.view = page

        rows = jclass("android.widget.ListView")(context)
        rows.setDivider(None)
        rows.setDividerHeight(0)
        rows.setCacheColorHint(0)
        rows.setVerticalScrollBarEnabled(False)
        rows.setOverScrollMode(2)
        rows.setClipToPadding(False)
        rows.setPadding(0, 0, 0, _dp(8))
        rows.setSelector(owner.selector(0))
        rows.setDrawSelectorOnTop(True)
        self.list = rows
        if self.list_header is not None:
            header = self.list_header(self)
            if header is not None:
                rows.addHeaderView(header, None, False)
        self.adapter = RowsAdapter(self)
        rows.setAdapter(self.adapter)
        rows.setOnItemClickListener(RowClick(self))
        rows.setOnItemLongClickListener(RowLongClick(self))
        rows.setOnScrollListener(ListScrolled(self))
        body.addView(rows, Frame(-1, -1))

        self.empty = self.label(15, "textSecondary")
        self.empty.setText(empty_text)
        self.empty.setGravity(17)
        self.empty.setSingleLine(False)
        self.empty.setPadding(_dp(32), 0, _dp(32), _dp(32))
        self.empty.setVisibility(8)
        body.addView(self.empty, Frame(-1, -1))

        # The slider: wide enough for a finger to catch, with a thin mark and a bubble naming the place.
        self.track_view = jclass("android.view.View")(context)
        self.track_view.setOnTouchListener(ThumbTouch(self))
        body.addView(self.track_view, Frame(_dp(THUMB_AREA), -1, 8388613))  # end
        self.thumb = jclass("android.view.View")(context)
        mark = Frame(_dp(4), _dp(THUMB_H), 8388661)  # top end
        mark.setMarginEnd(_dp(4))
        body.addView(self.thumb, mark)
        self.bubble = owner.text_view(22, True)
        self.bubble.setGravity(17)
        self.bubble.setVisibility(8)
        place = Frame(_dp(84), _dp(56), 8388661)
        place.setMarginEnd(_dp(THUMB_AREA + 8))
        body.addView(self.bubble, place)
        self.paint_slider()
        self.refresh()

    def toolbar(self):
        return None

    def paint_slider(self):
        owner = self.owner
        self.thumb.setBackground(owner.rounded(owner.color("accent"), _dp(2)))
        self.bubble.setTextColor(owner.color("onAccent"))
        self.bubble.setBackground(owner.rounded(owner.color("accent"), _dp(16)))

    def colors_changed(self):
        self.paint_slider()
        self.adapter.changed()

    def dispose(self):
        super().dispose()
        try:
            self.list.setOnItemClickListener(None)
            self.list.setOnItemLongClickListener(None)
            self.list.setOnScrollListener(None)
            self.list.setAdapter(None)
            self.track_view.setOnTouchListener(None)
        except Exception:
            pass
        if self.adapter is not None:
            self.adapter.observers = []
        self.holders = {}

    def data_refreshed(self):
        count = self.count()
        self.empty.setVisibility(8 if count else 0)
        self.list.setVisibility(0 if count else 8)
        show = 0 if count >= THUMB_MIN_ROWS else 8
        self.thumb.setVisibility(show)
        self.track_view.setVisibility(show)
        self.adapter.changed()

    def scroll_state_changed(self, state):
        """0 is idle: a rebind put off while the finger or the fling moved the list happens now."""
        self.scrolling = state != 0
        if not self.scrolling and self.change_waiting:
            self.change_waiting = False
            self.adapter.changed()

    def changed_when_still(self):
        """Rebinding every row in the middle of a fling costs frames: it waits for the list to stop."""
        if self.scrolling:
            self.change_waiting = True
        else:
            self.adapter.changed()

    def list_scrolled(self, first, visible, total):
        room = total - visible
        height = self.list.getHeight() - _dp(THUMB_H)
        if room > 0 and height > 0 and self.thumb is not None:
            self.thumb.setTranslationY(float(height) * first / room)

    def thumb_touched(self, view, event):
        action = event.getActionMasked()
        if action in (1, 3):  # up, cancel
            self.bubble.setVisibility(8)
            return True
        if action not in (0, 2):  # down, move
            return True
        view.getParent().requestDisallowInterceptTouchEvent(True)
        height = max(1, view.getHeight())
        share = max(0.0, min(1.0, event.getY() / height))
        count = self.count()
        if count <= 0:
            return True
        index = min(count - 1, int(share * count))
        self.list.setSelectionFromTop(index + self.list.getHeaderViewsCount(), 0)
        self.bubble.setText(self.letter(index))
        self.bubble.setVisibility(0)
        self.bubble.setTranslationY(float(max(0, int(share * height) - _dp(28))))
        return True

    def count(self):
        return 0

    def letter(self, index):
        return ""

    def row_view(self, position, convert):
        raise NotImplementedError

    def row_clicked(self, index, view):
        pass

    def row_long_clicked(self, index, view):
        pass


class SongsScreen(ListScreen):
    """A list of songs. Any of them starts the whole list from itself. Over the list: a search that narrows
    it and "Shuffle", which starts a random song of it."""

    FILTERED = True  # the library's own search screen has its own field instead

    def __init__(self, owner, title, source, list_id=None, default_sort="title", empty_text="", list_header=None, fav_dates=False):
        super().__init__(owner, title, "", list_header)
        self.filter_query = ""
        self.filter_field = None
        self.filter_watcher = None
        self.filter_clear = None
        self.filter_pill = None
        self.shuffle_pill = None
        self.empty_text = empty_text
        self.source = source
        self.list_id = list_id
        self.default_sort = default_sort
        self.fav_dates = fav_dates
        self.tracks = []
        self.sort_mode, self.reverse = self.read_sort()
        trailing = None
        if list_id is not None:
            trailing = self.icon_button(("msg_filter",), "Сортировка", self.show_sort)
        self.build(trailing, empty_text)

    def toolbar(self):
        if not self.FILTERED:
            return None
        owner = self.owner
        Params = jclass("android.widget.LinearLayout$LayoutParams")
        bar = jclass("android.widget.LinearLayout")(owner.context)
        bar.setOrientation(0)
        bar.setGravity(16)
        bar.setPadding(_dp(16), _dp(2), _dp(16), _dp(8))

        pill = jclass("android.widget.LinearLayout")(owner.context)
        pill.setOrientation(0)
        pill.setGravity(16)
        pill.setPadding(_dp(14), 0, _dp(4), 0)
        icon = jclass("android.widget.ImageView")(owner.context)
        owner.set_icon(icon, ("outline_search_1_24", "msg_search"))
        self.tint_icon(icon, "textSecondary")
        pill.addView(icon, owner.params(20, 20))
        field = jclass("android.widget.EditText")(owner.context)
        field.setHint("Искать в списке")
        field.setTextSize(1, 15.0)
        field.setSingleLine(True)
        field.setBackground(None)
        field.setPadding(_dp(10), 0, _dp(4), 0)
        field.setImeOptions(6)  # EditorInfo.IME_ACTION_DONE: the list narrows as one types
        self.filter_field = field
        self.paint_filter()
        self.filter_watcher = TextChanged(lambda text: self.guarded(self.filter_changed, text))
        field.addTextChangedListener(self.filter_watcher)
        pill.addView(field, Params(0, -1, 1.0))
        self.filter_clear = self.icon_button(("msg_close", "ic_close_white"), "Очистить поиск", self.clear_filter)
        self.filter_clear.setVisibility(8)
        pill.addView(self.filter_clear, owner.params(36, 36))
        self.filter_pill = pill
        bar.addView(pill, Params(0, _dp(44), 1.0))

        shuffle = jclass("android.widget.LinearLayout")(owner.context)
        shuffle.setOrientation(0)
        shuffle.setGravity(17)
        shuffle.setPadding(_dp(14), 0, _dp(16), 0)
        mark = jclass("android.widget.ImageView")(owner.context)
        owner.set_icon(mark, ("player_new_shuffle", "player_shuffle", "msg_shuffle"))
        self.tint_icon(mark, "accent")
        shuffle.addView(mark, owner.params(20, 20))
        word = self.label(15, "accent", True)
        word.setText("Перемешать")
        at = Params(-2, -2)
        at.setMarginStart(_dp(6))
        shuffle.addView(word, at)
        shuffle.setContentDescription("Перемешать: включить случайную песню из этого списка")
        self.click(shuffle, self.shuffle)
        self.shuffle_pill = shuffle
        place = Params(-2, _dp(44))
        place.setMarginStart(_dp(8))
        bar.addView(shuffle, place)
        self.paint_bar()
        return bar

    def paint_filter(self):
        self.filter_field.setTextColor(self.owner.color("text"))
        self.filter_field.setHintTextColor(self.owner.color("textSecondary"))

    def paint_bar(self):
        owner = self.owner
        self.filter_pill.setBackground(owner.rounded(owner.color("surfaceContainer"), _dp(22)))
        tint = jclass("androidx.core.graphics.ColorUtils").setAlphaComponent(owner.color("accent"), 40)
        self.shuffle_pill.setBackground(owner.rounded(tint, _dp(22)))

    def colors_changed(self):
        super().colors_changed()
        if self.filter_field is not None:
            self.paint_filter()
            self.paint_bar()

    def filter_changed(self, text):
        query = text.strip()
        self.filter_clear.setVisibility(0 if text else 8)
        if query == self.filter_query:
            return
        self.filter_query = query
        self.refresh()
        self.list.setSelection(0)

    def clear_filter(self):
        if self.filter_field is not None:
            self.filter_field.setText("")
        self.close_keyboard()

    def filtered(self, tracks):
        query = self.filter_query.casefold()
        if not query:
            return tracks
        return [t for t in tracks if query in t["title"].casefold() or query in t["artist"].casefold()
                or query in (t.get("album") or "").casefold()]

    def shuffle(self):
        """A random song of this list (of what the search left); the player's shuffle mode decides the rest."""
        if not self.tracks:
            self.owner.plugin.bulletin(self.owner.player.sheet, "info", "В этом списке нет песен.")
            return
        self.close_keyboard()
        self.owner.play(self.tracks, random.randrange(len(self.tracks)), self.title_text)

    def close_keyboard(self):
        if self.filter_field is not None:
            try:
                jclass("org.telegram.messenger.AndroidUtilities").hideKeyboard(self.filter_field)
                self.filter_field.clearFocus()
            except Exception:
                pass

    def dispose(self):
        if self.filter_watcher is not None:
            self.close_keyboard()
            self.filter_watcher.action = None
            try:
                self.filter_field.removeTextChangedListener(self.filter_watcher)
            except Exception:
                pass
            self.filter_watcher = None
        super().dispose()

    def read_sort(self):
        if self.list_id is None:
            return None, False
        stored = str(self.owner.plugin.get_setting("sort_" + self.list_id, self.default_sort + ":0"))
        mode, _, flag = stored.partition(":")
        return mode, flag == "1"

    def show_sort(self):
        owner = self.owner
        check = owner.resource("msg_text_check")
        menu = owner.make_menu(self.title_view, False)
        later = owner.player.start_menu()
        modes = list(SORT_MODES)
        if self.default_sort == "track":
            modes.insert(0, ("track", "По номеру"))
        for mode, title in modes:
            menu.add(check if mode == self.sort_mode else 0, title,
                     later(lambda m=mode: self.pick_sort(menu, m, self.reverse)))
        menu.addGap()
        menu.add(check if self.reverse else 0, "В обратном порядке", later(lambda: self.pick_sort(menu, self.sort_mode, not self.reverse)))
        owner.player.show_menu(menu)

    def pick_sort(self, menu, mode, reverse):
        try:
            menu.dismiss()
            self.sort_mode, self.reverse = mode, reverse
            self.owner.plugin.set_setting("sort_" + self.list_id, "%s:%d" % (mode, 1 if reverse else 0))
            self.refresh()
            self.list.setSelection(0)
        except Exception as e:
            self.owner.plugin.report("sort", e)

    def when(self, track):
        return self.owner.data.favorites.get(track["path"], 0) if self.fav_dates else track.get("added", 0)

    def sort_key(self, track):
        mode = self.sort_mode
        if mode == "artist":
            return sort_text(track["artist"]), sort_text(track["title"])
        if mode == "album":
            # songs with no album go last, not first
            album = sort_text(track["album"])
            return not album, album, track_number(track), sort_text(track["title"])
        if mode == "added":
            return -self.when(track)
        if mode == "duration":
            return track.get("duration", 0)
        if mode == "track":
            return track_number(track), sort_text(track["title"])
        return sort_text(track["title"])

    def refresh(self):
        everything = list(self.source())
        tracks = self.filtered(everything) if self.FILTERED else everything
        if self.sort_mode is not None:
            tracks.sort(key=self.sort_key, reverse=self.reverse)
        self.tracks = tracks
        if self.FILTERED and self.filter_query:
            self.set_subtitle("%d из %s" % (len(tracks), songs_label(len(everything))))
            if self.empty is not None:
                self.empty.setText("Ничего не нашлось по «%s» в этом списке." % self.filter_query)
        else:
            self.set_subtitle(songs_label(len(tracks)) if tracks else "")
            if self.empty is not None and self.FILTERED:
                self.empty.setText(self.empty_text)
        if self.shuffle_pill is not None:
            self.shuffle_pill.setVisibility(0 if tracks else 8)
        self.data_refreshed()

    def count(self):
        return len(self.tracks)

    def letter(self, index):
        track = self.tracks[index]
        mode = self.sort_mode
        if mode == "artist":
            return first_letter(track["artist"])
        if mode == "album":
            return first_letter(track["album"])
        if mode == "added":
            return time.strftime("%m.%y", time.localtime(self.when(track)))
        if mode == "duration":
            return "%d мин" % (track.get("duration", 0) // 60)
        if mode == "track":
            number = track_number(track)
            return str(number % 1000) if number < NO_TRACK_NUMBER else "#"
        return first_letter(track["title"])

    def row_view(self, position, convert):
        owner = self.owner
        if convert is None:
            convert = owner.song_row(self.holders)
        holder = self.holders[convert.hashCode()]
        track = self.tracks[position]
        path = track["path"]
        owner.bind_cover(holder["image"], path, 48)
        holder["title"].setText(track["title"])
        holder["subtitle"].setText(track["artist"])
        holder["time"].setText(format_time(track.get("duration", 0)))
        playing = path == owner.playing_path()
        holder["title"].setTextColor(owner.color("accent") if playing else owner.color("text"))
        holder["title"].setTypeface(owner.bold if playing else owner.regular)
        holder["subtitle"].setTextColor(owner.color("textSecondary"))
        holder["time"].setTextColor(owner.color("textSecondary"))
        return convert

    def row_clicked(self, index, view):
        self.close_keyboard()
        self.owner.play(self.tracks, index, self.title_text)

    def row_long_clicked(self, index, view):
        self.owner.song_menu(view, self.tracks[index])


class GroupsScreen(ListScreen):
    """Authors, albums or genres; a tap opens the songs of one."""

    def __init__(self, owner, kind, title):
        super().__init__(owner, title)
        self.kind = kind
        self.items = []
        empty = {"artists": "Здесь появятся авторы твоих песен.",
                 "albums": "Здесь появятся альбомы. Песни без альбома в тегах сюда не попадают.",
                 "genres": "Здесь появятся жанры. Android знает их только из тегов файлов, а у этих песен жанр не указан."}[kind]
        self.build(None, empty)

    def refresh(self):
        self.items = self.owner.data.groups()[self.kind]
        self.set_subtitle(str(len(self.items)) if self.items else "")
        self.data_refreshed()

    def count(self):
        return len(self.items)

    def letter(self, index):
        return first_letter(self.items[index]["name"])

    def row_view(self, position, convert):
        owner = self.owner
        if convert is None:
            convert = owner.group_row(self.kind, self.holders)
        holder = self.holders[convert.hashCode()]
        item = self.items[position]
        holder["title"].setText(item["name"])
        holder["title"].setTextColor(owner.color("text"))
        count = songs_label(len(item["tracks"]))
        holder["subtitle"].setText("%s, %s" % (item["artist"], count) if self.kind == "albums" else count)
        holder["subtitle"].setTextColor(owner.color("textSecondary"))
        if "letter" in holder:
            holder["letter"].setText(first_letter(item["name"]))
            holder["letter"].setTextColor(owner.color("textSecondary"))
        if "image" in holder:
            owner.bind_cover(holder["image"], owner.group_cover(item["tracks"]), 48)
        return convert

    def row_clicked(self, index, view):
        self.owner.open_group(self.kind, self.items[index])


class BlankScreen(Screen):
    """Popular songs: only the place for them, until there is something to count."""

    def __init__(self, owner, title, text):
        super().__init__(owner, title)
        page = jclass("android.widget.LinearLayout")(owner.context)
        page.setOrientation(1)
        page.addView(self.header())
        label = self.label(15, "textSecondary")
        label.setText(text)
        label.setGravity(17)
        label.setSingleLine(False)
        label.setPadding(_dp(32), 0, _dp(32), _dp(56))
        page.addView(label, jclass("android.widget.LinearLayout$LayoutParams")(-1, 0, 1.0))
        self.view = page


class SearchScreen(SongsScreen):
    """Songs of the library by name, author or album; each letter narrows the list."""

    HINT = "Начни вводить название песни, автора или альбом."
    FILTERED = False

    def __init__(self, owner):
        self.query = ""
        self.field = None
        self.watcher = None
        super().__init__(owner, "Поиск", self.matches, None, "title", self.HINT)
        run_on_ui_thread(self.open_keyboard, 250)

    def header(self, large=False, trailing=None):
        owner = self.owner
        row = jclass("android.widget.LinearLayout")(owner.context)
        row.setOrientation(0)
        row.setGravity(16)
        row.setPadding(_dp(8), _dp(8), _dp(8), _dp(8))
        row.addView(self.icon_button(("ic_ab_back",), "Назад", owner.back), owner.params(40, 40))
        self.field = jclass("android.widget.EditText")(owner.context)
        self.field.setHint("Песня, автор или альбом")
        self.field.setTextSize(1, 18.0)
        self.field.setSingleLine(True)
        self.field.setBackground(None)
        self.field.setPadding(_dp(12), 0, _dp(8), 0)
        self.paint_field()
        self.watcher = TextChanged(lambda text: self.guarded(self.searched, text))
        self.field.addTextChangedListener(self.watcher)
        row.addView(self.field, jclass("android.widget.LinearLayout$LayoutParams")(0, _dp(48), 1.0))
        # the list's subtitle has nowhere to go here: views of their own, never shown
        self.title_view = owner.text_view(13)
        self.subtitle_view = owner.text_view(13)
        return row

    def paint_field(self):
        self.field.setTextColor(self.owner.color("text"))
        self.field.setHintTextColor(self.owner.color("textSecondary"))

    def colors_changed(self):
        super().colors_changed()
        self.paint_field()

    def matches(self):
        query = self.query.casefold()
        if not query:
            return []
        found = [t for t in self.owner.data.tracks
                 if query in t["title"].casefold() or query in t["artist"].casefold() or query in (t.get("album") or "").casefold()]
        # a title that starts with the query, then one with a word that does, then any title that has it,
        # then the authors and albums
        word = re.compile(r"(?:^|\W)" + re.escape(query))

        def rank(track):
            title = track["title"].casefold()
            return (not title.startswith(query), not word.search(title), query not in title, sort_text(track["title"]))

        found.sort(key=rank)
        return found

    def searched(self, text):
        query = text.strip()
        if query == self.query:
            return
        self.query = query
        self.refresh()
        self.list.setSelection(0)

    def refresh(self):
        super().refresh()
        if self.empty is not None:
            self.empty.setText("Ничего не нашлось по запросу «%s»." % self.query if self.query else self.HINT)

    def open_keyboard(self):
        if self.field is not None and self.owner.visible:
            self.field.requestFocus()
            jclass("org.telegram.messenger.AndroidUtilities").showKeyboard(self.field)

    def close_keyboard(self):
        if self.field is not None:
            try:
                jclass("org.telegram.messenger.AndroidUtilities").hideKeyboard(self.field)
                self.field.clearFocus()
            except Exception:
                pass

    def row_clicked(self, index, view):
        self.close_keyboard()
        self.owner.play(self.tracks, index, "Поиск: %s" % self.query)

    def dispose(self):
        self.close_keyboard()
        if self.watcher is not None:
            self.watcher.action = None
            try:
                self.field.removeTextChangedListener(self.watcher)
            except Exception:
                pass
        self.watcher = None
        self.field = None
        super().dispose()


class RootScreen(Screen):
    """The first level: places to go first, the two rows of covers under them."""

    def __init__(self, owner):
        super().__init__(owner, "Медиатека")
        LinearLayout = jclass("android.widget.LinearLayout")
        Params = jclass("android.widget.LinearLayout$LayoutParams")
        context = owner.context
        page = LinearLayout(context)
        page.setOrientation(1)
        page.addView(self.header(True))
        self.scroll = jclass("android.widget.ScrollView")(context)
        self.scroll.setVerticalScrollBarEnabled(False)
        self.scroll.setOverScrollMode(2)
        self.content = LinearLayout(context)
        self.content.setOrientation(1)
        self.content.setPadding(0, 0, 0, _dp(16))
        self.scroll.addView(self.content)
        page.addView(self.scroll, Params(-1, 0, 1.0))

        self.message = self.label(15, "textSecondary")
        self.message.setGravity(17)
        self.message.setSingleLine(False)
        self.message.setPadding(_dp(32), 0, _dp(32), _dp(16))
        self.button = self.label(15, "onAccent", True)
        self.button.setGravity(17)
        self.button.setText("Разрешить")
        self.click(self.button, owner.ask_permission)
        self.notice = LinearLayout(context)
        self.notice.setOrientation(1)
        self.notice.setGravity(17)
        self.notice.addView(self.message, Params(-1, -2))
        button_at = Params(_dp(180), _dp(44))
        button_at.gravity = 1
        self.notice.addView(self.button, button_at)
        page.addView(self.notice, Params(-1, 0, 1.0))
        self.view = page

        self.counts = {}
        self.tile_views = []
        self.search_pill(self.content, "Искать в медиатеке", owner.open_search)
        self.nav("all",("msg_filled_data_music", "msg_played"), "Все песни", owner.open_all)
        self.nav("favorites", ("media_like",), "Любимые", owner.open_favorites)
        self.nav(None, ("msg_stats",), "Популярные", owner.open_popular)
        self.tiles()
        self.added_row = self.preview("Недавно добавленные", owner.open_added)
        self.played_row = self.preview("Недавно сыгранные", owner.open_played)
        self.colors_changed()
        self.refresh()

    def colors_changed(self):
        owner = self.owner
        self.button.setBackground(owner.rounded(owner.color("accent"), _dp(22)))
        for tile in self.tile_views:
            tile.setBackground(owner.rounded(owner.color("surfaceContainer"), _dp(16)))
        self.paint_pills()

    def nav(self, key, icons, title, action):
        count = self.nav_row(self.content, icons, title, action)
        if key is not None:
            self.counts[key] = count

    def tiles(self):
        owner = self.owner
        LinearLayout = jclass("android.widget.LinearLayout")
        Params = jclass("android.widget.LinearLayout$LayoutParams")
        ImageView = jclass("android.widget.ImageView")
        row = LinearLayout(owner.context)
        row.setOrientation(0)
        row.setPadding(_dp(16), _dp(8), _dp(16), _dp(8))
        for index, (kind, title, icons) in enumerate((("artists", "Авторы", ("msg_contacts",)),
                                                      ("albums", "Альбомы", ("msg_media",)),
                                                      ("genres", "Жанры", ("msg_voice_headphones",)))):
            tile = LinearLayout(owner.context)
            tile.setOrientation(1)
            tile.setGravity(17)
            icon = ImageView(owner.context)
            owner.set_icon(icon, icons)
            self.tint_icon(icon, "icon")
            tile.addView(icon, owner.params(24, 24))
            name = self.label(13, "text", True)
            name.setText(title)
            name.setGravity(17)
            top = Params(-1, -2)
            top.topMargin = _dp(6)
            tile.addView(name, top)
            self.click(tile, owner.open_groups, kind, title)
            place = Params(0, _dp(80), 1.0)
            if index:
                place.setMarginStart(_dp(8))
            row.addView(tile, place)
            self.tile_views.append(tile)
        self.content.addView(row, Params(-1, -2))

    def preview(self, title, action):
        owner = self.owner
        Params = jclass("android.widget.LinearLayout$LayoutParams")
        ImageView = jclass("android.widget.ImageView")
        head = jclass("android.widget.LinearLayout")(owner.context)
        head.setOrientation(0)
        head.setGravity(16)
        head.setPadding(_dp(20), 0, _dp(12), 0)
        head.setBackground(owner.selector(0))
        name = self.label(17, "text", True)
        name.setText(title)
        head.addView(name, Params(0, -2, 1.0))
        more = self.label(14, "accent")
        more.setText("Показать всё")
        head.addView(more)
        arrow = ImageView(owner.context)
        owner.set_icon(arrow, ("msg_arrowright",))
        self.tint_icon(arrow, "accent")
        head.addView(arrow, owner.params(24, 24))
        self.click(head, action)
        top = Params(-1, _dp(44))
        top.topMargin = _dp(8)
        self.content.addView(head, top)

        scroller, row = self.sideways()
        self.content.addView(scroller, Params(-1, -2))
        hint = self.label(14, "textSecondary")
        hint.setSingleLine(False)
        hint.setPadding(_dp(20), 0, _dp(20), 0)
        self.content.addView(hint, Params(-1, -2))
        return {"scroller": scroller, "row": row, "hint": hint, "shown": None, "tracks": [], "title": title, "tiles": []}

    def fill(self, block, tracks, empty):
        """The row keeps its tiles and gives them new songs: a song heard every half minute would otherwise mean
        twenty new tiles, with their listeners, each time."""
        block["tracks"] = tracks
        shown = [t["path"] for t in tracks[:PREVIEW_MAX]]
        if shown != block["shown"]:
            block["shown"] = shown
            owner = self.owner
            tiles = block["tiles"]
            for index, track in enumerate(tracks[:PREVIEW_MAX]):
                if index == len(tiles):
                    tiles.append(self.tile(None, "", "",
                                           lambda i=index: owner.play(block["tracks"], i, block["title"]),
                                           lambda view, i=index: owner.song_menu(view, block["tracks"][i])))
                    place = jclass("android.widget.LinearLayout$LayoutParams")(-2, -2)
                    place.setMarginEnd(_dp(12))
                    block["row"].addView(tiles[index]["view"], place)
                tile = tiles[index]
                owner.bind_cover(tile["image"], track["path"], TILE_SIZE)
                tile["name"].setText(track["title"])
                tile["second"].setText(track["artist"])
                tile["view"].setVisibility(0)
            for tile in tiles[len(shown):]:
                tile["view"].setVisibility(8)
        block["scroller"].setVisibility(0 if tracks else 8)
        block["hint"].setVisibility(8 if tracks else 0)
        block["hint"].setText(empty)

    def refresh(self):
        data = self.owner.data
        has_songs = bool(data.tracks)
        if not has_songs and not data.has_permission():
            self.message.setText("Разреши доступ к музыке на телефоне, чтобы песни появились в медиатеке.")
            self.button.setVisibility(0)
        elif not has_songs:
            self.message.setText("Ищу музыку на телефоне." if data.scanning or not data.loaded
                                 else "На телефоне пока нет песен. Добавь музыку, и она появится здесь.")
            self.button.setVisibility(8)
        self.scroll.setVisibility(0 if has_songs else 8)
        self.notice.setVisibility(8 if has_songs else 0)
        if not has_songs:
            return
        self.counts["all"].setText(str(len(data.tracks)))
        favorites = data.favorite_tracks()
        self.counts["favorites"].setText(str(len(favorites)) if favorites else "")
        self.fill(self.added_row, data.recently_added(), "")
        self.fill(self.played_row, data.history_tracks(), "Здесь появятся песни, которые ты слушаешь. Песня попадёт сюда после 30 секунд.")


class LibraryView:
    """The media library tab of one open player: a stack of screens above the bottom panel.

    The Mornye tab is the same kind of stack: it overrides the first screen and what showing it starts.
    """

    OWNS_COVERS = True  # the covers' single "ready" callback belongs to the library

    def __init__(self, player, context):
        self.player = player
        self.plugin = player.plugin
        self.data = self.plugin.music
        self.context = context
        self.colors = None
        self.colors_at = 0.0
        self.colors_waiting = False
        self.colors_dirty = False
        self.stack = []
        self.slots = {}
        self.waiters = {}
        self.visible = False
        self.ready_paths = set()
        self.ready_posted = False
        self.color_cache = {}
        self.media = jclass("org.telegram.messenger.MediaController")
        self.playing_at = 0.0
        self.playing_cached = None
        self.bold = jclass("org.telegram.messenger.AndroidUtilities").bold()
        self.regular = jclass("android.graphics.Typeface").DEFAULT
        self.root = jclass("android.widget.FrameLayout")(context)
        self.root.setClickable(True)
        self.root.setVisibility(8)
        player.layout.addOwnView(self.root)
        if self.OWNS_COVERS:
            self.data.covers.on_ready = self.cover_ready

    # -- small helpers --------------------------------------------------------

    def color(self, role):
        # PlayerColors is a Java object: each field read goes through reflection, so a value is read once per change
        value = self.color_cache.get(role)
        if value is None:
            value = getattr(self.colors, role)
            self.color_cache[role] = value
        return value

    def selector(self, radius):
        color = jclass("androidx.core.graphics.ColorUtils").setAlphaComponent(self.colors.text, 24)
        return jclass("org.telegram.ui.ActionBar.Theme").createRadSelectorDrawable(color, radius, radius)

    @staticmethod
    def tint(view, color):
        view.setColorFilter(jclass("android.graphics.PorterDuffColorFilter")(color, jclass("android.graphics.PorterDuff$Mode").SRC_IN))

    def resource(self, name):
        return self.context.getResources().getIdentifier(name, "drawable", self.context.getPackageName())

    def set_icon(self, view, icons):
        for name in icons:
            resource = self.resource(name)
            if resource:
                view.setImageResource(resource)
                return

    @staticmethod
    def params(width, height):
        return jclass("android.widget.LinearLayout$LayoutParams")(_dp(width), _dp(height))

    @staticmethod
    def rounded(color, radius):
        drawable = jclass("android.graphics.drawable.GradientDrawable")()
        drawable.setColor(color)
        drawable.setCornerRadius(float(radius))
        return drawable

    def text_view(self, size, bold=False):
        view = jclass("android.widget.TextView")(self.context)
        view.setTextSize(1, float(size))
        view.setSingleLine(True)
        view.setEllipsize(jclass("android.text.TextUtils$TruncateAt").END)
        if bold:
            view.setTypeface(self.bold)
        return view

    def cover_view(self, radius, size):
        """An image over a plain tile with a note, which is what stays when a file has no cover."""
        image = jclass("org.telegram.ui.Components.BackupImageView")(self.context)
        image.setRoundRadius(_dp(radius))
        note = self.context.getResources().getDrawable(self.resource("msg_filled_data_music") or self.resource("msg_played"), None).mutate()
        note.setColorFilter(jclass("android.graphics.PorterDuffColorFilter")(self.colors.textSecondary, jclass("android.graphics.PorterDuff$Mode").SRC_IN))
        inset = jclass("android.graphics.drawable.InsetDrawable")(note, _dp(size * 0.28))
        Drawable = jclass("android.graphics.drawable.Drawable")
        image.setBackground(jclass("android.graphics.drawable.LayerDrawable")(jarray(Drawable)([self.rounded(self.colors.surfaceContainer, _dp(radius)), inset])))
        return image

    def bind_cover(self, image, path, size):
        image_id = image.hashCode()
        if path is None:
            self.slots[image_id] = None
            image.getImageReceiver().clearImage()
            return
        if self.slots.get(image_id) == path and image.getImageReceiver().hasImageSet():
            return
        self.slots[image_id] = path
        known, jpg = self.data.covers.cached(path)
        if jpg is not None:
            image.setImage(jpg, "%d_%d" % (size, size), None)
            return
        image.getImageReceiver().clearImage()
        if not known:
            self.waiters.setdefault(path, []).append((image, size))
            self.data.covers.warm([path], first=True)

    def cover_ready(self, path):
        """Called on the covers' thread; many at once are handed to the screen in one go."""
        if path not in self.waiters:
            return
        self.ready_paths.add(path)
        if not self.ready_posted:
            self.ready_posted = True
            run_on_ui_thread(self.deliver_covers, COVERS_DELIVERY_MS)

    def deliver_covers(self):
        self.ready_posted = False
        paths, self.ready_paths = self.ready_paths, set()
        try:
            for path in paths:
                for image, size in self.waiters.pop(path, ()):
                    if self.slots.get(image.hashCode()) != path:
                        continue
                    jpg = self.data.covers.cached(path)[1]
                    if jpg is not None:
                        image.setImage(jpg, "%d_%d" % (size, size), None)
            if paths and self.stack and isinstance(self.stack[-1], GroupsScreen):
                # a group whose first songs had no cover picks another one: its row is bound again
                self.stack[-1].changed_when_still()
        except Exception as e:
            self.plugin.report("covers", e)

    def group_cover(self, tracks):
        """The first cover among a group's songs: what is read yet wins, and the unread ones get read."""
        covers = self.data.covers
        unknown = []
        for track in tracks[:GROUP_COVER_TRIES]:
            known, jpg = covers.cached(track["path"])
            if jpg is not None:
                return track["path"]
            if not known:
                unknown.append(track["path"])
        return unknown[0] if unknown else None

    def playing_path(self):
        """Asked by every row a list binds: one answer per moment is enough."""
        now = time.monotonic()
        if now - self.playing_at > 0.2:
            self.playing_at = now
            self.playing_cached = local_path(self.media.getInstance().getPlayingMessageObject())
        return self.playing_cached

    # -- rows -----------------------------------------------------------------

    def _row(self, height):
        row = jclass("android.widget.LinearLayout")(self.context)
        row.setOrientation(0)
        row.setGravity(16)
        row.setPadding(_dp(16), 0, _dp(THUMB_AREA), 0)
        row.setLayoutParams(jclass("android.widget.AbsListView$LayoutParams")(-1, _dp(height)))
        return row

    def _texts(self, row, holder):
        column = jclass("android.widget.LinearLayout")(self.context)
        column.setOrientation(1)
        holder["title"] = self.text_view(16)
        column.addView(holder["title"])
        holder["subtitle"] = self.text_view(13)
        column.addView(holder["subtitle"])
        place = jclass("android.widget.LinearLayout$LayoutParams")(0, -2, 1.0)
        place.setMarginStart(_dp(12))
        row.addView(column, place)

    def song_row(self, holders):
        holder = {}
        row = self._row(64)
        holder["image"] = self.cover_view(8, 48)
        row.addView(holder["image"], self.params(48, 48))
        self._texts(row, holder)
        holder["time"] = self.text_view(13)
        place = jclass("android.widget.LinearLayout$LayoutParams")(-2, -2)
        place.setMarginStart(_dp(8))
        row.addView(holder["time"], place)
        holders[row.hashCode()] = holder
        return row

    def group_row(self, kind, holders):
        holder = {}
        row = self._row(64)
        Frame = jclass("android.widget.FrameLayout$LayoutParams")
        if kind == "artists":
            frame = jclass("android.widget.FrameLayout")(self.context)
            frame.setBackground(self.rounded(self.colors.surfaceContainer, _dp(24)))
            holder["letter"] = self.text_view(20, True)
            holder["letter"].setGravity(17)
            frame.addView(holder["letter"], Frame(-1, -1))
            holder["image"] = jclass("org.telegram.ui.Components.BackupImageView")(self.context)
            holder["image"].setRoundRadius(_dp(24))
            frame.addView(holder["image"], Frame(-1, -1))
            row.addView(frame, self.params(48, 48))
        elif kind == "albums":
            holder["image"] = self.cover_view(8, 48)
            row.addView(holder["image"], self.params(48, 48))
        self._texts(row, holder)
        holders[row.hashCode()] = holder
        return row

    # -- menus ------------------------------------------------------------------

    def make_menu(self, anchor, swipeback=True):
        return self.plugin.sheet_menu(self.player.sheet, anchor, swipeback)

    def song_menu(self, anchor, track):
        path = track["path"]
        menu = self.make_menu(anchor)
        later = self.player.start_menu()
        menu.add(self.resource("msg_info"), "Информация о песне", later(lambda: self.menu_action(menu, self.song_info, track)))
        menu.add(self.resource("menu_tag_edit") or self.resource("msg_edit"), "Изменить теги",
                 later(lambda: self.menu_action(menu, self.edit_tags, track["path"])))
        menu.add(self.resource("msg_played"), "Играть следующей", later(lambda: self.menu_action(menu, self.queue_next, track)))
        menu.add(self.resource("player_new_queue"), "В конец очереди", later(lambda: self.menu_action(menu, self.queue_last, track)))
        favorite = self.data.is_favorite(path)
        menu.add(self.resource("media_like_active" if favorite else "media_like"), "Убрать из любимых" if favorite else "В любимые",
                 later(lambda: self.menu_action(menu, self.toggle_favorite, path)))
        self.player.add_playlist_item(menu)
        self.player.show_menu(menu)

    def menu_action(self, menu, action, *args):
        try:
            menu.dismiss()
            action(*args)
        except Exception as e:
            self.plugin.report("menu", e)

    def edit_tags(self, path):
        from .tag_ui import TagScreen
        self.push(TagScreen(self, path))

    def song_info(self, track):
        from .song_info import SongInfo
        SongInfo(self.player, track["path"], track["path"], {"title": track["title"], "artist": track["artist"],
                                                             "album": track["album"], "seconds": track.get("duration", 0)}).show()

    def queue_next(self, track):
        self.data.play_next(track)
        self.plugin.bulletin(self.player.sheet, "saved_messages", "Песня заиграет следующей")

    def queue_last(self, track):
        self.data.play_last(track)
        self.plugin.bulletin(self.player.sheet, "saved_messages", "Песня добавлена в конец очереди")

    def toggle_favorite(self, path):
        added = self.data.toggle_favorite(path)
        self.plugin.bulletin(self.player.sheet, "saved_messages" if added else "ic_delete", "Добавлено в любимые" if added else "Убрано из любимых")
        self.data_changed()
        self.player.update_like()

    # -- navigation ----------------------------------------------------------

    def push(self, screen):
        if self.stack:
            self.root.removeView(self.stack[-1].view)
        self.stack.append(screen)
        self.root.addView(screen.view, jclass("android.widget.FrameLayout$LayoutParams")(-1, -1))
        view = screen.view
        view.setAlpha(0.0)
        view.setTranslationX(float(_dp(24)))
        interpolator = jclass("android.view.animation.DecelerateInterpolator")()
        view.animate().alpha(1.0).translationX(0.0).setDuration(180).setInterpolator(interpolator).start()

    def back(self):
        top = self.stack[-1] if self.stack else None
        if top is not None and getattr(top, "filter_query", ""):
            top.clear_filter()
            return
        if len(self.stack) > 1:
            gone = self.stack.pop()
            self.root.removeView(gone.view)
            gone.dispose()
            top = self.stack[-1]
            self.root.addView(top.view, jclass("android.widget.FrameLayout$LayoutParams")(-1, -1))
            top.view.setAlpha(1.0)
            top.view.setTranslationX(0.0)
            top.refresh()
        else:
            self.player.show_tab(PANEL_ACTIVE)

    def to_root(self):
        """Straight back to the first screen, as a second press on the tab asks; already there, the screen
        takes the press itself (the search opens its keyboard)."""
        if len(self.stack) <= 1:
            again = getattr(self.stack[0], "tab_again", None) if self.stack else None
            if again is not None:
                self.stack[0].guarded(again)
            return
        while len(self.stack) > 1:
            gone = self.stack.pop()
            self.root.removeView(gone.view)
            gone.dispose()
        top = self.stack[0]
        self.root.addView(top.view, jclass("android.widget.FrameLayout$LayoutParams")(-1, -1))
        view = top.view
        view.setAlpha(0.0)
        view.setTranslationX(float(-_dp(24)))
        interpolator = jclass("android.view.animation.DecelerateInterpolator")()
        view.animate().alpha(1.0).translationX(0.0).setDuration(180).setInterpolator(interpolator).start()
        top.guarded(top.refresh)

    def close_player(self):
        self.player.collapseButton.performClick()

    def show(self):
        self.visible = True
        self.root.setVisibility(0)
        self.root.setAlpha(0.0)
        self.root.animate().alpha(1.0).setDuration(150).start()
        if not self.stack:
            if self.colors is None:
                self.colors = self.plugin.sheet_fields.get(self.player.sheet, "colors")
                self.color_cache = {}
            self.root.setBackgroundColor(tab_scrim(self.colors))
            self.root.setPadding(0, self.plugin.layout_fields.int(self.player.layout, "contentTop"), 0, 0)
            self.push(self.first_screen())
        elif self.colors_dirty:
            self.apply_colors()
        self.shown()

    def first_screen(self):
        return RootScreen(self)

    def shown(self):
        self.data.scan()
        self.data_changed()

    def hide(self):
        self.visible = False
        self.root.animate().cancel()
        self.root.setVisibility(8)
        for screen in self.stack:
            close = getattr(screen, "close_keyboard", None)
            if close is not None:
                close()

    def dispose(self):
        """The player closed: every screen lets go of its listeners, so all of it can be collected."""
        self.visible = False
        for screen in self.stack:
            screen.dispose()
        self.stack = []
        self.slots = {}
        self.waiters = {}
        self.ready_paths = set()
        if self.data.covers.on_ready == self.cover_ready:
            self.data.covers.on_ready = None

    def data_changed(self):
        if not self.visible:
            return
        for screen in self.stack:
            screen.guarded(screen.refresh)

    def set_colors(self, colors):
        self.colors = colors
        self.color_cache = {}
        if not self.stack:
            return
        if not self.visible:
            self.colors_dirty = True
            return
        # applyColors fires on every frame of a color animation: a few repaints a second are plenty here
        if time.monotonic() - self.colors_at >= COLORS_SECONDS:
            self.apply_colors()
        elif not self.colors_waiting:
            self.colors_waiting = True
            run_on_ui_thread(self.apply_colors, int(COLORS_SECONDS * 1000))

    def apply_colors(self):
        self.colors_waiting = False
        self.colors_dirty = False
        self.colors_at = time.monotonic()
        try:
            self.root.setBackgroundColor(tab_scrim(self.colors))
            for screen in self.stack:
                screen.retint()
        except Exception as e:
            self.plugin.report("library colors", e)

    # -- opening things --------------------------------------------------------

    def open_search(self):
        self.push(SearchScreen(self))

    def open_all(self):
        self.push(SongsScreen(self, "Все песни", lambda: self.data.tracks, "all", "title"))

    def open_favorites(self):
        self.push(SongsScreen(self, "Любимые", self.data.favorite_tracks, "favorites", "added",
                              "Здесь будут песни, которые ты отметишь сердечком. Отметить можно в плеере или долгим нажатием на песню.", fav_dates=True))

    def open_added(self):
        self.push(SongsScreen(self, "Недавно добавленные", lambda: self.data.tracks, "added", "added"))

    def open_played(self):
        self.push(SongsScreen(self, "Недавно сыгранные", self.data.history_tracks, None, "title",
                              "Здесь появятся песни, которые ты слушаешь. Песня попадёт сюда после 30 секунд."))

    def open_popular(self):
        self.push(BlankScreen(self, "Популярные", "Здесь появятся песни, которые ты слушаешь чаще всего."))

    def open_groups(self, kind, title):
        self.push(GroupsScreen(self, kind, title))

    def open_group(self, kind, item):
        if kind == "artists":
            albums = self.data.artist_albums(item["tracks"])
            self.push(SongsScreen(self, item["name"], lambda: item["tracks"], "artist", "title",
                                  list_header=lambda screen: self.albums_header(screen, albums)))
        elif kind == "albums":
            self.push(SongsScreen(self, item["name"], lambda: item["tracks"], "album", "track"))
        else:
            self.push(SongsScreen(self, item["name"], lambda: item["tracks"], "genre", "title"))

    def albums_header(self, screen, albums):
        """The author's albums above the songs, when there is more than one to choose from."""
        if len(albums) < 2:
            return None
        Params = jclass("android.widget.LinearLayout$LayoutParams")
        block = jclass("android.widget.LinearLayout")(self.context)
        block.setOrientation(1)
        block.setLayoutParams(jclass("android.widget.AbsListView$LayoutParams")(-1, -2))
        name = screen.label(17, "text", True)
        name.setText("Альбомы")
        name.setPadding(_dp(20), _dp(8), _dp(20), _dp(12))
        block.addView(name)
        scroller, row = screen.sideways()
        for album in albums:
            tile = screen.tile(self.group_cover(album["tracks"]), album["name"], songs_label(len(album["tracks"])),
                               lambda a=album: self.open_group("albums", a))
            place = Params(-2, -2)
            place.setMarginEnd(_dp(12))
            row.addView(tile["view"], place)
        block.addView(scroller, Params(-1, -2))
        songs = screen.label(17, "text", True)
        songs.setText("Песни")
        songs.setPadding(_dp(20), _dp(16), _dp(20), _dp(8))
        block.addView(songs)
        return block

    def play(self, tracks, index, title=""):
        self.player.show_tab(PANEL_ACTIVE)
        self.data.play(list(tracks), index, title)

    # -- permission --------------------------------------------------------------

    def ask_permission(self):
        activity = jclass("org.telegram.ui.LaunchActivity").instance
        permission = self.data.permission()
        if self.plugin.get_setting("permission_asked", False) and not activity.shouldShowRequestPermissionRationale(permission):
            # Android stopped showing the question after a refusal: only the app's settings page can change it now
            uri = jclass("android.net.Uri").fromParts("package", self.context.getPackageName(), None)
            activity.startActivity(jclass("android.content.Intent")("android.settings.APPLICATION_DETAILS_SETTINGS", uri))
        else:
            self.plugin.set_setting("permission_asked", True)
            activity.requestPermissions(jarray(jclass("java.lang.String"))([permission]), PERMISSION_REQUEST)
        self.wait_permission(PERMISSION_POLLS)

    def wait_permission(self, polls):
        if self.data.has_permission():
            self.data.scan()
            self.data_changed()
        elif polls > 0:
            run_on_ui_thread(lambda: self.wait_permission(polls - 1), 500)
