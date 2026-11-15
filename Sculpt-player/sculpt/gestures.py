# Sculpt Player for exteraGram. Copyright 2026 BroNik (@BroZYTnikkkk).

"""Touches of the whole player: a sideways drag pages between the tabs the way Telegram's chat folders do, the
tab following the finger with the next one coming in beside it; a tap on an empty place closes the lyrics.

A drag may start anywhere except on what is dragged itself: the seek bar, the cover (a swipe on it changes the
song), a strip that scrolls sideways, a slider and the queue's drag handles."""

import time

from android_utils import run_on_ui_thread
from java import dynamic_proxy, jarray, jclass, jint

from .common import MODE_LYRICS, MODE_PLAYER, PANEL_ACTIVE, PANEL_TABS
from .i18n import tr

TAP_MS = 350
SETTLE_MS = 240
COMMIT_SHARE = 0.3  # of the width: past this the next tab comes even without a fling
FLING_PX_S = 1100.0
EDGE_PULL = 0.25  # how far a tab follows the finger where there is no tab beyond
DRAGGED = ("Seek", "Slider")  # class names of what follows a finger sideways by itself
OWN_TOUCHES = ("Seek", "Slider", "Controls", "EditText", "Switch", "CheckBox")
OWN, STOP, DRAG = "own", "stop", "drag"


class Updates(dynamic_proxy(jclass("android.animation.ValueAnimator$AnimatorUpdateListener"))):
    def __init__(self, action):
        super().__init__()
        self.action = action

    def onAnimationUpdate(self, animator, *more):
        action = self.action
        if action is not None:
            action(float(animator.getAnimatedValue()))


class Ends(dynamic_proxy(jclass("android.animation.Animator$AnimatorListener"))):
    """Android also calls each of these with an isReverse flag (the interface's default methods): any extra
    argument is taken, or the call raises inside the animation and takes the whole app down."""

    def __init__(self, action):
        super().__init__()
        self.action = action

    def onAnimationEnd(self, animator, *more):
        action, self.action = self.action, None
        if action is not None:
            action()

    def onAnimationCancel(self, animator, *more):
        pass

    def onAnimationStart(self, animator, *more):
        pass

    def onAnimationRepeat(self, animator, *more):
        pass


