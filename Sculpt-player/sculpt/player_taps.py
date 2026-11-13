# Sculpt Player for exteraGram. Copyright 2026 BroNik (@BroZYTnikkkk).

"""What a tap on the player does: the title opens the song's info, the author and the album open in the library
(or in the Search tab when the library has none of them), the cover does the chosen action, a long press on the
cover opens its menu.

The cover view has no click of its own: a tap that does not move ends its touch with nothing done. Its touches
are read here through a GestureDetector, fed from PlayerCoverView.dispatchTouchEvent (CoverTouchHook), so a swipe
stays a swipe and a tap or a long press is told apart the way Android tells them apart everywhere.
"""

import re
import threading

from android_utils import OnClickListener, run_on_ui_thread
from java import dynamic_proxy, jclass

from .i18n import tr
from .common import MEDIA_CONTROLLER, MODE_LYRICS, PANEL_SEARCH, _dp, _log
from .music import find_group, local_path

COVER_ACTIONS = (tr("Ничего"), tr("Посмотреть обложку"), tr("Открыть текст песни"), tr("Плей/пауза"))
COVER_DEFAULT = 1
GALLERY_FOLDER = "Pictures/Sculpt Player"


def cover_action(plugin):
    try:
        value = int(plugin.get_setting("cover_tap", COVER_DEFAULT))
    except (TypeError, ValueError):
        value = COVER_DEFAULT
    return value if 0 <= value < len(COVER_ACTIONS) else COVER_DEFAULT


class Run(dynamic_proxy(jclass("java.lang.Runnable"))):
    def __init__(self, action):
        super().__init__()
        self.action = action

    def run(self):
        action, self.action = self.action, None
        if action is not None:
            action()


class Dismissed(dynamic_proxy(jclass("android.content.DialogInterface$OnDismissListener"))):
    def __init__(self, action):
        super().__init__()
        self.action = action

    def onDismiss(self, dialog):
        action, self.action = self.action, None
        if action is not None:
            action()


class Gestures(dynamic_proxy(jclass("android.view.GestureDetector$OnGestureListener"))):
    def __init__(self, taps):
        super().__init__()
        self.taps = taps

    def onDown(self, event):
        return True

    def onShowPress(self, event):
        pass

    def onSingleTapUp(self, event):
        taps = self.taps
        if taps is not None:
            taps.guarded(taps.cover_tapped)
        return False

    def onScroll(self, first, event, dx, dy):
        return False

    def onLongPress(self, event):
        taps = self.taps
        if taps is not None:
            taps.guarded(taps.cover_pressed)

    def onFling(self, first, event, vx, vy):
        return False


