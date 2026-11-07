# SPDX-License-Identifier: LGPL-3.0-only
# Mornye Player for exteraGram. Copyright 2026 BroNik (@BroZYTnikkkk).
# Based on Mornye by zarzet (https://github.com/mornyeapp/Mornye), LGPL-3.0-only.

"""Logging that reaches logcat from an Elyx plugin too (tag "Mornye")."""

from java import jclass

try:
    from android_utils import log as _sdk_log
except Exception:
    _sdk_log = None

_android_log = None


def log(text):
    global _android_log
    text = str(text)
    if _sdk_log is not None:
        try:
            _sdk_log(text)
        except Exception:
            pass
    try:
        if _android_log is None:
            _android_log = jclass("android.util.Log")
        _android_log.i("Mornye", text)
    except Exception:
        pass
