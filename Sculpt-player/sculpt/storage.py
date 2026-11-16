# SPDX-License-Identifier: LGPL-3.0-only
# Sculpt Player for exteraGram. Copyright 2026 BroNik (@BroZYTnikkkk).

"""Where the plugin keeps its files: user data in the app's internal files dir, caches in the cache dir.

file_utils.get_files_dir() is Telegram's "exteraGram Files" media folder, which Settings > Data and Storage >
Clear Cache empties; the plugin's own unpacked folder is rewritten on every update. The internal files dir
(Context.getFilesDir) is touched by neither.
"""

import os
import shutil

from .common import _ctx, _log

DATA_NAME = "sculpt_data"
CACHE_NAME = "sculpt_player"
NOT_MIGRATED = ("covers",)  # a cache: rebuilt from the songs


def _old_dir():
    from file_utils import get_files_dir
    return os.path.join(get_files_dir(), CACHE_NAME)


def data_dir():
    """The internal files dir's own folder; the old Telegram-managed folder only when the context gives no usable path."""
    try:
        path = os.path.join(str(_ctx().getFilesDir().getAbsolutePath()), DATA_NAME)
        os.makedirs(path, exist_ok=True)
        return path
    except Exception as e:
        _log("storage: internal files dir unavailable, using the old folder: %s" % e)
        path = _old_dir()
        os.makedirs(path, exist_ok=True)
        return path


def cache_dir():
    try:
        path = os.path.join(str(_ctx().getCacheDir().getAbsolutePath()), CACHE_NAME)
        os.makedirs(path, exist_ok=True)
        return path
    except Exception:
        return data_dir()


def _copy_verified(src, dst):
    """Copy one file next to its place, check the size, then move it in; the source stays until that worked."""
    tmp = dst + ".moving"
    shutil.copyfile(src, tmp)
    if os.path.getsize(tmp) != os.path.getsize(src):
        os.remove(tmp)
        raise OSError("size differs after copy: %s" % src)
    os.replace(tmp, dst)


def _merge(src, dst, counts):
    """Everything of src that dst lacks goes to dst; what dst already has wins. A source file goes only after its copy is verified."""
    os.makedirs(dst, exist_ok=True)
    for name in os.listdir(src):
        s, d = os.path.join(src, name), os.path.join(dst, name)
        if name.endswith(".moving"):
            continue
        try:
            if os.path.isdir(s):
                _merge(s, d, counts)
                try:
                    os.rmdir(s)
                except OSError:
                    pass
            elif os.path.exists(d):
                counts["kept"] += 1  # the new place has its own, newer copy
            else:
                _copy_verified(s, d)
                os.remove(s)
                counts["moved"] += 1
        except Exception as e:
            counts["failed"] += 1
            _log("storage: %s not moved: %s" % (s, e))


def migrate(old, new, skip=NOT_MIGRATED):
    """Moves what is in the old folder to the new one. Safe to run on every start: with nothing left it does nothing."""
    try:
        if not os.path.isdir(old) or os.path.abspath(old) == os.path.abspath(new):
            return
        counts = {"moved": 0, "kept": 0, "failed": 0}
        os.makedirs(new, exist_ok=True)
        for name in os.listdir(old):
            if name in skip:
                shutil.rmtree(os.path.join(old, name), ignore_errors=True)
                continue
            s, d = os.path.join(old, name), os.path.join(new, name)
            if os.path.isdir(s):
                _merge(s, d, counts)
                try:
                    os.rmdir(s)
                except OSError:
                    pass
            else:
                _merge_file(s, d, counts)
        try:
            os.rmdir(old)
        except OSError:
            pass
        if counts["moved"] or counts["failed"]:
            _log("storage: %s -> %s: moved %d, kept newer %d, failed %d" % (old, new, counts["moved"], counts["kept"], counts["failed"]))
    except Exception as e:
        _log("storage: migration from %s failed: %s" % (old, e))


def _merge_file(s, d, counts):
    try:
        if os.path.exists(d):
            counts["kept"] += 1
        else:
            _copy_verified(s, d)
            os.remove(s)
            counts["moved"] += 1
    except Exception as e:
        counts["failed"] += 1
        _log("storage: %s not moved: %s" % (s, e))
