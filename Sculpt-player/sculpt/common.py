# Sculpt Player for exteraGram. Copyright 2026 BroNik (@BroZYTnikkkk).

import base64
import os
import re
import traceback

from android_utils import copy_to_clipboard
from java import jclass
from ui.bulletin import BulletinHelper


VERSION = "0.16.2"


SHEET = "com.exteragram.messenger.player.MusicPlayerSheet"
LAYOUT = SHEET + "$PlayerLayout"
COVER = "com.exteragram.messenger.player.ui.PlayerCoverView"
CONTROLS = "com.exteragram.messenger.player.ui.PlayerControlsView"
SEGMENT_DRAWABLE = "com.exteragram.messenger.player.ui.ExpressiveStateDrawable"
COLORS = "com.exteragram.messenger.player.PlayerColors"
CONFIG = "com.exteragram.messenger.ExteraConfig"
SETTINGS_SHEET = "com.exteragram.messenger.player.ui.PlayerSettingsSheet"
RHYTHM_TAP = "com.exteragram.messenger.player.rhythm.RhythmTap"
RHYTHM_ANALYZER = "com.exteragram.messenger.player.rhythm.RhythmAnalyzer"

RADIUS_LABELS = ["Нет", "8 dp", "16 dp", "28 dp"]
RADIUS_VALUES = [0.0, 8.0, 16.0, 28.0]

MARGIN = 24.0  # side gutters of the whole player
BUTTON = 40.0  # every button in the icon row and beside the transport
STEP = 48.0  # distance between buttons of the icon row, narrower when 7 of them do not fit
TIME_WIDTH = 48.0  # time labels beside the seek bar
TITLE_H = 28.0
ARTIST_OFFSET = 28.0
ALBUM_OFFSET = 54.0
ALBUM_H = 22.0
TEXT_BLOCK = ALBUM_OFFSET + ALBUM_H
TRANSPORT_H = 72.0  # PlayerControlsView.getHeightDp()
SEEK_H = 68.0  # WavySeekBar draws its line 52 dp from the top, the rest is room for the drag bubble
SEEK_LINE = 52.0
PANEL_H = 56.0
# the bottom panel, left to right; ⋮ is the player's own button and takes the last slot
PANEL_TABS = (
    ("Очередь", ("player_new_queue",)),
    ("Плеер", ("tab_music", "msg_filled_data_music", "msg_played")),
    ("Медиатека", ("msg_folders", "msg2_folder")),
    ("Плейлисты", ("files_music", "filled_widget_music")),
    ("Mornye", ("menu_download_round", "msg_download")),
)
PANEL_QUEUE = 0  # the player's own queue mode, moved here from the icon row
PANEL_ACTIVE = 1  # the player tab, which every opening of the player starts on
PANEL_LIBRARY = 2
PANEL_MORNYE = 4  # downloads, metadata and extensions from Mornye; search of one's own songs is in the library
PANEL_STACKS = (PANEL_LIBRARY, PANEL_MORNYE)  # tabs that are a stack of screens
MODE_PLAYER, MODE_LYRICS, MODE_QUEUE = 0, 1, 2  # MusicPlayerSheet.mode
QUEUES_MAX = 10  # queues kept at once; the oldest goes first
# The tabs lie over the player's own animated glow (RhythmBackground): the player's background color at this
# alpha (of 255) under them keeps their text readable and lets the glow and its rhythm show through.
TAB_SCRIM = 150
HEADER_H = 56.0  # the player's own header, same as PlayerLayout's