class Taps:
    def __init__(self, plugin, player):
        self.plugin = plugin
        self.player = player
        self.views = []
        self.gestures = None
        self.detector = None
        self.inside = False

    def guarded(self, action, *args):
        try:
            action(*args)
        except Exception as e:
            self.plugin.report("player taps", e)

    def attach(self):
        player = self.player
        for switcher, action in ((player.titleView, self.song_info), (player.artistView, self.open_artist)):
            for label in (switcher.getTextView(), switcher.getNextTextView()):
                if label is not None:
                    self.listen(label, action)
        self.listen(player.album, self.open_album)
        self.gestures = Gestures(self)
        self.detector = jclass("android.view.GestureDetector")(player.context, self.gestures)

    def listen(self, view, action):
        view.setOnClickListener(OnClickListener(lambda _: self.guarded(action)))
        self.views.append(view)

    def detach(self):
        for view in self.views:
            try:
                view.setOnClickListener(None)
            except Exception:
                pass
        self.views = []
        if self.gestures is not None:
            self.gestures.taps = None
        self.gestures = None
        self.detector = None

    # -- the cover's touches, from CoverTouchHook

    def cover_touch(self, cover, event):
        """Every touch of the cover view, before it handles it; a touch outside the cover itself is not ours."""
        if self.detector is None:
            return
        action = event.getActionMasked()
        if action == 0:  # down
            player = self.player
            mode = self.plugin.sheet_fields.float(player.sheet, "modeProgress")
            self.inside = (cover.getCoverRect().contains(event.getX(), event.getY()) and mode < 0.01
                           and player.canvas_amount() < 0.5  # a video fills the screen: the cover is a thumbnail
                           and not (player.library_visible() or player.queue_visible()))
        if self.inside:
            self.detector.onTouchEvent(event)
        if action in (1, 3):  # up, cancel
            self.inside = False

    def cover_tapped(self):
        if float(self.player.coverView.getPageOffset()) != 0.0:
            return  # the end of a small swipe
        action = cover_action(self.plugin)
        if action == 1:
            self.view_cover()
        elif action == 2:
            self.player.set_mode(MODE_LYRICS)
        elif action == 3:
            controller = jclass(MEDIA_CONTROLLER).getInstance()
            playing = controller.getPlayingMessageObject()
            if playing is None:
                return
            if controller.isMessagePaused():
                controller.playMessage(playing)
            else:
                controller.pauseMessage(playing)

    def cover_pressed(self):
        CoverMenu(self).show()

    # -- what plays

    @staticmethod
    def playing():
        return jclass(MEDIA_CONTROLLER).getInstance().getPlayingMessageObject()

    @staticmethod
    def file_of(message):
        path = local_path(message)
        if path is not None:
            return path
        try:
            loaded = jclass("org.telegram.messenger.FileLoader").getInstance(message.currentAccount).getPathToMessage(message.messageOwner)
            if loaded is not None and loaded.exists():
                return str(loaded.getAbsolutePath())
        except Exception:
            pass
        return None

    def say(self, text, icon="info"):
        self.plugin.bulletin(self.player.sheet, icon, text)

    # -- the title, the author, the album

    def song_info(self):
        message = self.playing()
        if message is None:
            return
        from .song_info import SongInfo
        fallback = {"title": str(message.getMusicTitle() or ""), "artist": str(message.getMusicAuthor() or ""),
                    "album": str(self.player.album.getText() or ""), "seconds": message.getDuration()}
        SongInfo(self.player, self.file_of(message), local_path(message), fallback).show()

    def open_artist(self):
        message = self.playing()
        if message is None:
            return
        name = str(message.getMusicAuthor() or "").strip()
        if not name:
            self.say(tr("У этой песни не указан исполнитель."))
            return
        if find_group(self.plugin.music, "artists", name) is not None:
            self.player.open_group("artists", name)
        else:
            self.search_online(name)

    def open_album(self):
        album = str(self.player.album.getText() or "").strip()
        if not album:
            return
        if find_group(self.plugin.music, "albums", album) is not None:
            self.player.open_group("albums", album)
            return
        message = self.playing()
        artist = str(message.getMusicAuthor() or "").strip() if message is not None else ""
        self.search_online(("%s %s" % (artist, album)).strip())

    def search_online(self, query):
        """Not in the library: the Search tab looks for it through the services."""
        player = self.player
        player.show_tab(PANEL_SEARCH)
        tab = player.search_tab
        if tab is None or not tab.stack:
            return
        if len(tab.stack) > 1:
            tab.to_root()
        screen = tab.stack[0]
        if getattr(screen, "field", None) is None:
            return
        screen.field.setText(query)
        screen.field.setSelection(len(query))
        screen.search()

    # -- the cover

    def cover_bitmap(self):
        """The playing song's cover at its full size: the file's own picture, else what the cover view shows."""
        message = self.playing()
        try:
            info = jclass(MEDIA_CONTROLLER).getInstance().getAudioInfo()
            if info is not None and info.getCover() is not None:
                return info.getCover()
        except Exception:
            pass
        bitmap = self.player.coverView.getImageReceiver().getBitmap()
        if bitmap is not None:
            return bitmap
        path = local_path(message)
        if path is not None:
            jpg = self.plugin.music.covers.cached(path)[1]
            if jpg is not None:
                return jclass("android.graphics.BitmapFactory").decodeFile(jpg)
        return None

    def view_cover(self):
        bitmap = self.cover_bitmap()
        if bitmap is None:
            self.say(tr("У этой песни нет обложки."))
            return
        message = self.playing()
        name = ""
        if message is not None:
            name = " - ".join(p for p in (str(message.getMusicAuthor() or ""), str(message.getMusicTitle() or "")) if p)
        CoverViewer(self, bitmap, name).show()

    def edit_cover(self):
        path = local_path(self.playing())
        if path is None:
            self.say(tr("Обложку можно изменить только у песни с телефона."))
            return
        self.player.edit_tags(path)
        screen = self.player.library.stack[-1] if self.player.library is not None and self.player.library.stack else None
        if hasattr(screen, "choose_cover"):
            screen.choose_cover()  # the picture is asked for at once; the editor shows it and writes it with "Save"


