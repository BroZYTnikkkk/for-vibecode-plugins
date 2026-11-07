# Sculpt Player for exteraGram. Copyright 2026 BroNik (@BroZYTnikkkk).

from android_utils import run_on_ui_thread
from base_plugin import BasePlugin, MenuItemData, MenuItemType
from java import dynamic_proxy, jarray, jclass
from java.lang import Boolean as JBoolean, Float as JFloat, Integer as JInteger, Long as JLong
from ui.bulletin import BulletinHelper
from ui.settings import Divider

from .common import CHECKS, COLORS, CONFIG, CONTROLS, COVER, Fields, ID_COVER_RADIUS, ID_FLAT_SEEK, ID_VIS_BOTTOM, ID_VIS_COLORS, ID_VIS_DENSITY, ID_VIS_HEIGHT, ID_VIS_STYLE, ID_VIS_TOP, LAYOUT, MEDIA_CONTROLLER, MESSAGE_OBJECT, PLAYER_COVERS, RADIUS_LABELS, RADIUS_VALUES, SEGMENT_DRAWABLE, SETTINGS_SHEET, SHEET, VERSION, VIS_COLORS, VIS_DENSITIES, VIS_HEIGHTS, VIS_STYLES, _ctx, _java_class, _log, _show_error
from .music import ListenTimer, MusicData, local_path
from .library_ui import Run
from .player import Player
from .queues import QueueStore
from .extensions import SFLX_CONDITION, Extensions
from .hooks import ArtworkHook, BackHook, BindHook, ColorsHook, ConstructorHook, ControlsColorsHook, CoverRectHook, DetachHook, DrawHook, HeaderHook, LayoutHook, ModeHook, ModeSegmentColorsHook, ModeSegmentsHook, NeedsArtworkHook, NewPlayerHook, PlayHook, PlaylistHook, PredictiveBackHook, RhythmHook, SettingsClickHook, SettingsFillHook, SpeedColorsHook, SwipeAreaHook, TransitionsHook


