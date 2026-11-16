# SPDX-License-Identifier: LGPL-3.0-only
# Mornye Player for exteraGram. Copyright 2026 BroNik (@BroZYTnikkkk).
# Based on Mornye by zarzet (https://github.com/mornyeapp/Mornye), LGPL-3.0-only.

"""Player modules by @RnPlugins (YouRooni), shipped as their original DEX in assets/.

Material Player restyles the Telegram player and the mini player, Player Resume folds the player into a
button and brings it back after a restart, Cover Theme tints the app with the cover colors. Each one
keeps its own SharedPreferences, which these wrappers fill from Mornye Player's settings. When the
standalone plugin is installed and enabled, the built-in copy stays off so the hooks don't run twice.
"""

import base64

from .logs import log
from .resources import _elyx_paths, _plugin_dirs

AUTHOR_URL = "https://t.me/RnPlugins"
SOURCE_URL = "https://github.com/YouRooni/plugins"

# key: (asset, class, standalone plugin id, prefs, enabled by default)
SPECS = {
    "md3": ("md3_player.dex", "dev.rooni.player.PlayerHook", "md3_player", "md3_player_prefs", True),
    "resume": ("player_resume.dex", "dev.rooni.playerresume.PlayerResume", "player_resume", "player_resume_prefs", True),
    "cover": ("cover_theme.dex", "dev.rooni.covertheme.CoverTheme", "cover_theme", "cover_theme_prefs", False),
}
NAMES = {"md3": "Material Player", "resume": "Player Resume", "cover": "Cover Theme"}

RESUME_POSITIONS = ["Слева", "Сверху"]
RESUME_SHAPES = ["Квадрат", "Круг"]
RESUME_STARTUP = ["Сохранять", "Открывать плеер", "Сворачивать в кнопку"]
COVER_TINTS = ["Лёгкий", "Заметный", "Сильный"]
MD3_COLORS = ["Обложка трека", "Тема Telegram"]
MD3_ANIMS = ["Морфинг", "Скольжение"]


def _ctx():
    from org.telegram.messenger import ApplicationLoader
    return ApplicationLoader.applicationContext


def _dex_bytes(name):
    import os
    for path in _elyx_paths(name) + [os.path.join(d, "assets", name) for d in _plugin_dirs()]:
        if os.path.isfile(path):
            with open(path, "rb") as f:
                data = f.read()
            # some asset pipelines keep text only, so a .dex may arrive base64 encoded
            return data if data[:4] == b"dex\n" else base64.b64decode(data)
    raise RuntimeError("asset %s not found" % name)


def standalone_active(plugin_id):
    """True when the original plugin is installed and enabled in exteraGram."""
    try:
        from com.exteragram.messenger.plugins import PluginsController
        if PluginsController.getInstance().getPluginEngine(plugin_id) is None:
            return False
        prefs = _ctx().getSharedPreferences("plugin_settings", 0)
        return bool(prefs.getBoolean("plugin_enabled_" + plugin_id, True))
    except Exception:
        return False


def _int(value, default=0, labels=None):
    try:
        if hasattr(value, "intValue"):
            return int(value.intValue())
        if labels and str(value) in labels:
            return labels.index(str(value))
        return int(value)
    except Exception:
        return default


