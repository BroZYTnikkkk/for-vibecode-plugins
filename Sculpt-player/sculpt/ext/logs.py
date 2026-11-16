# SPDX-License-Identifier: LGPL-3.0-only
# Mornye extensions in Sculpt Player. Copyright 2026 BroNik (@BroZYTnikkkk).
# Based on Mornye by zarzet (https://github.com/mornyeapp/Mornye), LGPL-3.0-only.

"""The extensions' log lines go to logcat under Sculpt Player's tag."""

from ..common import _log


def log(text):
    _log(text)