ID_VIS_TOP, ID_VIS_BOTTOM, ID_FLAT_SEEK = 9101, 9102, 9103
ID_VIS_STYLE, ID_VIS_HEIGHT, ID_VIS_DENSITY, ID_VIS_COLORS, ID_COVER_RADIUS = 9104, 9105, 9106, 9107, 9108
CHECKS = {ID_VIS_TOP: "vis_top", ID_VIS_BOTTOM: "vis_bottom", ID_FLAT_SEEK: "flat_seek"}
VIS_HEIGHTS = ["Низкий", "Средний", "Высокий"]
VIS_HEIGHT_DP = [40.0, 64.0, 88.0]
VIS_DENSITIES = ["Редкие", "Обычные", "Частые"]
VIS_BARS = [32, 48, 64]
VIS_COLORS = ["Три слоя", "Плавный", "Один цвет"]
VIS_MIN_CHROMA = 0.09  # below this a color reads as gray
VIS_MIN_HUE = 0.07  # hues closer than this (25 degrees) read as one color
VIS_DARKER = 0.22  # the back layer of a cover with a single color
VIS_HUE_BINS = 36  # 10 degrees each
VIS_FAR_BINS = 4  # the second color is at least this far in hue from the first
VIS_MIN_SHARE = 0.03  # of the whole cover: less than this is a detail, not a color of the cover
VIS_SAMPLE = 48  # the cover is read at this size
VIS_GRAY = -8355712  # 0xFF808080, what Score returns for a cover with no color
VIS_COVER_CHECK = 0.25  # seconds between checks that the cover on screen changed
VIS_PALE_LIGHT = 0.88  # the front layer goes halfway to this lightness
# Three bars laid over each other, front first. Each has its own length, so the colors keep walking inside a bar:
# bands shifted sideways, rise and fall per second, share of the height, wobble depth, its speed and phase per bar.
VIS_LAYERS = (
    (0.0, 28.0, 12.0, 0.8, 0.0, 0.0, 0.0),
    (2.0, 18.0, 6.0, 1.0, 0.35, 2.6, 0.55),
    (-2.0, 11.0, 4.0, 1.0, 0.35, 3.7, -0.8),
)
VIS_CORNER = 0.3  # corner radius as a share of the bar width: more than this turns narrow bars into capsules
VIS_BUILD_SECONDS = 0.024
BAR_RADIUS = 3.0  # corners of the square style
VIS_STYLES = ["Квадратные", "Скруглённые"]
VIS_WIDTHS = [0.62, 0.55]  # share of a bar's slot
BANDS = 24  # RhythmAnalyzer.bandLevel

MEDIA_CONTROLLER = "org.telegram.messenger.MediaController"
MESSAGE_OBJECT = "org.telegram.messenger.MessageObject"
PLAYER_COVERS = "com.exteragram.messenger.player.PlayerCovers"
UNKNOWN_ARTIST = "Неизвестный исполнитель"
# Android names a file with no album tag after its folder: these names say nothing about an album
GENERIC_FOLDERS = {"music", "download", "downloads", "audio", "telegram", "telegram audio", "0", "bluetooth", "recordings", "mornye"}
ARTIST_SEP = re.compile(r"\s*(?:,|;|&|\s/\s|\s\+\s|\s(?:feat\.?|ft\.?|featuring|vs\.?|x)\s)\s*", re.I)
SORT_MODES = (("title", "По названию"), ("artist", "По автору"), ("album", "По альбому"),
              ("added", "По дате добавления"), ("duration", "По длительности"))
NO_TRACK_NUMBER = 1 << 30
COVER_SIZE = 640  # px of a cached cover
TILE_SIZE = 112  # dp of a cover in a row that scrolls sideways
TILE_RADIUS = 12
PREVIEW_MAX = 20  # covers in such a row
THUMB_AREA = 28  # dp the slider at the list's edge catches a finger in
THUMB_H = 48
THUMB_MIN_ROWS = 30  # a shorter list has no need for a slider
GROUP_COVER_TRIES = 8  # songs of a group looked at for its picture
HISTORY_MAX = 100
QUEUE_MAX = 5000
# MessageObject's own constructor costs about 2 ms a song: the first ones start the music, the rest follow in parts
QUEUE_HEAD = 30
QUEUE_CHUNK = 200
LISTEN_SECONDS = 30.0
LISTEN_TICK_MS = 5000
COLORS_SECONDS = 0.15
COVERS_DELIVERY_MS = 120
PERMISSION_REQUEST = 4731
PERMISSION_POLLS = 240  # half-second looks at whether the answer came


def _log(text):
    try:
        jclass("android.util.Log").i("SculptPlayer", str(text))
    except Exception:
        pass


def _show_error(msg, exc):
    trace = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    _log(msg + "\n" + trace)
    try:
        BulletinHelper.show_with_button(
            msg,
            jclass("org.telegram.messenger.R").raw.error,
            "Copy",
            on_click=lambda: copy_to_clipboard(trace),
        )
    except Exception:
        pass


