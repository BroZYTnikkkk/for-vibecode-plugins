# Sculpt Player for exteraGram. Copyright 2026 BroNik (@BroZYTnikkkk).

"""Touches that start on an empty place of the player: a swipe sideways moves to the next or the previous tab,
the way Telegram's chat folders do, and a tap closes the lyrics.

Empty means nothing under the finger has a touch of its own: no button or row that can be pressed, no list
that scrolls sideways, no field, slider or the cover (a swipe on it changes the song)."""

import time

from android_utils import run_on_ui_thread
from java import jarray, jclass, jint

from .common import MODE_LYRICS, MODE_PLAYER, PANEL_ACTIVE, PANEL_TABS, _dp

SWIPE_DP = 72  # how far sideways a finger goes for a tab to change
SWIPE_MS = 700
TAP_MS = 350
OWN_TOUCHES = ("Seek", "Slider", "Controls", "EditText", "Switch", "CheckBox")
OWN, STOP = "own", "stop"


class EmptyPlaceGestures:
    def __init__(self, player):
        self.player = player
        self.slop = jclass("android.view.ViewConfiguration").get(player.context).getScaledTouchSlop()
        self.where = jarray(jint)(2)
        self.down = None  # (x, y, time) of a touch that started on an empty place

    def touch(self, event):
        """Every touch of the player's sheet, before the sheet hands it on; nothing is taken from the views."""
        action = event.getActionMasked()
        if action == 0:  # down
            x, y = float(event.getRawX()), float(event.getRawY())
            self.down = (x, y, time.monotonic()) if self.empty_at(x, y) else None
        elif action == 5 or action == 3:  # a second finger, or the touch was taken over
            self.down = None
        elif action == 1 and self.down is not None:  # up
            x0, y0, t0 = self.down
            self.down = None
            dx, dy = float(event.getRawX()) - x0, float(event.getRawY()) - y0
            spent = time.monotonic() - t0
            if abs(dx) >= _dp(SWIPE_DP) and abs(dx) > 2 * abs(dy) and spent * 1000 < SWIPE_MS:
                step = 1 if dx < 0 else -1  # the finger goes left: the tab on the right comes
                run_on_ui_thread(lambda: self.player.plugin.player is self.player and self.switch(step))
            elif abs(dx) < self.slop and abs(dy) < self.slop and spent * 1000 < TAP_MS and self.lyrics_open():
                run_on_ui_thread(lambda: self.player.plugin.player is self.player and self.close_lyrics())

    # -- what happens

    def switch(self, step):
        player = self.player
        index = max(0, min(len(PANEL_TABS) - 1, player.active_tab + step))
        if index != player.active_tab:
            player.show_tab(index)

    def lyrics_open(self):
        player = self.player
        return (player.active_tab == PANEL_ACTIVE and player.mode() == MODE_LYRICS
                and not (player.library_visible() or player.queue_visible()))

    def close_lyrics(self):
        if self.lyrics_open():
            self.player.set_mode(MODE_PLAYER)

    # -- what is under the finger

    def bounds(self, view):
        view.getLocationOnScreen(self.where)
        x, y = self.where[0], self.where[1]
        return x, y, x + view.getWidth(), y + view.getHeight()

    def shown(self, view):
        return view.getVisibility() == 0 and view.getAlpha() > 0.01 and view.getTransitionAlpha() > 0.01

    def empty_at(self, x, y):
        player = self.player
        layout = player.layout
        if layout is None or not self.shown(layout):
            return False
        left, top, right, bottom = self.bounds(layout)
        if not (left <= x < right and top <= y < bottom):
            return False
        # the screens of the tabs take all touches to keep the player under them from being pressed: not a touch
        # of their own
        catchers = {screen.root.hashCode() for _, screen in player.stacks() if screen is not None}
        if player.queue_screen is not None:
            catchers.add(player.queue_screen.root.hashCode())
        cover = player.coverView if not (player.library_visible() or player.queue_visible()) else None
        # the java.lang.Class itself: the Python proxy of a class has no isInstance
        group = jclass("java.lang.Class").forName("android.view.ViewGroup")
        return self.scan(layout, x, y, group, catchers, cover) != OWN

    def scan(self, view, x, y, group, catchers, cover):
        """What takes a touch at this point inside the view: OWN, STOP (taken with nothing done), or None.

        A view that does nothing with a touch lets it through to the ones under it, the way Android hands it on: a
        lyrics line under a plain overlay still gets the tap, so the place is not empty."""
        if not group.isInstance(view):
            return None
        for i in range(view.getChildCount() - 1, -1, -1):
            child = view.getChildAt(i)
            if not self.shown(child):
                continue
            left, top, right, bottom = self.bounds(child)
            if not (left <= x < right and top <= y < bottom):
                continue
            if cover is not None and child.equals(cover):
                return OWN
            if child.hashCode() in catchers:
                # it takes every touch: what it holds decides, nothing under it gets one
                return self.scan(child, x, y, group, catchers, cover) or STOP
            if (child.isClickable() or child.isLongClickable() or child.canScrollHorizontally(1) or child.canScrollHorizontally(-1)
                    or any(part in str(child.getClass().getSimpleName()) for part in OWN_TOUCHES)):
                return OWN
            found = self.scan(child, x, y, group, catchers, cover)
            if found is not None:
                return found
        return None
