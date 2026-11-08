# Sculpt Player for exteraGram. Copyright 2026 BroNik (@BroZYTnikkkk).

from android_utils import OnClickListener, run_on_ui_thread
from java import jarray, jclass
from java.lang import Boolean as JBoolean, Integer as JInteger

from .common import ALBUM_H, ALBUM_OFFSET, ARTIST_OFFSET, BUTTON, HEADER_H, MARGIN, MEDIA_CONTROLLER, MODE_PLAYER, MODE_QUEUE, PANEL_ACTIVE, PANEL_H, PANEL_LIBRARY, PANEL_MORNYE, PANEL_PLAYLISTS, PANEL_QUEUE, PANEL_SEARCH, PANEL_SETTINGS, PANEL_STACKS, PANEL_TABS, LYRICS_SHIFT, SEEK_H, SEEK_LINE, STEP, TEXT_BLOCK, TIME_WIDTH, TITLE_H, TRANSPORT_H, _dp
from .visualizer import Visualizer
from .peeks import Peeks
from .player_taps import Taps
from .lyrics_fx import LyricsEffects
from .link_stream import saved_server
from .music import local_path
from .library_ui import LibraryView, Run, release_on_dismiss
from .queue_ui import QueueScreen
from .mornye_ui import MornyeView, SearchView
from .settings_ui import SettingsView


MENU_SWAP_MS = 180  # one menu closes before the other opens