class TabPager:
    def __init__(self, player):
        self.player = player
        self.slop = jclass("android.view.ViewConfiguration").get(player.context).getScaledTouchSlop()
        self.where = jarray(jint)(2)
        self.start = None  # (x, y, time) of the touch, while it may still become a drag or a tap
        self.can_drag = False
        self.dragging = False
        self.offset = 0.0
        self.width = 1.0
        self.neighbor = None
        self.last = (0.0, 0.0)  # (x, time) a moment ago, for the speed at the end
        self.speed = 0.0
        self.animator = None

    # -- touches

    def touch(self, event):
        """Every touch of the sheet before it is handed on. True: the drag took it, the views do not get it."""
        action = event.getActionMasked()
        x, y, now = float(event.getRawX()), float(event.getRawY()), time.monotonic()
        if action == 0:  # down
            if self.animator is not None:
                self.animator.end()  # a new touch while a tab settles: it lands at once
            self.start = (x, y, now)
            self.can_drag = True  # what is under the finger is looked up once a drag or a tap needs it
            self.dragging = False
            return False
        if self.start is None:
            return False
        x0, y0, t0 = self.start
        dx, dy = x - x0, y - y0
        if action == 5 or action == 3:  # a second finger, or taken over
            self.release(cancelled=True)
            return False
        if action == 2:  # move
            if not self.dragging:
                if not self.can_drag:
                    return False
                if abs(dy) > self.slop * 1.5 and abs(dy) >= abs(dx):
                    self.can_drag = False  # a scroll up or down: not a page any more
                    return False
                if abs(dx) > self.slop * 1.5 and abs(dx) > 1.5 * abs(dy):
                    if self.under(x0, y0) == DRAG:
                        self.can_drag = False  # it started on something dragged by itself: that one moves
                        return False
                    self.begin(event, x)
                return self.dragging
            self.follow(dx, x, now)
            return True
        if action == 1:  # up
            if self.dragging:
                self.follow_speed(x, now)
                self.release()
                return True
            self.start = None
            if (abs(dx) < self.slop and abs(dy) < self.slop and (now - t0) * 1000 < TAP_MS and self.lyrics_open()
                    and self.under(x0, y0) in (None, STOP)):
                run_on_ui_thread(lambda: self.player.plugin.player is self.player and self.close_lyrics())
        return False

    def begin(self, event, x):
        """The touch becomes a page drag: the views under it get a cancel and nothing more of it."""
        self.dragging = True
        self.width = float(max(1, self.player.layout.getWidth()))
        self.last = (x, time.monotonic())
        self.speed = 0.0
        cancel = jclass("android.view.MotionEvent").obtain(event)
        cancel.setAction(3)
        self.player.layout.dispatchTouchEvent(cancel)
        cancel.recycle()

    def follow_speed(self, x, now):
        last_x, last_t = self.last
        if now - last_t > 0.004:
            self.speed = 0.6 * self.speed + 0.4 * (x - last_x) / (now - last_t)
            self.last = (x, now)

    def follow(self, offset, x, now):
        self.follow_speed(x, now)
        player = self.player
        side = 1 if offset < 0 else -1  # the finger goes left: the tab on the right comes
        target = player.active_tab + side
        if not 0 <= target < len(PANEL_TABS):
            target = None
            offset *= EDGE_PULL
        if target != self.neighbor:
            if self.neighbor is not None:
                player.shift_tab(self.neighbor, 0.0)
                player.end_peek(self.neighbor)
            self.neighbor = target
            if target is not None:
                player.peek(target)
        self.place(offset)

    def place(self, offset):
        self.offset = offset
        player = self.player
        player.shift_tab(player.active_tab, offset)
        if self.neighbor is not None:
            side = 1 if self.neighbor > player.active_tab else -1
            player.shift_tab(self.neighbor, offset + side * self.width)
        player.move_indicator(-offset / self.width)

    def release(self, cancelled=False):
        self.start = None
        if not self.dragging:
            return
        self.dragging = False
        neighbor = self.neighbor
        side = 0 if neighbor is None else (1 if neighbor > self.player.active_tab else -1)
        # side 1: the finger went left, offset and speed are negative while the next tab comes
        going = (not cancelled and neighbor is not None
                 and (abs(self.offset) > self.width * COMMIT_SHARE or -side * self.speed > FLING_PX_S)
                 and not side * self.speed > FLING_PX_S)  # flung back the other way
        self.settle(self.offset, -side * self.width if going else 0.0, going)

    def settle(self, begin, end, going):
        player = self.player
        animator = jclass("android.animation.ValueAnimator").ofFloat(0.0, 1.0)
        share = min(1.0, abs(end - begin) / self.width)
        animator.setDuration(int(max(90, SETTLE_MS * share)))
        animator.setInterpolator(jclass("android.view.animation.DecelerateInterpolator")(1.6))
        updates = Updates(lambda t: self.place(begin + (end - begin) * t))
        animator.addUpdateListener(updates)
        self.animator = animator

        def done():
            if self.animator is not animator:
                return
            self.animator = None
            updates.action = None
            neighbor, self.neighbor = self.neighbor, None
            player.shift_tab(player.active_tab, 0.0)
            player.move_indicator(0.0)
            if neighbor is not None:
                player.shift_tab(neighbor, 0.0)
                if going:
                    player.show_tab(neighbor, swiped=True)
                else:
                    player.end_peek(neighbor)

        animator.addListener(Ends(lambda: player.guarded_menu(done)))
        animator.start()

    def dispose(self):
        if self.animator is not None:
            self.animator.end()
        self.animator = None

    # -- the lyrics

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

    @staticmethod
    def shown(view):
        return view.getVisibility() == 0 and view.getAlpha() > 0.01 and view.getTransitionAlpha() > 0.01

    def under(self, x, y):
        """DRAG when the finger is on something dragged by itself; OWN when on something that takes the touch;
        STOP when only on a tab's screen that keeps the player under it from being pressed; None when on nothing."""
        player = self.player
        layout = player.layout
        if layout is None or not self.shown(layout):
            return OWN
        catchers = {screen.root.hashCode() for _, screen in player.stacks() if screen is not None}
        if player.queue_screen is not None:
            catchers.add(player.queue_screen.root.hashCode())
        over_player = not (player.library_visible() or player.queue_visible())
        cover = player.coverView if over_player and player.mode() != MODE_LYRICS else None
        # the java.lang.Class itself: the Python proxy of a class has no isInstance
        group = jclass("java.lang.Class").forName("android.view.ViewGroup")
        return self.scan(layout, x, y, group, catchers, cover, tr("Перетащить"))

    def scan(self, view, x, y, group, catchers, cover, handle):
        """A view that does nothing with a touch lets it through to the ones under it, the way Android hands it on."""
        if not group.isInstance(view):
            return None
        for i in range(view.getChildCount() - 1, -1, -1):
            child = view.getChildAt(i)
            if not self.shown(child):
                continue
            left, top, right, bottom = self.bounds(child)
            if not (left <= x < right and top <= y < bottom):
                continue
            name = str(child.getClass().getSimpleName())
            if ((cover is not None and child.equals(cover)) or child.canScrollHorizontally(1) or child.canScrollHorizontally(-1)
                    or any(part in name for part in DRAGGED) or str(child.getContentDescription() or "") == handle):
                return DRAG
            inside = self.scan(child, x, y, group, catchers, cover, handle)
            if inside == DRAG:
                return DRAG
            if child.hashCode() in catchers:
                return inside or STOP  # it takes every touch: nothing under it gets one
            if inside is not None:
                return inside
            if child.isClickable() or child.isLongClickable() or any(part in name for part in OWN_TOUCHES):
                return OWN
        return None
