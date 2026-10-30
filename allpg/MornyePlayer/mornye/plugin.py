# SPDX-License-Identifier: LGPL-3.0-only
# Mornye Player for exteraGram. Copyright 2026 BroNik (@BroZYTnikkkk).
# Based on Mornye by zarzet (https://github.com/mornyeapp/Mornye), LGPL-3.0-only.

"""The plugin class."""

import json
import os
import threading
from base_plugin import BasePlugin, MenuItemData, MenuItemType
from client_utils import run_on_queue
from ui.bulletin import BulletinHelper
from ui.settings import Divider, Header, Input, Selector, Switch, Text
from android.os import Handler, Looper
from android_utils import R, run_on_ui_thread
from .logs import log
from java.lang import Boolean as JBoolean, Float as JFloat
from .common import (
    EFFECT_AUTO,
    EFFECT_LABELS,
    EQ_CENTERS,
    EQ_PRESET_LABELS,
    MIX_CROSSFADE,
    MIX_DURATION_LABELS,
    PREAMP_LABELS,
    SKIP_FADE_LABELS,
    STRENGTH_LABELS,
)
from .automix import java_class
from .audio import (
    Engine,
    PauseHook,
    PlayMessageHook,
    PlayerAlertHook,
    SkipHook,
    VolumeHook,
)
from .library import Library, scan_file
from .classic_ui import UI
from .ext_runtime import CallContext
from .ext_manager import ExtensionManager
from .downloads import DownloadQueue
from .app import AppServer
from .modules import (
    AUTHOR_URL,
    COVER_TINTS,
    MD3_ANIMS,
    MD3_COLORS,
    RESUME_POSITIONS,
    RESUME_SHAPES,
    RESUME_STARTUP,
    SOURCE_URL,
    Modules,
)
from .glue import (
    _GrantUrlHook,
    _VERIFY,
    _ValueCallback,
    _Verification,
    fullscreen_webview,
)


# ---------------------------------------------------------------------------
# Plugin
# ---------------------------------------------------------------------------