class Player:
    """One open MusicPlayerSheet: its views and the ones this plugin adds to it."""

    NAMES = ("titleView", "artistView", "seekBar", "timeView", "durationView", "controlsView", "profileButton",
             "lyricsView", "lyricsButton", "queueButton", "moreButton", "speedButton", "repeatButton", "shuffleButton",
             "collapseButton", "headerTitle", "headerSubtitle", "coverView")

    def __init__(self, plugin, sheet):
        self.plugin = plugin
        self.sheet = sheet
        self.layout = plugin.sheet_fields.get(sheet, "playerLayout")
        self.layout_id = self.layout.hashCode()
        for name in self.NAMES:
            setattr(self, name, plugin.sheet_fields.get(sheet, name))
        self.album = None
        self.volume = None
        self.equalizer = None
        self.listeners = []
        self.visualizer = None
        self.peeks = None
        self.taps = None
        self.effects = None
        self.album_checked = 0.0
        self.tabs = []
        self.panel_top = 0
        self.divider = None
        self.indicator = None
        self.panel_hidden = False
        self.context = None
        self.active_tab = PANEL_ACTIVE
        self.library = None
        self.search_tab = None
        self.search_shape = None
        self.mornye = None
        self.settings = None
        self.like = None
        self.stock_menu_next = False
        self.add = None
        self.add_ring = None
        self.queue_screen = None
        self.menu_runs = []

    # the tabs made of a stack of screens: panel index, attribute, class
    STACK_KINDS = ((PANEL_LIBRARY, "library", LibraryView), (PANEL_SEARCH, "search_tab", SearchView),
                   (PANEL_MORNYE, "mornye", MornyeView), (PANEL_SETTINGS, "settings", SettingsView))

    def stacks(self):
        """The tabs made of a stack of screens, with their panel indexes: library, search, Mornye, settings."""
        return tuple((index, getattr(self, name)) for index, name, _ in self.STACK_KINDS)

    def ensure_stack(self, index, colors):
        for panel, name, kind in self.STACK_KINDS:
            if panel == index:
                stack = getattr(self, name)
                if stack is None:
                    stack = kind(self, self.context)
                    stack.set_colors(colors)
                    setattr(self, name, stack)
                    self.layout.requestLayout()
                return stack
        return None

    def visible_stack(self):
        for _, stack in self.stacks():
            if stack is not None and stack.visible:
                return stack
        return None

    def library_visible(self):
        """Whether the library or the Mornye tab is over the player."""
        return self.visible_stack() is not None

    def build(self, context):
        self.context = context
        TextView = jclass("android.widget.TextView")
        Gravity = jclass("android.view.Gravity")
        self.titleView.setIsCenter()
        self.artistView.setIsCenter()

        self.album = TextView(context)
        self.album.setTextSize(1, 14.0)
        self.album.setSingleLine(True)
        self.album.setEllipsize(jclass("android.text.TextUtils$TruncateAt").END)
        self.album.setGravity(Gravity.CENTER)
        self.layout.addOwnView(self.album)

        self.volume = self._button(context, ("filled_sound_on", "msg_call_speaker"), "Громкость", self.plugin.show_volume)
        self.equalizer = self._button(context, ("msg_photo_settings", "msg_settings"), "Эквалайзер", self.plugin.show_equalizer)

        self.remote_button = self._button(context, ("msg2_devices", "menu_devices"), "Пульт компьютера", self.open_link_remote)
        self.update_remote_button()
        self.like = self._button(context, ("media_like",), "В любимые", self.like_pressed)
        self.add = self._button(context, ("msg_add",), "Добавить", self.add_pressed)
        self.add_ring = jclass("android.graphics.drawable.GradientDrawable")()
        self.add_ring.setShape(1)  # oval
        self.add.setBackground(jclass("android.graphics.drawable.InsetDrawable")(self.add_ring, _dp((BUTTON - 28.0) / 2.0)))

        # The seek bar is 68 dp tall and reaches over the icon row: this one was added before it.
        self.moreButton.bringToFront()

        self.apply_wave()
        self.build_panel(context)
        # the player may reopen in the queue it was left in
        if self.mode() == MODE_QUEUE:
            # the player's own queue mode is the Queue tab's job now
            self.set_mode(MODE_PLAYER)
        self.visualizer = Visualizer(self.plugin, self)
        self.peeks = Peeks(self.plugin, self)
        self.taps = Taps(self.plugin, self)
        self.taps.attach()
        self.effects = LyricsEffects(self.plugin, self)
        self.effects.align()
        # the covers a first swipe shows are read now too: after Telegram restarts, no song starts to do it
        run_on_ui_thread(lambda: self.plugin.warm_neighbors(), 600)
        self.update_like()
        self.apply_colors(self.plugin.sheet_fields.get(self.sheet, "colors"))
        self.update_album()

    def build_panel(self, context):
        View = jclass("android.view.View")
        self.divider = View(context)
        self.layout.addOwnView(self.divider)
        for index, (title, icons) in enumerate(PANEL_TABS):
            tab = self._button(context, icons, title, lambda i=index: self.tab_pressed(i))
            tab.setTooltipText(title)
            self.tabs.append(tab)
        # the search tab stands out: its icon sits on a pill of the accent color
        Drawable = jclass("android.graphics.drawable.Drawable")
        self.search_shape = jclass("android.graphics.drawable.GradientDrawable")()
        self.search_shape.setCornerRadius(float(_dp(18)))
        pill = jclass("android.graphics.drawable.LayerDrawable")(jarray(Drawable)([self.search_shape]))
        pill.setLayerSize(0, _dp(52), _dp(36))
        pill.setLayerGravity(0, 17)  # Gravity.CENTER
        self.tabs[PANEL_SEARCH].setBackground(pill)
        self.indicator = View(context)
        self.layout.addOwnView(self.indicator)
        self.moreButton.bringToFront()

    def tab_pressed(self, index):
        if index == PANEL_PLAYLISTS:
            return  # a blank for now
        if index == self.active_tab:
            self.tab_again(index)
        else:
            self.show_tab(index)

    def tab_again(self, index):
        """A press on the tab that is open: back to its first screen, the way apps' bottom bars do it."""
        for panel, stack in self.stacks():
            if panel == index and stack is not None:
                stack.to_root()
                return
        if index == PANEL_ACTIVE and self.mode() != MODE_PLAYER:
            self.set_mode(MODE_PLAYER)
        elif index == PANEL_QUEUE and self.queue_visible() and self.queue_screen.query:
            self.queue_screen.search.setText("")

    def show_tab(self, index):
        if index == self.active_tab:
            return
        self.active_tab = index
        colors = self.plugin.sheet_fields.get(self.sheet, "colors")
        for panel, stack in self.stacks():
            if index != panel and stack is not None and stack.visible:
                stack.hide()
                self.layout.postInvalidateOnAnimation()
        if index != PANEL_QUEUE and self.queue_visible():
            self.queue_screen.hide()
            self.layout.postInvalidateOnAnimation()
        stack = self.ensure_stack(index, colors)
        if stack is not None:
            stack.show()
        elif index == PANEL_QUEUE:
            if self.queue_screen is None:
                self.queue_screen = QueueScreen(self, self.context)
                self.layout.requestLayout()
            self.queue_screen.show()
        if self.mode() == MODE_QUEUE:
            self.set_mode(MODE_PLAYER)
        self.cover_player(index in PANEL_STACKS or index == PANEL_QUEUE)
        self.paint_tabs(colors)
        self.place_indicator()

    def cover_player(self, hidden):
        """A tab over the player: the player's own views step aside, its glow (drawn under all of them) stays.

        Transition alpha multiplies the alpha the player animates on its own, so neither undoes the other. The
        tab's root takes the touches, so nothing hidden can be pressed.
        """
        keep = {view.hashCode() for view in self.tabs + [self.divider, self.indicator]}
        for screen in [stack for _, stack in self.stacks()] + [self.queue_screen]:
            if screen is not None:
                keep.add(screen.root.hashCode())
        value = 0.0 if hidden else 1.0
        for i in range(self.layout.getChildCount()):
            child = self.layout.getChildAt(i)
            if child.hashCode() not in keep:
                child.setTransitionAlpha(value)
        # the moving background stops under a tab and starts again over the player (RhythmHook)
        try:
            self.plugin.sheet_method("updateRhythm").invoke(self.sheet)
        except Exception as e:
            self.plugin.report("updateRhythm", e)

    def open_group(self, kind, name):
        """From the song info: that author, album or genre, opened in the library."""
        from .music import find_group
        item = find_group(self.plugin.music, kind, name)
        if item is None:
            self.plugin.bulletin(self.sheet, "info", "В медиатеке нет «%s»." % name)
            return
        self.show_tab(PANEL_LIBRARY)
        self.library.open_group(kind, item)

    def edit_tags(self, path):
        """The tag editor, in the library tab: it is the library's songs whose tags it writes."""
        self.show_tab(PANEL_LIBRARY)
        self.library.edit_tags(path)

    def queue_visible(self):
        return self.queue_screen is not None and self.queue_screen.visible

    def mode(self):
        return self.plugin.sheet_fields.int(self.sheet, "mode")

    def wants_back(self):
        """Whether back has a step to take inside the player before it closes."""
        return self.library_visible() or self.queue_visible() or self.mode() != MODE_PLAYER

    def go_back(self):
        """One step back: up the library, out of the queue's search, out of the queue or the lyrics."""
        if self.library_visible():
            self.visible_stack().back()
        elif self.queue_visible():
            if self.queue_screen.query:
                self.queue_screen.search.setText("")
            else:
                self.show_tab(PANEL_ACTIVE)
        else:
            self.set_mode(MODE_PLAYER)

    def set_mode(self, mode):
        """The player's own switch, without saving it as the mode the next opening starts in."""
        method = self.plugin.sheet_method("setMode", JInteger.TYPE, JBoolean.TYPE)
        method.invoke(self.sheet, JInteger(mode), JBoolean(True))

    def mode_changed(self, mode):
        """After MusicPlayerSheet.setMode: the player's own queue mode, if anything opens it, is the Queue tab."""
        if self.indicator is None or mode != MODE_QUEUE:
            return
        self.set_mode(MODE_PLAYER)
        self.show_tab(PANEL_QUEUE)

    def paint_tabs(self, colors):
        PorterDuffColorFilter = jclass("android.graphics.PorterDuffColorFilter")
        mode = jclass("android.graphics.PorterDuff$Mode").SRC_IN
        for index, tab in enumerate(self.tabs):
            if index == PANEL_SEARCH:
                continue
            tab.setColorFilter(PorterDuffColorFilter(colors.accent if index == self.active_tab else colors.icon, mode))
        if self.search_shape is not None:
            ColorUtils = jclass("androidx.core.graphics.ColorUtils")
            accent = colors.accent
            self.search_shape.setColor(accent)
            on_accent = -16777216 if ColorUtils.calculateLuminance(accent) > 0.5 else -1  # black or white
            self.tabs[PANEL_SEARCH].setColorFilter(PorterDuffColorFilter(on_accent, mode))

    def place_indicator(self):
        f = self.plugin.layout_fields
        slot = f.int(self.layout, "paneWidth") // len(self.tabs)
        left = f.int(self.layout, "paneLeft") + self.active_tab * slot
        self.indicator.layout(left, self.panel_top, left + self.indicator.getMeasuredWidth(), self.panel_top + self.indicator.getMeasuredHeight())

    def playing(self):
        return jclass(MEDIA_CONTROLLER).getInstance().getPlayingMessageObject()

    def like_pressed(self):
        path = local_path(self.playing())
        if path is None:
            self.plugin.bulletin(self.sheet, "info", "В любимые можно добавить только песню с телефона.")
            return
        added = self.plugin.music.toggle_favorite(path)
        self.plugin.bulletin(self.sheet, "saved_messages" if added else "ic_delete", "Добавлено в любимые" if added else "Убрано из любимых")
        self.update_like()
        if self.library is not None:
            self.library.data_changed()

    def update_like(self):
        if self.like is None:
            return
        res = self.context.getResources()
        package = self.context.getPackageName()
        path = local_path(self.playing())
        favorite = path is not None and self.plugin.music.is_favorite(path)
        self.like.setImageResource(res.getIdentifier("media_like_active" if favorite else "media_like", "drawable", package))
        self.like.setContentDescription("Убрать из любимых" if favorite else "В любимые")
        colors = self.plugin.sheet_fields.get(self.sheet, "colors")
        if colors is not None:
            self.tint_like(colors, path, favorite)

    def tint_like(self, colors, path, favorite):
        # A song from a chat cannot be marked: the heart stays visible, dimmed, and says why when pressed.
        color = colors.accent if favorite else colors.icon
        if path is None:
            color = jclass("androidx.core.graphics.ColorUtils").setAlphaComponent(colors.icon, 90)
        self.like.setColorFilter(jclass("android.graphics.PorterDuffColorFilter")(color, jclass("android.graphics.PorterDuff$Mode").SRC_IN))

    def add_pressed(self):
        message = self.playing()
        if message is None:
            return
        res = self.context.getResources()
        package = self.context.getPackageName()

        def icon(name):
            return res.getIdentifier(name, "drawable", package)

        menu = self.plugin.sheet_menu(self.sheet, self.add, True)
        self.start_menu()
        if local_path(message) is not None:
            # Telegram can only keep what it has on its servers, and this file is only on the phone.
            menu.add(icon("left_status_profile"), "Добавить в профиль", self.run_later(lambda: self.plugin.bulletin(self.sheet, "info", "В профиль можно добавить только песню из Telegram.")))
            last = menu.getLast()
            if last is not None:
                last.setAlpha(0.5)
        else:
            inside = self.plugin.sheet_actions(self.sheet).isInProfile(message)

            def toggle():
                menu.dismiss()
                self.plugin.toggle_profile(self.sheet)

            menu.add(icon("left_status_profile"), "Убрать из профиля" if inside else "Добавить в профиль", self.run_later(toggle))
        self.add_playlist_item(menu)
        self.show_menu(menu)

    def start_menu(self):
        """A fresh list for the Runnables of the menu about to open; returns the way to make one."""
        self.menu_runs = []
        return self.run_later

    def show_menu(self, menu):
        release_on_dismiss(menu, self.menu_runs)
        self.menu_runs = []
        menu.show()

    def dispose(self):
        """The sheet is gone: its buttons and the library let go of their listeners.

        Each listener's closure holds this player, and a cycle through Java and Python is never collected:
        without this every opening of the player would stay in memory with all of its views.
        """
        for button in self.listeners:
            try:
                button.setOnClickListener(None)
            except Exception:
                pass
        self.listeners = []
        if self.queue_screen is not None:
            self.queue_screen.dispose()
            self.queue_screen = None
        for _, name, _ in self.STACK_KINDS:
            stack = getattr(self, name)
            if stack is not None:
                stack.dispose()
                setattr(self, name, None)
        self.visualizer = None
        if self.peeks is not None:
            self.peeks.dispose()
            self.peeks = None
        if self.taps is not None:
            self.taps.detach()
            self.taps = None
        self.effects = None
        self.menu_runs = []

    def run_later(self, action):
        run = Run(lambda: self.guarded_menu(action))
        self.menu_runs.append(run)
        return run

    def guarded_menu(self, action):
        try:
            action()
        except Exception as e:
            self.plugin.report("menu", e)

    def add_playlist_item(self, menu):
        """Playlists are a blank for now: the list and its "create" button are in place, with nothing behind them."""
        res = self.context.getResources()
        package = self.context.getPackageName()

        def icon(name):
            return res.getIdentifier(name, "drawable", package)

        submenu = menu.makeSwipeback()
        submenu.add(icon("ic_ab_back"), "Назад", self.run_later(menu.closeSwipeback))

        def create():
            menu.dismiss()
            self.plugin.bulletin(self.sheet, "info", "Плейлисты появятся позже.")

        submenu.addGap()
        submenu.add(icon("msg_add"), "Создать плейлист", self.run_later(create))
        menu.add(icon("msg_addfolder"), "В плейлист", self.run_later(lambda: menu.openSwipeback(submenu)))
        last = menu.getLast()
        if last is not None:
            last.setRightIcon(icon("msg_arrowright"))

    def hide_panel(self, hidden):
        """Search in the queue opens the keyboard: the panel gives way, like the rest of the controls."""
        if hidden == self.panel_hidden or self.divider is None:
            return
        self.panel_hidden = hidden
        for view in self.tabs + [self.divider, self.indicator]:
            view.setAlpha(0.0 if hidden else 1.0)
            view.setEnabled(not hidden)

    def apply_wave(self):
        amplitude = 0.0 if self.plugin.get_setting("flat_seek", True) else 3.0
        self.seekBar.setWaveStyle(4.0, amplitude, 40.0, 24.0, 4.0, 18.0)

    def _button(self, context, icons, description, action):
        button = jclass("android.widget.ImageView")(context)
        res = context.getResources()
        for icon in icons:
            resource = res.getIdentifier(icon, "drawable", context.getPackageName())
            if resource:
                button.setImageResource(resource)
                break
        button.setScaleType(jclass("android.widget.ImageView$ScaleType").CENTER)
        button.setContentDescription(description)
        listener = OnClickListener(lambda view: action())
        self.listeners.append(button)
        button.setOnClickListener(listener)
        self.layout.addOwnView(button)
        return button

    def apply_colors(self, colors):
        if self.album is None or colors is None:
            return
        self.album.setTextColor(colors.textSecondary)
        PorterDuffColorFilter = jclass("android.graphics.PorterDuffColorFilter")
        mode = jclass("android.graphics.PorterDuff$Mode").SRC_IN
        self.volume.setColorFilter(PorterDuffColorFilter(colors.icon, mode))
        self.equalizer.setColorFilter(PorterDuffColorFilter(colors.icon, mode))
        self.paint_tabs(colors)
        if self.queue_visible():
            self.queue_screen.set_colors(colors)
        if self.like is not None:
            path = local_path(self.playing())
            self.tint_like(colors, path, path is not None and self.plugin.music.is_favorite(path))
            self.add.setColorFilter(PorterDuffColorFilter(colors.icon, mode))
            self.add_ring.setStroke(_dp(1.5), colors.icon)
        for _, stack in self.stacks():
            if stack is not None:
                stack.set_colors(colors)
        if self.divider is not None:
            ColorUtils = jclass("androidx.core.graphics.ColorUtils")
            self.divider.setBackgroundColor(ColorUtils.setAlphaComponent(colors.text, 30))
            self.indicator.setBackgroundColor(colors.accent)
        if self.visualizer is not None:
            self.visualizer.set_colors(colors)

    def update_album(self):
        if self.album is None:
            return
        album = None
        try:
            controller = jclass("org.telegram.messenger.MediaController").getInstance()
            # a song from the phone: the library's album, read with its odd letters intact (Telegram's own tag
            # reader turns letters outside the basic plane into "?")
            track = self.plugin.music.by_path.get(local_path(controller.getPlayingMessageObject()))
            if track is not None:
                album = track.get("album") or None
            else:
                info = controller.getAudioInfo()
                album = info.getAlbum() if info is not None else None
        except Exception:
            pass
        text = str(album) if album else ""
        if "??" in text or text.count("?") >= 3:
            text = ""  # question marks for letters say nothing: no album line rather than that
        if str(self.album.getText()) != text:
            self.album.setText(text)
        self.recenter()

    def lyrics_layout(self, progress):
        """With the lyrics open the icon row goes, the title drops into its place, and the lyrics button stays, beside
        the title where the ⋯ was: it is the way back. Runs after applyTransitions, which has just set these views."""
        shift = _dp(LYRICS_SHIFT)
        for view in (self.titleView, self.artistView):
            view.setTranslationY(view.getTranslationY() + shift * progress)
        fading = max(0.0, 1.0 - progress * 1.6)
        for view in (self.like, self.add, self.speedButton, self.repeatButton, self.shuffleButton):
            view.setAlpha(view.getAlpha() * fading)
            view.setEnabled(progress < 0.5)
        lyrics = self.lyricsButton
        # counted from the places worked out here, not read from the views: on the first opening the player's own
        # layout still holds the ⋯ in the header, and the button would follow it there
        x, top = getattr(self, "lyrics_slot", (lyrics.getLeft(), lyrics.getTop()))
        more_x, more_top = self.more_spot()
        lyrics.setTranslationX((more_x - x) * progress)
        lyrics.setTranslationY((more_top + shift - top) * progress)

    def more_spot(self):
        """Where the ⋯ belongs: beside the title and the author (Musicolet's place for it)."""
        f = self.plugin.layout_fields
        lay = self.layout
        size = _dp(BUTTON)
        right = f.int(lay, "paneLeft") + f.int(lay, "paneWidth") - _dp(MARGIN)
        return right - size, f.int(lay, "titleTop") + (_dp(ARTIST_OFFSET) + _dp(TITLE_H) - size) // 2

    def recenter(self):
        """Beside the small cover in queue and lyrics: the text keeps close to the middle of the screen.

        Its center sits halfway between the screen's right edge and the point halfway across the cover's left
        margin. A long title moves right just enough to clear the cover.
        """
        sf, f = self.plugin.sheet_fields, self.plugin.layout_fields
        progress = max(sf.float(self.sheet, "modeProgress"), sf.float(self.sheet, "canvasTitleProgress"))
        # the ⋯ beside the title gives way to the small cover's text
        self.moreButton.setAlpha(max(0.0, 1.0 - 2.0 * progress))
        self.moreButton.setEnabled(progress < 0.5)
        if progress <= 0.0:
            return
        lay = self.layout
        pane_left = f.int(lay, "paneLeft")
        left = pane_left + _dp(MARGIN) + _dp(BUTTON)
        shift = (f.int(lay, "compactCoverSize") + _dp(16)) * progress
        width = f.int(lay, "textWidth") - round(shift)
        wanted = (pane_left + f.int(lay, "paneWidth") + pane_left + _dp(10)) / 2.0
        center = left + shift + width / 2.0
        for switcher in (self.titleView, self.artistView):
            label = switcher.getTextView()
            text = label.getText()
            text_width = min(float(width), label.getPaint().measureText(str(text))) if text is not None else 0.0
            target = max(wanted, left + shift + text_width / 2.0)
            switcher.setTranslationX(float(shift + min(0.0, target - center)))

    def geometry(self, height):
        """All the numbers PlayerLayout.onLayout and applyTransitions read, built from the bottom up."""
        f = self.plugin.layout_fields
        lay = self.layout
        content_top = f.int(lay, "contentTop")
        content_left = f.int(lay, "contentLeft")
        content_width = f.int(lay, "contentWidth")

        self.panel_top = height - _dp(PANEL_H)
        transport_top = self.panel_top - _dp(4) - _dp(TRANSPORT_H)
        line_center = transport_top - _dp(20)
        toolbar_top = line_center - _dp(24) - _dp(BUTTON)
        title_top = toolbar_top - _dp(8) - _dp(TEXT_BLOCK)

        header = content_top + _dp(HEADER_H)
        space = title_top - _dp(12) - (header + _dp(8))
        size = float(max(0, min(content_width - 2 * _dp(MARGIN), space)))
        f.set_int(lay, "headerBottom", header)
        f.set_int(lay, "stageTop", header + _dp(8))
        f.set_float(lay, "coverSize", size)
        f.set_float(lay, "coverLeft", content_left + (content_width - size) / 2.0)
        f.set_float(lay, "coverTop", header + _dp(8) + (space - size) / 2.0)
        f.set_int(lay, "titleTop", title_top)
        f.set_int(lay, "toolbarTop", toolbar_top)
        f.set_int(lay, "lineCenter", line_center)
        f.set_int(lay, "timesTop", line_center - _dp(9))
        f.set_int(lay, "transportTop", transport_top)
        if not f.bool(lay, "keyboardLayout"):
            f.set_int(lay, "stageBottom", title_top - _dp(16))

    def measure(self):
        f = self.plugin.layout_fields
        lay = self.layout
        pane = f.int(lay, "paneWidth")
        full = pane - 2 * _dp(MARGIN)
        # the title block leaves room for the ⋯ on its right, and as much on its left, so it stays centered
        text = full - 2 * _dp(BUTTON)
        f.set_int(lay, "textWidth", text)
        spec = jclass("android.view.View$MeasureSpec")
        exact = spec.EXACTLY

        def measure(view, width, height):
            view.measure(spec.makeMeasureSpec(max(0, int(width)), exact), spec.makeMeasureSpec(max(0, int(height)), exact))

        measure(self.titleView, text, _dp(TITLE_H))
        measure(self.artistView, text + 2 * _dp(6), _dp(TITLE_H))
        measure(self.album, text, _dp(ALBUM_H))
        measure(self.seekBar, full - 2 * _dp(TIME_WIDTH + 4), _dp(SEEK_H))
        measure(self.timeView, _dp(TIME_WIDTH), _dp(18))
        measure(self.durationView, _dp(TIME_WIDTH), _dp(18))
        for button in (self.like, self.add, self.lyricsButton, self.queueButton, self.moreButton, self.speedButton,
                       self.repeatButton, self.shuffleButton, self.volume, self.equalizer, self.remote_button):
            measure(button, _dp(BUTTON), _dp(BUTTON))
        slot = pane // len(self.tabs)
        for tab in self.tabs:
            measure(tab, slot, _dp(PANEL_H))
        measure(self.divider, pane, max(1, _dp(1) // 2))
        measure(self.lyricsView, self.lyricsView.getMeasuredWidth(), self.lyricsView.getMeasuredHeight() + _dp(LYRICS_SHIFT))
        measure(self.indicator, slot, _dp(2))
        for _, stack in self.stacks():
            if stack is not None:
                measure(stack.root, pane, self.panel_top)
        if self.queue_screen is not None:
            measure(self.queue_screen.root, pane, self.panel_top)

    def open_song_menu(self):
        """True when the song's menu opened in place of the player's own."""
        from .song_menu import PlayerSongMenu
        if self.stock_menu_next:
            self.stock_menu_next = False
            return False
        message = jclass(MEDIA_CONTROLLER).getInstance().getPlayingMessageObject()
        if message is None:
            return False
        PlayerSongMenu(self, message).show()
        return True

    def open_stock_menu(self):
        """The player's own ⋯ menu, once the song's menu has closed; ShowMenuHook lets this one through."""
        def show():
            self.stock_menu_next = True
            self.plugin.sheet_method("showMenu").invoke(self.sheet)

        run_on_ui_thread(show, MENU_SWAP_MS)

    def update_remote_button(self):
        """Only with a computer to steer."""
        self.remote_button.setVisibility(0 if saved_server(self.plugin) is not None else 8)

    def open_link_remote(self):
        saved = saved_server(self.plugin)
        if saved is None:
            return
        self.show_tab(PANEL_MORNYE)
        self.mornye.open_link_remote(saved)

    def step(self):
        pane = self.plugin.layout_fields.int(self.layout, "paneWidth")
        # the row is laid out for seven buttons (heart, plus, lyrics, a free place, speed, repeat, shuffle), so
        # the spacing stays the one it had with the queue button, which is a tab now
        return min(_dp(STEP), (pane - 2 * _dp(MARGIN) - _dp(BUTTON)) // 6)

    def place_mode_buttons(self):
        f = self.plugin.layout_fields
        left = f.int(self.layout, "paneLeft") + _dp(MARGIN)
        top = f.int(self.layout, "toolbarTop")
        size = _dp(BUTTON)
        x = left + 2 * self.step()
        self.lyricsButton.layout(x, top, x + size, top + size)
        self.lyrics_slot = (x, top)
        # the queue is the first tab of the bottom panel now
        self.queueButton.layout(0, 0, 0, 0)

    def place(self):
        f = self.plugin.layout_fields
        lay = self.layout
        left = f.int(lay, "paneLeft") + _dp(MARGIN)
        right = f.int(lay, "paneLeft") + f.int(lay, "paneWidth") - _dp(MARGIN)
        title_top = f.int(lay, "titleTop")
        toolbar_top = f.int(lay, "toolbarTop")
        line_center = f.int(lay, "lineCenter")
        times_top = f.int(lay, "timesTop")
        transport_top = f.int(lay, "transportTop")
        size = _dp(BUTTON)

        def put(view, x, y):
            view.layout(x, y, x + view.getMeasuredWidth(), y + view.getMeasuredHeight())

        inset = _dp(BUTTON)
        put(self.titleView, left + inset, title_top)
        put(self.artistView, left + inset - _dp(6), title_top + _dp(ARTIST_OFFSET))
        put(self.album, left + inset, title_top + _dp(ALBUM_OFFSET))
        put(self.moreButton, *self.more_spot())

        step = self.step()
        # the player's own heart adds to the Telegram profile; here that is a line in the plus's menu
        # the top right corner, level with the arrow that closes the player
        put(self.remote_button, right - size, f.int(lay, "contentTop") + (_dp(HEADER_H) - size) // 2)
        self.profileButton.layout(0, 0, 0, 0)
        put(self.like, left, toolbar_top)
        put(self.add, left + step, toolbar_top)
        self.place_mode_buttons()
        put(self.speedButton, right - size - 2 * step, toolbar_top)
        put(self.repeatButton, right - size - step, toolbar_top)
        put(self.shuffleButton, right - size, toolbar_top)

        put(self.timeView, left, times_top)
        put(self.durationView, right - _dp(TIME_WIDTH), times_top)
        put(self.seekBar, left + _dp(TIME_WIDTH + 4), line_center - _dp(SEEK_LINE))

        center_y = transport_top + (self.controlsView.getMeasuredHeight() - size) // 2
        put(self.volume, left, center_y)
        put(self.equalizer, right - size, center_y)
        put(self.controlsView, left + size + _dp(8), transport_top)

        pane_left = f.int(lay, "paneLeft")
        slot = f.int(lay, "paneWidth") // len(self.tabs)
        put(self.divider, pane_left, self.panel_top)
        self.lyricsView.layout(self.lyricsView.getLeft(), self.lyricsView.getTop(), self.lyricsView.getRight(),
                               self.lyricsView.getTop() + self.lyricsView.getMeasuredHeight())
        for index, tab in enumerate(self.tabs):
            put(tab, pane_left + index * slot, self.panel_top)
        self.place_indicator()
        for _, stack in self.stacks():
            if stack is not None:
                put(stack.root, pane_left, 0)
        if self.queue_screen is not None:
            put(self.queue_screen.root, pane_left, 0)