class SculptPlayerPlugin(BasePlugin):
    def __init__(self):
        super().__init__()
        self.hooks = []
        self.player = None
        self.sheet_fields = None
        self.layout_fields = None
        self.reported = set()
        self.callbacks = []
        self.music = None
        self.queues = None
        # "stop after this song": the song's identity, and the one that played last
        self.stop_after = None
        self.last_song = None
        self.listen = None
        self.media_fields = None
        self.sheet_methods = {}
        self.extensions = None

    def on_plugin_load(self):
        try:
            self.sheet_fields = Fields(SHEET)
            self.media_fields = Fields(MEDIA_CONTROLLER)
            self.music = MusicData(self)
            self.music.covers.on_extracted = self.cover_extracted
            self.queues = QueueStore(self)
            self.listen = ListenTimer(self)
            self.layout_fields = Fields(LAYOUT)
            self.cover_fields = Fields(COVER)
            sheet = self.sheet_fields.cls
            layout = self.layout_fields.cls
            view = _java_class("android.widget.ImageView")
            drawable = _java_class(SEGMENT_DRAWABLE)
            colors = _java_class(COLORS)
            controls = _java_class(CONTROLS)
            cover = _java_class(COVER)
            config = _java_class(CONFIG)
            i, f, b = JInteger.TYPE, JFloat.TYPE, JBoolean.TYPE

            self.remember(self.hook_all_constructors(sheet, ConstructorHook(self, "constructor")))
            self.install(layout, "computeGeometry", (i,), LayoutHook(self, "computeGeometry", lambda p, a: p.geometry(int(a.args[0]))))
            self.install(layout, "onMeasure", (i, i), LayoutHook(self, "onMeasure", lambda p, a: p.measure()))
            self.install(layout, "onLayout", (b, i, i, i, i), LayoutHook(self, "onLayout", lambda p, a: p.place()))
            self.install(layout, "layoutModeSegments", (), ModeSegmentsHook(self, "layoutModeSegments"))
            self.install(sheet, "applyModeSegment", (view, drawable, colors), ModeSegmentColorsHook(self, "applyModeSegment"))
            self.install(sheet, "applyColors", (colors,), ColorsHook(self, "applyColors"))
            self.install(sheet, "applySpeedColors", (colors,), SpeedColorsHook(self, "applySpeedColors"))
            self.install(sheet, "applyTransitions", (), TransitionsHook(self, "applyTransitions"))
            self.install(sheet, "bindMessage", (b, b), BindHook(self, "bindMessage"))
            self.install(sheet, "updateRhythm", (), RhythmHook(self, "updateRhythm"))
            self.install(layout, "onDraw", (_java_class("android.graphics.Canvas"),), DrawHook(self, "onDraw"))
            self.install(controls, "setColors", (i, i, i, i), ControlsColorsHook(self, "setColors"))
            self.install(cover, "setCoverRect", (f, f, f, f, f), CoverRectHook(self, "setCoverRect"))
            self.install(config, "getNewPlayerStyle", (), NewPlayerHook(self, "getNewPlayerStyle"))
            self.install(sheet, "updateHeader", (), HeaderHook(self, "updateHeader"))
            self.install(sheet, "setMode", (i, b), ModeHook(self, "setMode"))
            self.install(layout, "onDetachedFromWindow", (), DetachHook(self, "onDetachedFromWindow"))
            self.install(sheet, "onBackPressed", (), BackHook(self, "onBackPressed"))
            self.install_predictive_back()
            self.install(sheet, "isSwipeDismissArea", (f, f), SwipeAreaHook(self, "isSwipeDismissArea"))
            message = _java_class(MESSAGE_OBJECT)
            self.install(message, "getArtworkUrl", (b,), ArtworkHook(self, "getArtworkUrl"))
            self.install(_java_class(PLAYER_COVERS), "needsArtwork", (message,), NeedsArtworkHook(self, "needsArtwork"))
            self.remember(self.hook_all_methods(self.media_fields.cls, "playMessage", PlayHook(self, "playMessage")))
            self.install(self.media_fields.cls, "setPlaylist", (_java_class("java.util.ArrayList"), message, JLong.TYPE, b,
                                                                _java_class(MEDIA_CONTROLLER + "$PlaylistGlobalSearchParams")),
                         PlaylistHook(self, "setPlaylist"))
            settings = _java_class(SETTINGS_SHEET)
            self.install(settings, "fillItems", (_java_class("java.util.ArrayList"), _java_class("org.telegram.ui.Components.UniversalAdapter")),
                         SettingsFillHook(self, "fillItems"))
            self.install(settings, "onItemClick", (_java_class("org.telegram.ui.Components.UItem"), _java_class("android.view.View")),
                         SettingsClickHook(self, "onItemClick"))
            self.extensions = Extensions(self)
            self.add_menu_item(MenuItemData(
                menu_type=MenuItemType.MESSAGE_CONTEXT_MENU,
                text="Установить расширение",
                icon="msg_plugins",
                condition=SFLX_CONDITION,
                on_click=self.extensions.install_message,
            ))
            from . import music as music_module
            tags = music_module.mutagen
            _log("loaded %s, mutagen %s" % (VERSION, getattr(tags, "version_string", None) if tags else "missing"))
        except Exception as e:
            _show_error("Sculpt Player: не удалось загрузиться", e)

    def on_plugin_unload(self):
        for handle in self.hooks:
            try:
                self.unhook_method(handle)
            except Exception:
                pass
        self.hooks = []
        if self.player is not None:
            try:
                self.player.dispose()
            except Exception:
                pass
        self.player = None
        if self.listen is not None:
            self.listen.stopped = True
        if self.extensions is not None:
            self.extensions.close()

    def install_predictive_back(self):
        """BottomSheet's back callback is an anonymous class: the one that implements OnBackAnimationCallback.
        Phones before Android 13 have no such callback, and back goes through onBackPressed there."""
        try:
            wanted = _java_class("android.window.OnBackAnimationCallback")
            event = _java_class("android.window.BackEvent")
        except Exception:
            return
        for number in range(1, 40):
            try:
                cls = _java_class("org.telegram.ui.ActionBar.BottomSheet$%d" % number)
            except Exception:
                continue
            if not wanted.isAssignableFrom(cls):
                continue
            try:
                self.install(cls, "onBackInvoked", (), PredictiveBackHook(self, "onBackInvoked", "invoked"))
                self.install(cls, "onBackStarted", (event,), PredictiveBackHook(self, "onBackStarted", "started"))
                self.install(cls, "onBackProgressed", (event,), PredictiveBackHook(self, "onBackProgressed", "progressed"))
                _log("predictive back: %s" % cls.getName())
            except Exception as e:
                # without these the player still works; back just closes it from any tab
                _log("predictive back: %s" % e)
            return
        _log("predictive back: no callback class found")

    def install(self, cls, name, types, handler):
        method = cls.getDeclaredMethod(name, *types)
        method.setAccessible(True)
        handle = self.hook_method(method, handler)
        if not handle:
            handle = self.hook_all_methods(cls, name, handler)
        if not handle:
            raise RuntimeError("no hook on %s" % name)
        self.remember(handle)

    def remember(self, handle):
        if isinstance(handle, (list, tuple)):
            self.hooks.extend(handle)
        elif handle:
            self.hooks.append(handle)

    def report(self, name, exc):
        # Layout hooks fire many times a second: one bulletin per failing hook is enough.
        if name not in self.reported:
            self.reported.add(name)
            _show_error("Sculpt Player: ошибка в %s" % name, exc)

    def sheet_method(self, name, *types):
        method = self.sheet_methods.get(name)
        if method is None:
            method = self.sheet_fields.cls.getDeclaredMethod(name, *types)
            method.setAccessible(True)
            self.sheet_methods[name] = method
        return method

    def sheet_menu(self, sheet, anchor, swipeback):
        """The player's own menu builder, so these menus look and dim like its other ones."""
        method = self.sheet_method("makeMenu", _java_class("android.view.View"), JBoolean.TYPE, JBoolean.TYPE)
        return method.invoke(sheet, anchor, bool(swipeback), not swipeback)

    def sheet_actions(self, sheet):
        return self.sheet_fields.get(sheet, "actions")

    def toggle_profile(self, sheet):
        self.sheet_method("toggleProfile").invoke(sheet)

    def close_player(self, layout):
        """The sheet's layout left the screen; when the sheet is dismissed, its player is done for good."""
        player = self.player
        if player is None or layout.hashCode() != player.layout_id or not player.sheet.isDismissed():
            return
        player.dispose()
        self.player = None

    def cover_extracted(self, path):
        """On the covers' thread: a cover read late is the playing song's one, so the open player redraws it.

        The player asks for the artwork once, when the song starts, and again only when a file finishes
        downloading, which never happens for a song that is already on the phone."""
        playing = jclass(MEDIA_CONTROLLER).getInstance().getPlayingMessageObject()
        if self.player is not None and local_path(playing) == path:
            run_on_ui_thread(lambda: self.refresh_cover(path))
        player = self.player
        if player is not None and player.queue_visible():
            screen = player.queue_screen
            run_on_ui_thread(lambda: screen.guarded(screen.cover_ready, path))

    @staticmethod
    def song_identity(message):
        """The same key the song menu uses: the file for a song from the phone, the message for a chat's."""
        if message is None:
            return None
        path = local_path(message)
        if path is not None:
            return ("path", path)
        return ("message", message.getDialogId(), message.getId())

    def song_started(self):
        """After MediaController.playMessage: when the song marked "stop after" is over, the next one waits."""
        controller = jclass(MEDIA_CONTROLLER).getInstance()
        playing = controller.getPlayingMessageObject()
        now = self.song_identity(playing)
        if self.stop_after is not None and self.last_song == self.stop_after and now != self.stop_after:
            self.stop_after = None
            run_on_ui_thread(lambda: controller.pauseMessage(controller.getPlayingMessageObject()))
        self.last_song = now

    def refresh_cover(self, path):
        player = self.player
        if player is None:
            return
        try:
            cover = self.sheet_fields.get(player.sheet, "coverView")
            message = cover.getMessageObject()
            if local_path(message) == path:
                cover.refreshCover()
        except Exception as e:
            self.report("refreshCover", e)

    def library_header(self, sheet):
        """The list the queue came from and "Track N of M" counted in that list, for a song from the library."""
        controller = jclass(MEDIA_CONTROLLER).getInstance()
        message = controller.getPlayingMessageObject()
        if local_path(message) is None:
            return
        self.sheet_fields.get(sheet, "headerTitle").setText(self.music.queue_title or "Медиатека")
        subtitle = self.sheet_fields.get(sheet, "headerSubtitle")
        playlist = controller.getPlaylist()
        index = playlist.indexOf(message)
        size = playlist.size()
        # the rest of a long queue is still being added: count the whole list from the start
        total = max(size, self.music.queue_total)
        if index < 0 or total <= 1:
            subtitle.setVisibility(8)
            return
        # the same count as Telegram's own header for a queue that is not a profile playlist
        if jclass("org.telegram.messenger.SharedConfig").playOrderReversed:
            position = total - size + index + 1
        else:
            position = size - index
        text = jclass("org.telegram.messenger.LocaleController").formatString(
            jclass("org.telegram.messenger.R$string").PlayerTrackOf, JInteger(position), JInteger(total))
        subtitle.setText(text)
        subtitle.setVisibility(0)

    def bulletin(self, sheet, animation, text):
        """A message at the player's own bottom edge, the way it reports saving a song."""
        context = _ctx()
        resource = context.getResources().getIdentifier(animation, "raw", context.getPackageName())
        self.sheet_method("bulletins").invoke(sheet).createSimpleBulletin(resource, text).show()

    def bulletin_undo(self, sheet, text, action):
        """A message with an "Undo" button, for what is easy to do by mistake."""
        context = _ctx()
        resource = context.getResources().getIdentifier("ic_delete", "raw", context.getPackageName())
        run = Run(action)
        factory = self.sheet_method("bulletins").invoke(sheet)
        # long enough to read and reach the button: the default short one is gone in under three seconds
        factory.createSimpleBulletin(resource, text, "Отменить", run).setDuration(5000).show()

    def cover_radius(self):
        index = self.get_setting("cover_radius", 1)
        return RADIUS_VALUES[index if 0 <= index < len(RADIUS_VALUES) else 1]

    def open_player(self, sheet, context):
        player = Player(self, sheet)
        player.build(context)
        self.player = player
        player.layout.requestLayout()

    def player_for(self, layout):
        player = self.player
        if player is None or layout.hashCode() != player.layout_id:
            return None
        if self.layout_fields.bool(layout, "landscape"):
            return None
        return player

    def show_volume(self):
        audio = _ctx().getSystemService("audio")
        audio.adjustStreamVolume(3, 0, 1)  # STREAM_MUSIC, ADJUST_SAME, FLAG_SHOW_UI

    def show_equalizer(self):
        ctx = _ctx()
        intent = jclass("android.content.Intent")("android.media.action.DISPLAY_AUDIO_EFFECT_CONTROL_PANEL")
        intent.putExtra("android.media.extra.PACKAGE_NAME", ctx.getPackageName())
        try:
            activity = jclass("org.telegram.ui.LaunchActivity").instance
            activity.startActivityForResult(intent, 0)
        except Exception:
            run_on_ui_thread(lambda: BulletinHelper.show_error("На этом телефоне нет системного эквалайзера"))

    def settings_changed(self):
        player = self.player
        if player is None:
            return
        player.visualizer.shader_key = None
        player.visualizer.settings = None
        player.apply_wave()
        player.layout.requestLayout()
        player.layout.invalidate()

    def _slider(self, item_id, labels, key, default):
        plugin = self

        class Chosen(dynamic_proxy(jclass("org.telegram.messenger.Utilities$Callback"))):
            def run(self, value):
                try:
                    plugin.set_setting(key, int(value))
                    plugin.settings_changed()
                except Exception as e:
                    plugin.report("slider", e)

        callback = Chosen()
        self.callbacks.append(callback)
        UItem = jclass("org.telegram.ui.Components.UItem")
        return UItem.asSlideView(item_id, jarray(jclass("java.lang.String"))(labels), self.get_setting(key, default), callback)

    def fill_settings(self, items):
        UItem = jclass("org.telegram.ui.Components.UItem")
        self.callbacks = []

        def check(item_id, text, subtext):
            return UItem.asCheck(item_id, text, subtext, True).setChecked(self.get_setting(CHECKS[item_id], True))

        for item in (
            UItem.asHeader("Визуализатор"),
            check(ID_VIS_TOP, "Над обложкой", "Столбики растут вверх от края обложки."),
            check(ID_VIS_BOTTOM, "Под обложкой", "Столбики растут вниз от края обложки."),
            UItem.asShadow(None),
            UItem.asHeader("Столбики"),
            self._slider(ID_VIS_STYLE, VIS_STYLES, "vis_style", 0),
            UItem.asShadow(None),
            UItem.asHeader("Высота столбиков"),
            self._slider(ID_VIS_HEIGHT, VIS_HEIGHTS, "vis_height", 1),
            UItem.asShadow(None),
            UItem.asHeader("Количество столбиков"),
            self._slider(ID_VIS_DENSITY, VIS_DENSITIES, "vis_density", 1),
            UItem.asShadow(None),
            UItem.asHeader("Цвет столбиков"),
            self._slider(ID_VIS_COLORS, VIS_COLORS, "vis_color_mode", 0),
            UItem.asShadow(None),
            UItem.asHeader("Скругление обложки"),
            self._slider(ID_COVER_RADIUS, RADIUS_LABELS, "cover_radius", 1),
            UItem.asShadow(None),
            UItem.asHeader("Прогресс"),
            check(ID_FLAT_SEEK, "Ровная линия", "Выключено: волна, как в обычном плеере exteraGram."),
            UItem.asShadow(None),
        ):
            items.add(item)

    def create_settings(self):
        return [
            Divider(text="Все настройки теперь в самом плеере: «⋮» → настройки плеера. "
                         "Пока плагин включён, в exteraGram работает новый плеер, даже если его переключатель выключен."),
        ]
