# SPDX-License-Identifier: LGPL-3.0-only
# Mornye Player for exteraGram. Copyright 2026 BroNik (@BroZYTnikkkk).
# Based on Mornye by zarzet (https://github.com/mornyeapp/Mornye), LGPL-3.0-only.

"""Texts shipped in assets/: the worker bridge page, Mornye prelude.js and provider.js, the app."""

import os


def _asset_text(filename):
    candidates = []
    try:
        from elyx import assets
        asset = assets[filename.rsplit(".", 1)[0]]
        for attr in ("path_str", "path"):
            path = getattr(asset, attr, None)
            if path:
                candidates.append(str(path))
    except Exception:
        pass
    here = os.path.dirname(os.path.abspath(__file__))
    candidates.append(os.path.join(here, os.pardir, "assets", filename))
    for path in candidates:
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as f:
                return f.read()
    raise RuntimeError("Mornye Player: asset %s not found" % filename)


BRIDGE_PAGE_HTML = _asset_text('bridge.html')
WORKER_JS = _asset_text('worker.js')
MORNYE_PRELUDE_JS = _asset_text('prelude.js')
MORNYE_PROVIDER_JS = _asset_text('provider.js')
APP_HTML = _asset_text('app.html')