# -- the full-screen cover ------------------------------------------------------------------------------------


class TouchListener(dynamic_proxy(jclass("android.view.View$OnTouchListener"))):
    def __init__(self, viewer):
        super().__init__()
        self.viewer = viewer

    def onTouch(self, view, event):
        viewer = self.viewer
        if viewer is None:
            return False
        try:
            return viewer.touched(event)
        except Exception as e:
            viewer.taps.plugin.report("cover viewer", e)
            return True


class Pinch(dynamic_proxy(jclass("android.view.ScaleGestureDetector$OnScaleGestureListener"))):
    def __init__(self, viewer):
        super().__init__()
        self.viewer = viewer

    def onScaleBegin(self, detector):
        return True

    def onScale(self, detector):
        if self.viewer is not None:
            self.viewer.zoom(detector.getScaleFactor(), detector.getFocusX(), detector.getFocusY())
        return True

    def onScaleEnd(self, detector):
        pass


class Pan(dynamic_proxy(jclass("android.view.GestureDetector$OnGestureListener"),
                        jclass("android.view.GestureDetector$OnDoubleTapListener"))):
    def __init__(self, viewer):
        super().__init__()
        self.viewer = viewer

    def onDown(self, event):
        return True

    def onShowPress(self, event):
        pass

    def onSingleTapUp(self, event):
        return False

    def onScroll(self, first, event, dx, dy):
        if self.viewer is not None:
            self.viewer.move(-dx, -dy)
        return True

    def onLongPress(self, event):
        pass

    def onFling(self, first, event, vx, vy):
        return False

    def onSingleTapConfirmed(self, event):
        if self.viewer is not None:
            self.viewer.toggle_controls()
        return True

    def onDoubleTap(self, event):
        if self.viewer is not None:
            self.viewer.double_tap(event.getX(), event.getY())
        return True

    def onDoubleTapEvent(self, event):
        return False


