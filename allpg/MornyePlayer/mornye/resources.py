# SPDX-License-Identifier: LGPL-3.0-only
# Mornye Player for exteraGram. Copyright 2026 BroNik (@BroZYTnikkkk).
# Based on Mornye by zarzet (https://github.com/mornyeapp/Mornye), LGPL-3.0-only.

"""Texts shipped in assets/: the worker bridge page, Mornye prelude.js and provider.js, the app."""

import os

_PLUGIN_ID = "mornye_player"


def _elyx_paths(filename):
    """Where the Elyx asset API says the file is. Names may be normalized (app.html -> app)."""
    out = []
    try:
        from elyx import assets
    except Exception as e:
        _note("elyx import: %s" % e)
        return out
    stem = filename.rsplit(".", 1)[0]
    for key in (stem, filename, stem.replace("-", "_")):
        asset = None
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
                    out.append(str(value))
            except Exception:
                pass
    if not out:
        _note("elyx assets has no %s" % filename)
    return out


def _plugin_dirs():
    """The plugin's own folder, found without __file__ (Elyx modules do not define it)."""
    dirs = []
    here = globals().get("__file__") or _plugin_dirs.__code__.co_filename
    if here and os.path.isabs(here):
        dirs.append(os.path.dirname(os.path.dirname(here)))
    try:
        from org.telegram.messenger import ApplicationLoader
        files = str(ApplicationLoader.applicationContext.getFilesDir().getAbsolutePath())
        dirs.append(os.path.join(files, "plugins", "ElyxPlugins", _PLUGIN_ID))
    except Exception:
        pass
    return dirs


def _note(text):
    try:
        from android_utils import log
        log("[Mornye] assets: " + text)
    except Exception:
        pass


def _asset_text(filename):
    candidates = _elyx_paths(filename) + [os.path.join(d, "assets", filename) for d in _plugin_dirs()]
    for path in candidates:
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as f:
                return f.read()
    raise RuntimeError("Mornye Player: asset %s not found in %s" % (filename, candidates))


BRIDGE_PAGE_HTML = _asset_text('bridge.html')
WORKER_JS = _asset_text('worker.js')
MORNYE_PRELUDE_JS = _asset_text('prelude.js')
MORNYE_PROVIDER_JS = _asset_text('provider.js')
APP_HTML = _asset_text('app.html')
