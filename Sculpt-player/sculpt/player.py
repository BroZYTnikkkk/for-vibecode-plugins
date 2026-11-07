# Sculpt Player for exteraGram. Copyright 2026 BroNik (@BroZYTnikkkk).

from android_utils import OnClickListener
from java import jclass
from java.lang import Boolean as JBoolean, Integer as JInteger

from .common import ALBUM_H, ALBUM_OFFSET, ARTIST_OFFSET, BUTTON, HEADER_H, MARGIN, MEDIA_CONTROLLER, MODE_PLAYER, MODE_QUEUE, PANEL_ACTIVE, PANEL_H, PANEL_LIBRARY, PANEL_QUEUE, PANEL_TABS, SEEK_H, SEEK_LINE, STEP, TEXT_BLOCK, TIME_WIDTH, TITLE_H, TRANSPORT_H, _dp
from .visualizer import Visualizer
from .music import local_path
from .library_ui import LibraryView, Run, release_on_dismiss
from .queue_ui import QueueScreen


class Player:
    """One open MusicPlayerSheet: its views and the ones this plugin adds to it."""

    NAMES = ("titleView", "artistView", "seekBar", "timeView", "durationView", "controlsView", "profileButton",
             "lyricsButton", "queueButton", "moreButton", "speedButton", "repeatButton", "shuffleButton",
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
        self.album_checked = 0.0
        self.tabs = []
        self.panel_top = 0
        self.divider = None
        self.indicator = None
        self.panel_hidden = False
        self.context = None
        self.active_tab = PANEL_ACTIVE
        self.library = None
        self.like = None
        self.add = None
        self.add_ring = None
        self.queue_screen = None
        self.menu_runs = []

    def library_visible(self):
        return self.library is not None and self.library.visible

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
        self.update_like()
        self.apply_colors(self.plugin.sheet_fields.get(self.sheet, "colors"))
        self.update_album()

    def build_panel(self, context):
        View = jclass("android.view.View")
        self.divider = View(context)
        self.layout.addOwnView(self.divider)
        for index, (title, icons) in enumerate(PANEL_TABS):
            # the others are blanks for now: only the icon and the name, shown as a tooltip on a long press
            tab = self._button(context, icons, title, lambda i=index: self.tab_pressed(i))
            tab.setTooltipText(title)
            self.tabs.append(tab)
        self.indicator = View(context)
        self.layout.addOwnView(self.indicator)
        self.moreButton.bringToFront()

    def tab_pressed(self, index):
        if index in (PANEL_QUEUE, PANEL_ACTIVE, PANEL_LIBRARY):
            self.show_tab(index)

    def show_tab(self, index):
        if index == self.active_tab:
            return
        self.active_tab = index
        colors = self.plugin.sheet_fields.get(self.sheet, "colors")
        if index != PANEL_LIBRARY and self.library_visible():
            self.library.hide()
            self.layout.postInvalidateOnAnimation()
        if index != PANEL_QUEUE and self.queue_visible():
            self.queue_screen.hide()
            self.layout.postInvalidateOnAnimation()
        if index == PANEL_LIBRARY:
            if self.library is None:
                self.library = LibraryView(self, self.context)
                self.library.set_colors(colors)
                self.layout.requestLayout()
            self.library.show()
        elif index == PANEL_QUEUE:
            if self.queue_screen is None:
                self.queue_screen = QueueScreen(self, self.context)
                self.layout.requestLayout()
            self.queue_screen.show()
        if self.mode() == MODE_QUEUE:
            self.set_mode(MODE_PLAYER)
        self.paint_tabs(colors)
        self.place_indicator()

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
            self.library.back()
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
            tab.setColorFilter(PorterDuffColorFilter(colors.accent if index == self.active_tab else colors.icon, mode))

    def place_indicator(self):
        f = self.plugin.layout_fields
        slot = f.int(self.layout, "paneWidth") // (len(self.tabs) + 1)
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
        if self.library is not None:
            self.library.dispose()
            self.library = None
        self.visualizer = None
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
        for view in self.tabs + [self.divider, self.indicator, self.moreButton]:
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
        if self.library is not None:
            self.library.set_colors(colors)
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
            info = jclass("org.telegram.messenger.MediaController").getInstance().getAudioInfo()
            album = info.getAlbum() if info is not None else None
        except Exception:
            pass
        text = str(album) if album else ""
        if str(self.album.getText()) != text:
            self.album.setText(text)
        self.recenter()

    def recenter(self):
        """Beside the small cover in queue and lyrics: the text keeps close to the middle of the screen.

        Its center sits halfway between the screen's right edge and the point halfway across the cover's left
        margin. A long title moves right just enough to clear the cover.
        """
        sf, f = self.plugin.sheet_fields, self.plugin.layout_fields
        progress = max(sf.float(self.sheet, "modeProgress"), sf.float(self.sheet, "canvasTitleProgress"))
        if progress <= 0.0:
            return
        lay = self.layout
        pane_left = f.int(lay, "paneLeft")
        left = pane_left + _dp(MARGIN)
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
        text = pane - 2 * _dp(MARGIN)
        f.set_int(lay, "textWidth", text)
        spec = jclass("android.view.View$MeasureSpec")
        exact = spec.EXACTLY

        def measure(view, width, height):
            view.measure(spec.makeMeasureSpec(max(0, int(width)), exact), spec.makeMeasureSpec(max(0, int(height)), exact))

        measure(self.titleView, text, _dp(TITLE_H))
        measure(self.artistView, text + 2 * _dp(6), _dp(TITLE_H))
        measure(self.album, text, _dp(ALBUM_H))
        measure(self.seekBar, text - 2 * _dp(TIME_WIDTH + 4), _dp(SEEK_H))
        measure(self.timeView, _dp(TIME_WIDTH), _dp(18))
        measure(self.durationView, _dp(TIME_WIDTH), _dp(18))
        for button in (self.like, self.add, self.lyricsButton, self.queueButton, self.moreButton, self.speedButton,
                       self.repeatButton, self.shuffleButton, self.volume, self.equalizer):
            measure(button, _dp(BUTTON), _dp(BUTTON))
        slot = pane // (len(self.tabs) + 1)
        for tab in self.tabs:
            measure(tab, slot, _dp(PANEL_H))
        measure(self.divider, pane, max(1, _dp(1) // 2))
        measure(self.indicator, slot, _dp(2))
        if self.library is not None:
            measure(self.library.root, pane, self.panel_top)
        if self.queue_screen is not None:
            measure(self.queue_screen.root, pane, self.panel_top)

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

        put(self.titleView, left, title_top)
        put(self.artistView, left - _dp(6), title_top + _dp(ARTIST_OFFSET))
        put(self.album, left, title_top + _dp(ALBUM_OFFSET))

        step = self.step()
        # the player's own heart adds to the Telegram profile; here that is a line in the plus's menu
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
        slot = f.int(lay, "paneWidth") // (len(self.tabs) + 1)
        put(self.divider, pane_left, self.panel_top)
        for index, tab in enumerate(self.tabs):
            put(tab, pane_left + index * slot, self.panel_top)
        self.place_indicator()
        put(self.moreButton, pane_left + len(self.tabs) * slot + (slot - size) // 2, self.panel_top + (_dp(PANEL_H) - size) // 2)
        if self.library is not None:
            put(self.library.root, pane_left, 0)
        if self.queue_screen is not None:
            put(self.queue_screen.root, pane_left, 0)