class CoverViewer:
    """The cover across the screen: pinch or double tap to zoom, drag to look around, "Save to gallery" under it.
    A single tap hides and shows the buttons."""

    MAX_ZOOM = 6.0

    def __init__(self, taps, bitmap, name):
        self.taps = taps
        self.bitmap = bitmap
        self.name = name
        self.context = taps.player.context
        self.dialog = None
        self.image = None
        self.matrix = jclass("android.graphics.Matrix")()
        self.base = 1.0
        self.scale = 1.0
        self.listeners = []
        self.controls = []
        self.pinch = None
        self.pan = None
        self.scaler = None
        self.mover = None

    def show(self):
        context = self.context
        FrameLayout = jclass("android.widget.FrameLayout")
        Frame = jclass("android.widget.FrameLayout$LayoutParams")
        root = FrameLayout(context)
        root.setBackgroundColor(-16777216)
        self.image = jclass("android.widget.ImageView")(context)
        self.image.setScaleType(jclass("android.widget.ImageView$ScaleType").MATRIX)
        self.image.setImageBitmap(self.bitmap)
        root.addView(self.image, Frame(-1, -1))
        self.pinch = Pinch(self)
        self.pan = Pan(self)
        self.scaler = jclass("android.view.ScaleGestureDetector")(context, self.pinch)
        self.mover = jclass("android.view.GestureDetector")(context, self.pan)
        self.mover.setOnDoubleTapListener(self.pan)
        touch = TouchListener(self)
        self.image.setOnTouchListener(touch)
        self.listeners.append((self.image, "touch", touch))

        close = jclass("android.widget.ImageView")(context)
        resources = context.getResources()
        close.setImageResource(resources.getIdentifier("ic_close_white", "drawable", context.getPackageName()))
        close.setScaleType(jclass("android.widget.ImageView$ScaleType").CENTER)
        close.setContentDescription(tr("Закрыть"))
        close.setBackground(rounded(jclass("androidx.core.graphics.ColorUtils").setAlphaComponent(-16777216, 120), 22))
        self.on_click(close, self.close)
        top = Frame(_dp(44), _dp(44), 8388659)  # top start
        top.setMargins(_dp(12), jclass("org.telegram.messenger.AndroidUtilities").statusBarHeight + _dp(8), 0, 0)
        root.addView(close, top)

        save = jclass("android.widget.TextView")(context)
        save.setText(tr("Сохранить в галерею"))
        save.setTextSize(1, 16.0)
        save.setTextColor(-16777216)
        save.setTypeface(jclass("org.telegram.messenger.AndroidUtilities").bold())
        save.setGravity(17)
        save.setPadding(_dp(24), 0, _dp(24), 0)
        save.setBackground(rounded(-1, 24))
        self.on_click(save, self.save)
        bottom = Frame(-2, _dp(48), 81)  # bottom center
        bottom.setMargins(0, 0, 0, _dp(36))
        root.addView(save, bottom)
        self.controls = [close, save]

        style = jclass("android.R$style").Theme_Black_NoTitleBar_Fullscreen
        self.dialog = jclass("android.app.Dialog")(context, style)
        self.dialog.setContentView(root)
        self.dialog.setOnDismissListener(Dismissed(self.release))
        self.dialog.show()
        self.image.post(Run(lambda: self.taps.guarded(self.fit)))

    def on_click(self, view, action):
        listener = OnClickListener(lambda _: self.taps.guarded(action))
        view.setOnClickListener(listener)
        self.listeners.append((view, "click", listener))

    # -- zoom and pan

    def fit(self):
        if self.image is None:
            return
        width, height = self.image.getWidth(), self.image.getHeight()
        bw, bh = self.bitmap.getWidth(), self.bitmap.getHeight()
        if width <= 0 or height <= 0 or bw <= 0 or bh <= 0:
            return
        self.base = min(float(width) / bw, float(height) / bh)
        self.scale = self.base
        self.matrix.reset()
        self.matrix.postScale(self.base, self.base)
        self.matrix.postTranslate((width - bw * self.base) / 2.0, (height - bh * self.base) / 2.0)
        self.apply()

    def touched(self, event):
        self.scaler.onTouchEvent(event)
        if not self.scaler.isInProgress():
            self.mover.onTouchEvent(event)
        return True

    def zoom(self, factor, x, y):
        target = max(self.base, min(self.base * self.MAX_ZOOM, self.scale * factor))
        factor = target / self.scale
        if abs(factor - 1.0) < 1e-4:
            return
        self.scale = target
        self.matrix.postScale(factor, factor, x, y)
        self.apply()

    def move(self, dx, dy):
        if self.scale <= self.base * 1.001:
            return
        self.matrix.postTranslate(dx, dy)
        self.apply()

    def double_tap(self, x, y):
        if self.scale > self.base * 1.05:
            self.fit()
        else:
            self.zoom(2.5, x, y)

    def apply(self):
        """Keeps the picture on the screen: never a gap at an edge while it is larger than the screen."""
        rect = jclass("android.graphics.RectF")(0.0, 0.0, float(self.bitmap.getWidth()), float(self.bitmap.getHeight()))
        self.matrix.mapRect(rect)
        width, height = float(self.image.getWidth()), float(self.image.getHeight())
        dx = dy = 0.0
        if rect.width() <= width:
            dx = (width - rect.width()) / 2.0 - rect.left
        elif rect.left > 0:
            dx = -rect.left
        elif rect.right < width:
            dx = width - rect.right
        if rect.height() <= height:
            dy = (height - rect.height()) / 2.0 - rect.top
        elif rect.top > 0:
            dy = -rect.top
        elif rect.bottom < height:
            dy = height - rect.bottom
        self.matrix.postTranslate(dx, dy)
        self.image.setImageMatrix(self.matrix)

    def toggle_controls(self):
        for view in self.controls:
            view.setVisibility(8 if view.getVisibility() == 0 else 0)

    # -- saving

    def save(self):
        bitmap, name, context = self.bitmap, self.name, self.context

        def work():
            try:
                saved = save_to_gallery(context, bitmap, name)
                text = tr("Обложка сохранена в Галерею: %s") % GALLERY_FOLDER if saved else tr("Не получилось сохранить обложку.")
            except Exception as e:
                _log("save cover: %s" % e)
                text = tr("Не получилось сохранить обложку.")
            run_on_ui_thread(lambda: jclass("android.widget.Toast").makeText(context, text, 0).show())

        threading.Thread(target=work, name="sculpt-save-cover", daemon=True).start()

    def close(self):
        if self.dialog is not None:
            self.dialog.dismiss()

    def release(self):
        for view, kind, listener in self.listeners:
            try:
                if kind == "click":
                    view.setOnClickListener(None)
                else:
                    view.setOnTouchListener(None)
            except Exception:
                pass
            if hasattr(listener, "viewer"):
                listener.viewer = None
        self.listeners = []
        for proxy in (self.pinch, self.pan):
            if proxy is not None:
                proxy.viewer = None
        self.image = None
        self.dialog = None