class MornyePlayerPlugin(BasePlugin):
    def on_plugin_load(self):
        self.gains = {}
        self.library = Library(self)
        self.engine = Engine(self)
        self.ui = UI(self)
        self._ext_lock = threading.RLock()
        self._extensions = None
        self._downloads = None
        self._app = None
        self._app_dialog = None
        self._grant_hooked = False
        self._install_hooks()
        self.add_menu_item(MenuItemData(
            menu_type=MenuItemType.DRAWER_MENU,
            text="Mornye Player",
            icon="msg_played",
            on_click=lambda ctx: self.open_app(),
        ))
        self.add_menu_item(MenuItemData(
            menu_type=MenuItemType.MESSAGE_CONTEXT_MENU,
            text="Mornye: в библиотеку",
            icon="msg_download",
            on_click=self._on_message_save,
        ))
        if self.get_setting("scan_on_start", True):
            self.library.scan()
        self.engine.on_track_started()
        self.modules = Modules(self)
        try:
            self.modules.start()
        except Exception as e:
            log("[Mornye] modules: %s" % e)

    def on_plugin_unload(self):
        try:
            self.engine.stop()
        except Exception:
            pass
        try:
            self.modules.stop()
        except Exception:
            pass
        dialog = self._app_dialog
        if dialog is not None:
            run_on_ui_thread(lambda: dialog.dismiss())
        if self._app is not None:
            self._app.close()
        if self._extensions is not None:
            self._extensions.close()

    # -- Mornye extensions, downloads and the app window

    def extensions(self):
        with self._ext_lock:
            if self._extensions is None:
                self._extensions = ExtensionManager(os.path.join(self.library.dir, "extensions"))
            return self._extensions

    def downloads(self):
        with self._ext_lock:
            if self._downloads is None:
                self._downloads = DownloadQueue(self.extensions(), self.library.download_dir, on_done=self._download_done)
            return self._downloads

    def _download_done(self, item, result):
        if not result.get("success"):
            return
        path = result["file_path"]
        scan_file(path)
        track = self.library.add_file(path)
        if item.get("play") and track is not None:
            run_on_ui_thread(lambda: self.library.play([track], 0))
        if self._app_dialog is None:
            title = item.get("title") or os.path.basename(path)
            run_on_ui_thread(lambda: BulletinHelper.show_success("Mornye: скачано «%s»" % title))

    def open_app(self):
        act = self.ui.activity()
        if act is None:
            BulletinHelper.show_error("Mornye: нет активного экрана")
            return
        if self._app_dialog is not None:
            return
        if self._app is None:
            self._app = AppServer(self)

        def on_back(view, dialog):
            def answer(value):
                if value != "true":
                    run_on_ui_thread(lambda: dialog.dismiss())
            view.evaluateJavascript("window.mornyeBack ? window.mornyeBack() : false", _ValueCallback(answer))

        def closed():
            self._app_dialog = None

        try:
            self._app_dialog, _ = fullscreen_webview(act, self._app.url(), on_back, closed)
        except Exception as e:
            log("[Mornye] app window: %s" % e)
            BulletinHelper.show_error("Mornye: не удалось открыть плеер: %s" % e)

    def verify_extension(self, ext):
        def work():
            m = self.extensions()
            pending = m.pending_verification(ext)
            if pending is None:
                try:
                    m.preflight(ext, CallContext(), download_only=False)
                except Exception as e:
                    err = str(e)
                    run_on_ui_thread(lambda: BulletinHelper.show_error("Mornye: %s" % err))
                    return
                pending = m.pending_verification(ext)
            if pending is None or not pending.get("auth_url"):
                run_on_ui_thread(lambda: BulletinHelper.show_info("Mornye: проверка для %s не нужна" % ext))
                return
            run_on_ui_thread(lambda: self._show_verification(ext, pending))
        run_on_queue(work)

    def _show_verification(self, ext, pending):
        if not self._grant_hooked:
            try:
                client = java_class("android.webkit.WebViewClient")
                web_view = java_class("android.webkit.WebView")
                for arg in (java_class("android.webkit.WebResourceRequest"), java_class("java.lang.String")):
                    self.hook_method(client.getDeclaredMethod("shouldOverrideUrlLoading", web_view, arg), _GrantUrlHook())
                self._grant_hooked = True
            except Exception as e:
                log("[Mornye] grant hook: %s" % e)
        act = self.ui.activity()
        if act is None:
            return
        check = _Verification(self, ext, pending)
        _VERIFY["active"] = check

        def closed():
            if _VERIFY.get("active") is check:
                _VERIFY["active"] = None

        check.dialog, view = fullscreen_webview(act, pending["auth_url"], None, closed)
        handler = Handler(Looper.getMainLooper())

        def tick():
            if check.done or _VERIFY.get("active") is not check:
                return
            try:
                url = view.getUrl()
                if url is not None and check.offer(str(url)):
                    return
            except Exception:
                pass
            handler.postDelayed(R(tick), 400)

        handler.postDelayed(R(tick), 400)

    def _install_hooks(self):
        mc_cls = java_class("org.telegram.messenger.MediaController")
        vp_cls = java_class("org.telegram.ui.Components.VideoPlayer")
        mo_cls = java_class("org.telegram.messenger.MessageObject")
        try:
            m = vp_cls.getDeclaredMethod("setVolume", JFloat.TYPE)
            self.hook_method(m, VolumeHook(self))
        except Exception as e:
            log("[Mornye] setVolume hook: %s" % e)
        try:
            m = mc_cls.getDeclaredMethod("playMessage", mo_cls, JBoolean.TYPE)
            self.hook_method(m, PlayMessageHook(self))
        except Exception as e:
            log("[Mornye] playMessage hook: %s; have %s" % (e, [str(x) for x in mc_cls.getDeclaredMethods() if x.getName() == "playMessage"]))
        try:
            self.hook_method(mc_cls.getDeclaredMethod("pauseMessage", mo_cls), PauseHook(self))
        except Exception as e:
            log("[Mornye] pauseMessage hook: %s" % e)
        for name, previous in (("playNextMessage", False), ("playPreviousMessage", True)):
            try:
                self.hook_method(mc_cls.getDeclaredMethod(name), SkipHook(self, previous))
            except Exception as e:
                log("[Mornye] %s hook: %s" % (name, e))
        try:
            alert_cls = java_class("org.telegram.ui.Components.AudioPlayerAlert")
            if alert_cls is not None:
                self.hook_all_constructors(alert_cls, PlayerAlertHook(self))
        except Exception as e:
            log("[Mornye] player alert hook: %s" % e)

    def custom_eq(self):
        try:
            gains = json.loads(self.get_setting("eq_custom", "") or "[]")
            if len(gains) == len(EQ_CENTERS):
                return [float(g) for g in gains]
        except Exception:
            pass
        return [0.0] * len(EQ_CENTERS)

    def _on_message_save(self, context):
        msg = context.get("message")
        doc = msg.getDocument() if msg is not None else None
        is_audio = doc is not None and not msg.isVoice() and (
            msg.isMusic() or str(doc.mime_type or "").startswith("audio/"))
        if not is_audio:
            BulletinHelper.show_info("Mornye: это не аудиофайл")
            return
        self.library.save_message(msg)

    def _fx_changed(self, *_):
        run_on_ui_thread(lambda: self.engine.reapply_fx())

    def create_settings(self):
        return [
            Header(text="Переходы между треками"),
            Selector(key="mix_mode", text="Режим", default=MIX_CROSSFADE, items=["Выключено", "Кроссфейд", "AutoMix"], icon="msg_switch"),
            Selector(key="mix_duration", text="Длительность перехода", default=0, items=MIX_DURATION_LABELS, icon="msg_timer"),
            Selector(key="automix_effect", text="Эффект AutoMix", default=EFFECT_AUTO, items=EFFECT_LABELS, icon="msg_photo_settings"),
            Selector(key="automix_pitch", text="Сдвиг тона для эффекта", default=2,
                     items=["-6", "-5", "-4", "-3", "-2", "-1", "0", "+1", "+2", "+3", "+4", "+5", "+6"]),
            Input(key="pause_fade_s", text="Затухание при паузе и старте, сек", default="0.4", subtext="0 выключает, до 5 с", icon="msg_round_pause"),
            Selector(key="skip_fade", text="Плавное переключение вручную", default=0, items=SKIP_FADE_LABELS, icon="msg_forward"),
            Divider(text="AutoMix ищет биты в концовке и начале треков, подгоняет темп и сводит их на сильную долю. Работает для скачанных и локальных треков; иначе обычный кроссфейд."),
            Header(text="Звук"),
            Switch(key="normalize", text="Нормализация громкости (ReplayGain)", default=True, icon="msg_volume"),
            Selector(key="rg_preamp", text="Предусиление ReplayGain", default=4, items=PREAMP_LABELS),
            Switch(key="rg_album", text="Предпочитать альбомное усиление", default=False),
            Switch(key="eq_enabled", text="Эквалайзер", default=False, on_change=self._fx_changed, icon="msg_settings"),
            Selector(key="eq_preset", text="Пресет", default=0, items=EQ_PRESET_LABELS, on_change=self._fx_changed),
            Selector(key="eq_bass", text="Бас", default=4, items=["-8", "-6", "-4", "-2", "0", "+2", "+4", "+6", "+8"], on_change=self._fx_changed),
            Selector(key="eq_treble", text="Верха", default=4, items=["-8", "-6", "-4", "-2", "0", "+2", "+4", "+6", "+8"], on_change=self._fx_changed),
            Selector(key="bass_boost", text="Bass Boost", default=0, items=STRENGTH_LABELS, on_change=self._fx_changed),
            Selector(key="virtualizer", text="Объёмный звук", default=0, items=STRENGTH_LABELS, on_change=self._fx_changed),
            Selector(key="loudness_boost", text="Усиление громкости", default=0, items=["Выкл", "+3 дБ", "+6 дБ", "+9 дБ"], on_change=self._fx_changed),
            Switch(key="skip_silence", text="Пропускать тишину", default=False),
            Text(text="Открыть эквалайзер", icon="msg_settings", on_click=lambda v: self.ui.open_equalizer()),
            Header(text="Библиотека"),
            Switch(key="use_mediastore", text="Вся музыка устройства", default=True, subtext="Через медиатеку Android", icon="msg_media"),
            Input(key="folders", text="Дополнительные папки", default="", subtext="Через точку с запятой", icon="msg_folder"),
            Input(key="download_dir", text="Папка для скачивания", default="", subtext="По умолчанию Music/Mornye", icon="msg_download"),
            Switch(key="scan_on_start", text="Сканировать при запуске", default=True),
            Switch(key="autoplay", text="Автоплей из библиотеки", default=True, subtext="Когда очередь закончилась, подбирает похожие треки"),
            *self._module_settings(),
            Header(text="Mornye"),
            Text(text="Открыть плеер Mornye", icon="msg_played", accent=True, on_click=lambda v: self.open_app()),
            Text(text="Меню Mornye (классическое)", icon="msg_list", on_click=lambda v: self.ui.open_main()),
            Text(text="Пересканировать библиотеку", icon="msg_retry", on_click=lambda v: self.library.scan(
                lambda n: BulletinHelper.show_success("Найдено треков: %d" % n))),
            Divider(text="Плеер Mornye открывается из бокового меню и долгим нажатием на «⋮» в плеере Telegram. Поиск и скачивание идут через расширения Mornye: установите их в плеере, раздел «Ещё» → «Каталог расширений»."),
            Header(text="Авторство"),
            Text(text="Mornye by zarzet (LGPL-3.0)", icon="msg_info",
                 on_click=lambda v: self._open_url("https://github.com/mornyeapp/Mornye")),
            Divider(text="Плагин переносит идеи и алгоритмы Mornye (AutoMix, эквалайзер, нормализация, расширения и планировщик загрузок) в exteraGram и распространяется под LGPL-3.0. Расширения написаны их авторами, лицензии лежат в их пакетах."),
        ]

    def _module_settings(self):
        mods = self.modules
        push = {key: (lambda key: lambda *_: mods.push(key))(key) for key in ("md3", "resume", "cover")}
        on = {key: mods[key].wanted() for key in ("md3", "resume", "cover")}

        def toggle(key):
            return lambda value: mods.toggle(key, value)

        def note(key):
            return "Включён отдельный плагин, встроенный не запускается" if mods[key].blocked else None

        items = [
            Header(text="Плеер Telegram"),
            Switch(key="mod_md3", text="Material Player", default=True, icon="player", on_change=toggle("md3"),
                   subtext=note("md3") or "Плеер и мини-плеер в стиле Material Expressive"),
        ]
        if on["md3"]:
            items += [
                Switch(key="md3_dialogs", text="Мини-плеер на главной", default=True, on_change=push["md3"],
                       subtext="Перетаскиваемый плеер в списке чатов"),
                Switch(key="md3_context_bar", text="Панель в чате", default=True, on_change=push["md3"],
                       subtext="Компактный плеер сверху в переписке"),
                Selector(key="md3_color", text="Цвета", default=0, items=MD3_COLORS, on_change=push["md3"], icon="msg_palette"),
                Switch(key="md3_wavy", text="Волнистый прогресс", default=True, on_change=push["md3"]),
                Switch(key="md3_dot", text="Точка на конце прогресса", default=True, on_change=push["md3"]),
                Selector(key="md3_anim", text="Анимация", default=0, items=MD3_ANIMS, on_change=push["md3"], icon="msg_customize"),
            ]
        items.append(Switch(key="mod_resume", text="Player Resume", default=True, icon="msg_calls_minimize",
                            on_change=toggle("resume"),
                            subtext=note("resume") or "Сворачивает плеер в кнопку и возвращает его после перезапуска"))
        if on["resume"]:
            items += [
                Switch(key="pr_minimize", text="Сворачивать в кнопку", default=True, on_change=push["resume"],
                       subtext="Прятать плеер у FAB при закрытии"),
                Selector(key="pr_position", text="Положение кнопки", default=0, items=RESUME_POSITIONS, on_change=push["resume"]),
                Selector(key="pr_shape", text="Форма кнопки", default=0, items=RESUME_SHAPES, on_change=push["resume"]),
                Switch(key="pr_restore_paused", text="Возвращать на паузе", default=True, on_change=push["resume"],
                       subtext="Не запускать звук автоматически"),
                Selector(key="pr_startup", text="При запуске", default=0, items=RESUME_STARTUP, on_change=push["resume"]),
                Switch(key="pr_protect", text="Защита плейлиста", default=False, on_change=push["resume"],
                       subtext="Возвращать прошлый плейлист после короткого прослушивания"),
            ]
        items.append(Switch(key="mod_cover", text="Cover Theme", default=False, icon="msg_palette",
                            on_change=toggle("cover"),
                            subtext=note("cover") or "Красит тему в цвета обложки играющего трека"))
        if on["cover"]:
            items += [
                Selector(key="ct_strength", text="Оттенок", default=0, items=COVER_TINTS, on_change=push["cover"]),
                Switch(key="ct_reset_on_pause", text="Сброс на паузе", default=False, on_change=push["cover"],
                       subtext="Обычные цвета, пока трек на паузе"),
            ]
        items += [
            Text(text="Модули от @RnPlugins", icon="msg_openprofile", on_click=lambda v: self._rooni_author()),
            Text(text="Исходный код модулей", icon="msg_link", on_click=lambda v: self._open_url(SOURCE_URL)),
            Divider(text="Material Player, Player Resume и Cover Theme написаны @RnPlugins (YouRooni) и встроены без изменений. "
                         "Если у вас стоят их отдельные плагины, встроенные копии не запускаются, чтобы не было двойных хуков. "
                         "Изменения применяются сразу, переключение модуля может потребовать перезапуска."),
        ]
        return items

    def _rooni_author(self):
        for key in ("md3", "resume", "cover"):
            if self.modules[key].show_author():
                return
        self._open_url(AUTHOR_URL)

    def _open_url(self, url):
        try:
            from org.telegram.messenger.browser import Browser
            act = self.ui.activity()
            Browser.openUrl(act, url)
        except Exception:
            pass