class Module:
    def __init__(self, plugin, key):
        self.plugin = plugin
        self.key = key
        self.asset, self.class_name, self.plugin_id, self.prefs_name, self.default_on = SPECS[key]
        self.loader = None
        self.cls = None
        self.author_cls = None
        self.blocked = False

    def wanted(self):
        return bool(self.plugin.get_setting("mod_" + self.key, self.default_on))

    def running(self):
        return self.cls is not None

    def call(self, name, *args):
        if self.cls is None:
            return None
        for m in self.cls.getMethods():
            if m.getName() == name and len(m.getParameterTypes()) == len(args):
                return m.invoke(None, *args)
        return None

    def start(self):
        from android_utils import run_on_ui_thread
        run_on_ui_thread(self._start)

    def _start(self):
        if self.cls is not None or not self.wanted():
            return
        self.blocked = standalone_active(self.plugin_id)
        if self.blocked:
            log("[Mornye] %s: standalone plugin is on, built-in copy stays off" % NAMES[self.key])
            return
        try:
            from java.nio import ByteBuffer
            from dalvik.system import InMemoryDexClassLoader
            self.loader = InMemoryDexClassLoader(ByteBuffer.wrap(_dex_bytes(self.asset)), _ctx().getClassLoader())
            self.cls = self.loader.loadClass(self.class_name)
            try:
                self.author_cls = self.loader.loadClass("dev.rooni.author.AuthorBottomSheet")
            except Exception:
                self.author_cls = None
            self.push()
            self.call("start")
            self.push()
            log("[Mornye] %s started" % NAMES[self.key])
        except Exception as e:
            log("[Mornye] %s failed: %s" % (NAMES[self.key], e))
            self.cls = None
            self.loader = None

    def stop(self):
        from android_utils import run_on_ui_thread
        run_on_ui_thread(self._stop)

    def _stop(self):
        if self.cls is None:
            return
        try:
            if self.author_cls is not None:
                try:
                    self.author_cls.getMethod("dismissCurrent").invoke(None)
                except Exception:
                    pass
            self.call("stop")
        except Exception as e:
            log("[Mornye] %s stop: %s" % (NAMES[self.key], e))
        self.cls = self.author_cls = self.loader = None

    def show_author(self):
        if self.author_cls is not None:
            try:
                self.author_cls.getMethod("showFromCurrentActivity").invoke(None)
                return True
            except Exception:
                pass
        return False

    def _prefs(self):
        return _ctx().getSharedPreferences(self.prefs_name, 0).edit()

    def push(self):
        """Copy our settings into the module's prefs and its static setters."""
        s = self.plugin.get_setting
        try:
            if self.key == "resume":
                vals = dict(restore_paused=bool(s("pr_restore_paused", True)), minimize_on_close=bool(s("pr_minimize", True)),
                            startup_mode=_int(s("pr_startup", 0), 0, RESUME_STARTUP), playlist_protection=bool(s("pr_protect", False)),
                            protection_timeout=_int(s("pr_timeout", 29), 29), pill_position=_int(s("pr_position", 0), 0, RESUME_POSITIONS),
                            pill_shape=_int(s("pr_shape", 0), 0, RESUME_SHAPES))
                ed = self._prefs()
                for k, v in vals.items():
                    ed.putBoolean(k, v) if isinstance(v, bool) else ed.putInt(k, v)
                ed.apply()
                if self.cls is not None:
                    from java.lang import Boolean, Integer
                    self.call("updateSettings", Boolean(vals["restore_paused"]), Boolean(vals["minimize_on_close"]),
                              Integer(vals["startup_mode"]), Boolean(vals["playlist_protection"]),
                              Integer(vals["protection_timeout"]), Integer(vals["pill_position"]), Integer(vals["pill_shape"]))
            elif self.key == "cover":
                self._prefs().putInt("strength", _int(s("ct_strength", 0), 0, COVER_TINTS)) \
                    .putBoolean("reset_on_pause", bool(s("ct_reset_on_pause", False))).apply()
            elif self.key == "md3":
                mini, bar = bool(s("md3_dialogs", True)), bool(s("md3_context_bar", True))
                color = "theme" if _int(s("md3_color", 0), 0, MD3_COLORS) == 1 else "cover"
                wavy, dot = bool(s("md3_wavy", True)), bool(s("md3_dot", True))
                anim = _int(s("md3_anim", 0), 0, MD3_ANIMS)
                self._prefs().remove("anim_style").putBoolean("mini_player_dialogs", mini).putBoolean("context_bar_enabled", bar) \
                    .putString("color_source", color).putBoolean("online_lyrics", True).putBoolean("wavy_seekbar", wavy) \
                    .putBoolean("seekbar_dot", dot).putInt("anim_style", anim).apply()
                if self.cls is not None:
                    from java.lang import Boolean, Integer, String
                    setters = {"setAnimStyle": Integer(anim), "setSeekBarDot": Boolean(dot), "setWavySeekBar": Boolean(wavy),
                               "setColorSource": String(color), "setMiniPlayerDialogs": Boolean(mini), "setContextBar": Boolean(bar)}
                    for m in self.cls.getMethods():
                        if m.getName() in setters and len(m.getParameterTypes()) == 1:
                            try:
                                m.invoke(None, setters[m.getName()])
                            except Exception as e:
                                log("[Mornye] md3 %s: %s" % (m.getName(), e))
        except Exception as e:
            log("[Mornye] %s settings: %s" % (NAMES[self.key], e))


class Modules:
    def __init__(self, plugin):
        self.items = {key: Module(plugin, key) for key in SPECS}

    def __getitem__(self, key):
        return self.items[key]

    def start(self):
        for m in self.items.values():
            m.start()

    def stop(self):
        for m in self.items.values():
            m.stop()

    def toggle(self, key, value):
        self.items[key].plugin.set_setting("mod_" + key, bool(value), reload_settings=True)
        m = self.items[key]
        if value:
            m.start()
        else:
            m.stop()

    def push(self, key):
        self.items[key].push()

    def status(self):
        return {key: {"name": NAMES[key], "on": m.wanted(), "running": m.running(), "blocked": m.blocked}
                for key, m in self.items.items()}