def rounded(color, radius):
    shape = jclass("android.graphics.drawable.GradientDrawable")()
    shape.setColor(color)
    shape.setCornerRadius(float(_dp(radius)))
    return shape


def save_to_gallery(context, bitmap, name):
    """Into Pictures/Sculpt Player through MediaStore: no permission is needed for a picture an app adds."""
    MediaStore = jclass("android.provider.MediaStore")
    values = jclass("android.content.ContentValues")()
    clean = re.sub(r'[\\/:*?"<>|]+', " ", name or "").strip() or tr("Обложка")
    values.put("_display_name", "%s.jpg" % clean[:80])
    values.put("mime_type", "image/jpeg")
    values.put("relative_path", GALLERY_FOLDER)
    resolver = context.getContentResolver()
    uri = resolver.insert(MediaStore.Images.Media.EXTERNAL_CONTENT_URI, values)
    if uri is None:
        return False
    stream = resolver.openOutputStream(uri)
    try:
        return bool(bitmap.compress(jclass("android.graphics.Bitmap$CompressFormat").JPEG, 95, stream))
    finally:
        stream.close()


# -- the long press: what to do with the cover, and what a tap on it does -------------------------------------


class DialogButton(dynamic_proxy(jclass("org.telegram.ui.ActionBar.AlertDialog$OnButtonClickListener"))):
    def __init__(self, action):
        super().__init__()
        self.action = action

    def onClick(self, dialog, which):
        action, self.action = self.action, None
        if action is not None:
            action()