def _ctx():
    return jclass("org.telegram.messenger.ApplicationLoader").applicationContext


def _java_class(name):
    return jclass("java.lang.Class").forName(name, True, _ctx().getClassLoader())


PLUGIN_ID = "sculpt_player"
DEX_ASSET = "sculpt.dex"
_dex = {"loader": None, "failed": False, "methods": {}}


def _asset_paths(name):
    """Where the Elyx asset API says a file is, then the folder the plugin is unpacked to."""
    paths = []
    try:
        from elyx import assets
        for key in (name.rsplit(".", 1)[0], name):
            try:
                asset = assets[key]
            except Exception:
                asset = getattr(assets, key, None)
            if asset is None:
                continue
            for attr in ("path_str", "path", "file"):
                try:
                    value = getattr(asset, attr, None)
                    value = value() if callable(value) else value
                    if value:
                        paths.append(str(value))
                except Exception:
                    pass
    except Exception as e:
        _log("elyx assets: %s" % e)
    try:
        files = str(_ctx().getFilesDir().getAbsolutePath())
        paths.append(os.path.join(files, "plugins", "ElyxPlugins", PLUGIN_ID, "assets", name))
    except Exception:
        pass
    return paths


def _dex_loader():
    for path in _asset_paths(DEX_ASSET):
        if os.path.isfile(path):
            with open(path, "rb") as f:
                data = f.read()
            # some asset pipelines keep text only, so the DEX may arrive base64 encoded
            if data[:4] != b"dex\n":
                data = base64.b64decode(data)
            buffer = jclass("java.nio.ByteBuffer").wrap(data)
            return jclass("dalvik.system.InMemoryDexClassLoader")(buffer, _ctx().getClassLoader())
    raise RuntimeError("%s not found" % DEX_ASSET)


def sculpt_method(class_name, name):
    """A static method of this plugin's own Java code in assets/sculpt.dex.

    None when the DEX cannot be loaded: every caller keeps its Python way, so a broken asset slows the
    plugin down instead of breaking it.
    """
    key = (class_name, name)
    method = _dex["methods"].get(key)
    if method is not None or _dex["failed"]:
        return method
    try:
        if _dex["loader"] is None:
            _dex["loader"] = _dex_loader()
        for candidate in _dex["loader"].loadClass(class_name).getMethods():
            if candidate.getName() == name:
                _dex["methods"][key] = method = candidate
                return method
        raise RuntimeError("%s.%s not found" % (class_name, name))
    except Exception as e:
        _dex["failed"] = True
        _log("sculpt.dex: %s" % e)
        return None


def sculpt_class(class_name):
    """A class of this plugin's own Java code, or None when the DEX cannot be loaded."""
    if _dex["failed"]:
        return None
    try:
        if _dex["loader"] is None:
            _dex["loader"] = _dex_loader()
        return _dex["loader"].loadClass(class_name)
    except Exception as e:
        _dex["failed"] = True
        _log("sculpt.dex: %s" % e)
        return None


def _dp(value):
    return int(jclass("org.telegram.messenger.AndroidUtilities").dp(float(value)))


def tab_scrim(colors):
    """The background of a tab: the player's own color, see-through enough for the glow under it."""
    return jclass("androidx.core.graphics.ColorUtils").setAlphaComponent(colors.background, TAB_SCRIM)


class Fields:
    """Cached java.lang.reflect.Field access: these hooks run on every layout pass."""

    def __init__(self, name):
        self.cls = _java_class(name)
        self.cache = {}

    def field(self, name):
        f = self.cache.get(name)
        if f is None:
            f = self.cls.getDeclaredField(name)
            f.setAccessible(True)
            self.cache[name] = f
        return f

    def get(self, obj, name):
        return self.field(name).get(obj)

    def int(self, obj, name):
        return self.field(name).getInt(obj)

    def float(self, obj, name):
        return self.field(name).getFloat(obj)

    def bool(self, obj, name):
        return self.field(name).getBoolean(obj)

    def set_int(self, obj, name, value):
        self.field(name).setInt(obj, int(value))

    def set_float(self, obj, name, value):
        self.field(name).setFloat(obj, float(value))
