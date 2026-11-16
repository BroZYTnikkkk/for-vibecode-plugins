# SPDX-License-Identifier: LGPL-3.0-only
# Mornye extensions in Sculpt Player. Copyright 2026 BroNik (@BroZYTnikkkk).
# Based on Mornye by zarzet (https://github.com/mornyeapp/Mornye), LGPL-3.0-only.

"""Texts shipped in assets/: the worker bridge page, Mornye's prelude.js and provider.js."""

import os

from ..common import _asset_paths


def _asset_text(filename):
    candidates = _asset_paths(filename)
    for path in candidates:
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as f:
                return f.read()
    raise RuntimeError("Sculpt Player: asset %s not found in %s" % (filename, candidates))


BRIDGE_PAGE_HTML = _asset_text("bridge.html")
WORKER_JS = _asset_text("worker.js")
MORNYE_PRELUDE_JS = _asset_text("prelude.js")
MORNYE_PROVIDER_JS = _asset_text("provider.js")