class CoverMenu:
    """Two things to do with the cover, then what a tap on it does; "Save" keeps that choice, "Cancel" does not."""

    def __init__(self, taps):
        self.taps = taps
        self.context = taps.player.context
        self.dialog = None
        self.chosen = cover_action(taps.plugin)
        self.listeners = []
        self.marks = []
        Theme = jclass("org.telegram.ui.ActionBar.Theme")
        self.text = Theme.getColor(Theme.key_dialogTextBlack)
        self.second = Theme.getColor(Theme.key_dialogTextGray3)
        self.accent = Theme.getColor(Theme.key_dialogTextLink)

    def label(self, size, color, bold=False):
        view = jclass("android.widget.TextView")(self.context)
        view.setTextSize(1, float(size))
        view.setTextColor(color)
        if bold:
            view.setTypeface(jclass("org.telegram.messenger.AndroidUtilities").bold())
        return view

    def row(self, column, icon_names, title, action, tint=None):
        context = self.context
        Params = jclass("android.widget.LinearLayout$LayoutParams")
        row = jclass("android.widget.LinearLayout")(context)
        row.setOrientation(0)
        row.setGravity(16)
        row.setPadding(_dp(24), 0, _dp(24), 0)
        row.setBackground(jclass("org.telegram.ui.ActionBar.Theme").getSelectorDrawable(False))
        icon = jclass("android.widget.ImageView")(context)
        resources = context.getResources()
        for name in icon_names:
            res = resources.getIdentifier(name, "drawable", context.getPackageName())
            if res:
                icon.setImageResource(res)
                break
        icon.setColorFilter(jclass("android.graphics.PorterDuffColorFilter")(tint if tint is not None else self.second,
                                                                             jclass("android.graphics.PorterDuff$Mode").SRC_IN))
        row.addView(icon, Params(_dp(24), _dp(24)))
        name = self.label(16, self.text)
        name.setText(title)
        at = Params(0, -2, 1.0)
        at.setMarginStart(_dp(20))
        row.addView(name, at)
        row.setContentDescription(title)
        row.setOnClickListener(OnClickListener(lambda _: self.taps.guarded(action)))
        self.listeners.append(row)
        column.addView(row, Params(-1, _dp(52)))
        return row

    def show(self):
        context = self.context
        Params = jclass("android.widget.LinearLayout$LayoutParams")
        column = jclass("android.widget.LinearLayout")(context)
        column.setOrientation(1)
        column.setPadding(0, _dp(4), 0, _dp(4))
        self.row(column, ("msg_photos", "msg_gallery", "msg_media"), tr("Посмотреть обложку"),
                 lambda: (self.close(), self.taps.view_cover()))
        self.row(column, ("msg_edit", "menu_tag_edit"), tr("Изменить обложку альбома"),
                 lambda: (self.close(), self.taps.edit_cover()))
        head = self.label(14, self.accent, True)
        head.setText(tr("Нажатие на обложку"))
        head.setPadding(_dp(24), _dp(16), _dp(24), _dp(4))
        column.addView(head, Params(-1, -2))
        for index, title in enumerate(COVER_ACTIONS):
            row = self.row(column, ("msg_text_check",), title, lambda i=index: self.choose(i), self.accent)
            self.marks.append(row.getChildAt(0))
        self.paint()
        builder = jclass("org.telegram.ui.ActionBar.AlertDialog$Builder")(context)
        builder.setTitle(tr("Обложка"))
        builder.setView(column)
        builder.setNegativeButton(tr("Отмена"), DialogButton(None))
        builder.setPositiveButton(tr("Сохранить"), DialogButton(self.save))
        self.dialog = builder.create()
        self.dialog.setOnDismissListener(Dismissed(self.release))
        self.dialog.show()

    def choose(self, index):
        self.chosen = index
        self.paint()

    def paint(self):
        for index, mark in enumerate(self.marks):
            mark.setVisibility(0 if index == self.chosen else 4)  # invisible keeps the room

    def save(self):
        plugin = self.taps.plugin
        if self.chosen != cover_action(plugin):
            plugin.set_setting("cover_tap", self.chosen)
            self.taps.say(tr("Нажатие на обложку: %s") % COVER_ACTIONS[self.chosen].lower())

    def close(self):
        if self.dialog is not None:
            self.dialog.dismiss()

    def release(self):
        for view in self.listeners:
            try:
                view.setOnClickListener(None)
            except Exception:
                pass
        self.listeners = []
        self.marks = []
        self.dialog = None
