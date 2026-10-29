# SPDX-License-Identifier: LGPL-3.0-only
# Mornye Player for exteraGram. Copyright 2026 BroNik (@BroZYTnikkkk).
# Based on Mornye by zarzet (https://github.com/mornyeapp/Mornye), LGPL-3.0-only.

"""Shared imports, constants and small helpers. Other modules import from here."""

# ruff: noqa: F401



import base64
import calendar
import collections
import email.utils
import hashlib
import hmac
import ipaddress
import itertools
import json
import math
import os
import queue
import random
import re
import secrets
import shutil
import tempfile
import threading
import time
import unicodedata
from array import array
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, unquote, unquote_plus, urljoin, urlsplit, urlunsplit

import requests

from android_utils import R, OnClickListener, OnLongClickListener, run_on_ui_thread
from .logs import log
from base_plugin import BasePlugin, MenuItemData, MenuItemType, MethodHook
from client_utils import (
    get_last_fragment,
    get_media_controller,
    run_on_queue,
)
from file_utils import get_files_dir
from hook_utils import get_private_field, set_private_field
from ui.alert import AlertDialogBuilder
from ui.bulletin import BulletinHelper
from ui.settings import Divider, Header, Input, Selector, Switch, Text

from java import dynamic_proxy, jarray, jbyte, jclass, jfloat
from java.lang import Boolean as JBoolean
from java.lang import Float as JFloat
from java.lang import String as JString
from java.lang import System as JSystem

from android.os import Build, Environment, Handler, Looper
from android.text import TextWatcher
from android.util import TypedValue
from android.widget import EditText, LinearLayout, ScrollView, SeekBar, TextView

from org.telegram.messenger import (
    AndroidUtilities,
    ApplicationLoader,
    FileLoader,
    MessageObject,
    SharedConfig,
    UserConfig,
)
from org.telegram.tgnet import TLRPC
from org.telegram.ui.ActionBar import Theme
from org.telegram.ui.Components import LayoutHelper

try:
    import mutagen
except Exception:
    mutagen = None


AUDIO_EXTS = (".mp3", ".m4a", ".aac", ".flac", ".ogg", ".oga", ".opus", ".wav", ".alac", ".wma", ".mka")
USER_AGENT = "MornyePlayerPlugin/1.0 (exteraGram; https://github.com/mornyeapp/Mornye)"

MIX_OFF, MIX_CROSSFADE, MIX_AUTOMIX = 0, 1, 2
MIX_DURATIONS = [0, 3, 5, 8, 10, 12, 15]
MIX_DURATION_LABELS = ["Авто", "3 с", "5 с", "8 с", "10 с", "12 с", "15 с"]
EFFECT_AUTO, EFFECT_CROSSFADE, EFFECT_MUFFLED, EFFECT_ECHO, EFFECT_PITCH = range(5)
EFFECT_LABELS = ["Авто", "Кроссфейд", "Приглушение", "Эхо", "Сдвиг тона"]
SKIP_FADES = [0, 0.8, 1.5, 3.0]
SKIP_FADE_LABELS = ["Выкл", "0,8 с", "1,5 с", "3 с"]

EQ_CENTERS = [31.25, 62.5, 125, 250, 500, 1000, 2000, 4000, 8000, 16000]
EQ_PRESETS = [
    ("Flat", [0, 0, 0, 0, 0, 0, 0, 0, 0, 0]),
    ("Bass boost", [6, 5, 3, 1, 0, 0, 0, 0, 0, 0]),
    ("Treble boost", [0, 0, 0, 0, 0, 1, 2, 3, 4, 5]),
    ("Vocal", [-2, -2, -1, 0, 2, 3, 3, 2, 0, -1]),
    ("Rock", [4, 3, 1, -1, -2, 0, 2, 3, 4, 4]),
    ("Pop", [-1, 1, 3, 4, 3, 1, -1, -1, 1, 2]),
    ("Jazz", [3, 2, 1, 1, -1, -1, 0, 1, 2, 3]),
    ("Classical", [3, 2, 1, 0, -1, -1, 0, 1, 2, 3]),
    ("Electronic", [5, 4, 1, -1, -2, 0, 1, 3, 4, 4]),
    ("Acoustic", [3, 2, 1, 2, 2, 2, 3, 2, 1, 2]),
]
EQ_PRESET_LABELS = [name for name, _ in EQ_PRESETS] + ["Свой"]
PREAMP_LABELS = ["-12 дБ", "-9 дБ", "-6 дБ", "-3 дБ", "0 дБ", "+3 дБ", "+6 дБ"]
PREAMP_VALUES = [-12, -9, -6, -3, 0, 3, 6]
STRENGTH_LABELS = ["Выкл", "Слабо", "Средне", "Сильно", "Максимум"]
STRENGTH_VALUES = [0, 250, 500, 750, 1000]


def _dp(value):
    return AndroidUtilities.dp(float(value))


def _identity(obj):
    return int(JSystem.identityHashCode(obj)) if obj is not None else 0


def _color(key):
    try:
        return Theme.getColor(key)
    except Exception:
        return 0xFF888888


def _selected_account():
    return UserConfig.selectedAccount


def _fmt_time(seconds):
    seconds = max(0, int(seconds))
    return "%d:%02d" % (seconds // 60, seconds % 60)


def _norm_key(text):
    return re.sub(r"[^\w]+", " ", (text or "").lower()).strip()
