# SPDX-License-Identifier: LGPL-3.0-only
# Mornye Player for exteraGram. Copyright 2026 BroNik (@BroZYTnikkkk).
# Based on Mornye by zarzet (https://github.com/mornyeapp/Mornye), LGPL-3.0-only.

"""Backups of the player's data: settings, queues and playlists, favorites, history, stats, extensions.

Audio files and the scan cache stay out. A backup is a zip that goes to Download/Mornye/backups, to a
chosen chat or channel, or both, by hand or on a repeating interval. Restoring: tap "Mornye: в библиотеку"
on the backup file in any chat, or "Восстановить" in the settings for the newest copy on the device.
"""

import json
import os
import threading
import time
import zipfile

from .logs import log

PREFIX = "mornye-backup-"
KEEP_ON_DEVICE = 5
DATA_FILES = ("queues.json", "favorites.json", "history.json", "stats.json", "downloads.json")
SKIP_SETTINGS = {"backup_last"}

DEST_LABELS = ["Устройство", "Чат или канал", "Устройство и чат"]
INTERVAL_LABELS = ["Выключено", "Каждый день", "Каждые 3 дня", "Каждую неделю"]
INTERVAL_DAYS = [0, 1, 3, 7]


def device_dir():
    from android.os import Environment
    root = Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS).getAbsolutePath()
    path = os.path.join(str(root), "Mornye", "backups")
    os.makedirs(path, exist_ok=True)
    return path


def is_backup(name):
    name = os.path.basename(str(name or ""))
    return name.startswith(PREFIX) and name.endswith(".zip")


class Backups:
    def __init__(self, plugin, setting_keys):
        self.plugin = plugin
        self.keys = [k for k in setting_keys if k not in SKIP_SETTINGS]
        self.lock = threading.Lock()
        self._timer = None
        self._stopped = False

    # -- making one

    def _write_zip(self, path):
        lib = self.plugin.library
        settings = {}
        for key in self.keys:
            value = self.plugin.get_setting(key, None)
            if value is not None:
                settings[key] = value if isinstance(value, (bool, int, float, str)) else str(value)
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("backup.json", json.dumps({"format": 1, "created": int(time.time()), "plugin": "mornye_player"}))
            zf.writestr("settings.json", json.dumps(settings, ensure_ascii=False))
            for name in DATA_FILES:
                src = os.path.join(lib.dir, name)
                if os.path.isfile(src):
                    zf.write(src, "data/" + name)
            ext_root = os.path.join(lib.dir, "extensions")
            for top, dirs, files in os.walk(ext_root):
                dirs[:] = [d for d in dirs if d not in ("cache", "tmp")]
                for name in files:
                    if name.endswith(".tmp"):
                        continue
                    full = os.path.join(top, name)
                    zf.write(full, "extensions/" + os.path.relpath(full, ext_root).replace(os.sep, "/"))

    def make(self, reason="manual"):
        """Write a backup and deliver it. Returns a short report for a bulletin."""
        with self.lock:
            stamp = time.strftime("%Y-%m-%d_%H-%M")
            dest = int(self.plugin.get_setting("backup_dest", 0) or 0)
            to_device = dest in (0, 2)
            to_chat = dest in (1, 2)
            folder = device_dir() if to_device else os.path.join(self.plugin.library.dir, "backup_out")
            os.makedirs(folder, exist_ok=True)
            path = os.path.join(folder, PREFIX + stamp + ".zip")
            self._write_zip(path)
            done = []
            if to_device:
                done.append("на устройство")
                self._trim(folder)
            if to_chat:
                chat = self._resolve_chat()
                if chat is None:
                    done.append("чат не найден, проверьте настройку")
                else:
                    self._send(path, chat, "Mornye Player: резервная копия %s" % stamp.replace("_", " "))
                    done.append("в чат")
            self.plugin.set_setting("backup_last", int(time.time()))
            log("[Mornye] backup (%s): %s, %d bytes" % (reason, path, os.path.getsize(path)))
            return "Копия сохранена: " + ", ".join(done)

    def _trim(self, folder):
        old = sorted(n for n in os.listdir(folder) if is_backup(n))
        for name in old[:-KEEP_ON_DEVICE]:
            try:
                os.remove(os.path.join(folder, name))
            except Exception:
                pass

    def _resolve_chat(self):
        """The backup chat: empty means Saved Messages, else a numeric id or a @username."""
        from org.telegram.messenger import MessagesController, UserConfig
        account = UserConfig.selectedAccount
        raw = str(self.plugin.get_setting("backup_chat", "") or "").strip()
        if not raw:
            return account, UserConfig.getInstance(account).getClientUserId()
        if raw.lstrip("-").isdigit():
            return account, int(raw)
        name = raw.lstrip("@").split("/")[-1]
        obj = MessagesController.getInstance(account).getUserOrChat(name)
        if obj is None:
            return None
        cid = obj.id
        return account, (cid if hasattr(obj, "first_name") else -cid)

    def _send(self, path, chat, caption):
        from org.telegram.messenger import AccountInstance
        account, dialog_id = chat
        acc = AccountInstance.getInstance(account)
        from java.lang import Class
        method = None
        for m in Class.forName("org.telegram.messenger.SendMessagesHelper").getMethods():
            if m.getName() == "prepareSendingDocument" and (method is None or len(m.getParameterTypes()) > len(method.getParameterTypes())):
                method = m
        strings = [path, path, caption, "application/zip"]
        args = []
        from java.lang import Boolean, Integer, Long
        for t in method.getParameterTypes():
            name = t.getName()
            if name.endswith("AccountInstance"):
                args.append(acc)
            elif name == "java.lang.String":
                args.append(strings.pop(0) if strings else None)
            elif name == "long":
                args.append(Long(dialog_id))
            elif name == "boolean":
                args.append(Boolean(False))
            elif name == "int":
                args.append(Integer(0))
            else:
                args.append(None)
        method.invoke(None, *args)

    # -- restoring

    def latest_on_device(self):
        try:
            folder = device_dir()
            names = sorted(n for n in os.listdir(folder) if is_backup(n))
            return os.path.join(folder, names[-1]) if names else None
        except Exception:
            return None

    def restore(self, path):
        lib = self.plugin.library
        with self.lock, zipfile.ZipFile(path) as zf:
            names = zf.namelist()
            if "settings.json" not in names or "backup.json" not in names:
                raise RuntimeError("это не резервная копия Mornye Player")
            for key, value in json.loads(zf.read("settings.json").decode("utf-8")).items():
                if key in self.keys:
                    self.plugin.set_setting(key, value)
            ext_root = os.path.join(lib.dir, "extensions")
            for name in names:
                if name.endswith("/"):
                    continue
                if name.startswith("data/") and os.path.basename(name) in DATA_FILES:
                    target = os.path.join(lib.dir, os.path.basename(name))
                elif name.startswith("extensions/"):
                    target = os.path.normpath(os.path.join(ext_root, name[len("extensions/"):]))
                    if not target.startswith(ext_root + os.sep):
                        continue
                else:
                    continue
                os.makedirs(os.path.dirname(target), exist_ok=True)
                tmp = target + ".tmp"
                with open(tmp, "wb") as f:
                    f.write(zf.read(name))
                os.replace(tmp, target)
        log("[Mornye] restored backup %s" % path)

    # -- schedule

    def start(self):
        self._stopped = False
        self._schedule(60)

    def stop(self):
        self._stopped = True
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

    def _schedule(self, delay):
        if self._stopped:
            return
        self._timer = threading.Timer(delay, self._tick)
        self._timer.daemon = True
        self._timer.start()

    def _tick(self):
        try:
            idx = int(self.plugin.get_setting("backup_interval", 2) or 0)
            days = INTERVAL_DAYS[idx] if 0 <= idx < len(INTERVAL_DAYS) else 0
            last = int(self.plugin.get_setting("backup_last", 0) or 0)
            if days and time.time() - last >= days * 86400:
                self.make("auto")
        except Exception as e:
            log("[Mornye] auto backup: %s" % e)
        self._schedule(3600)
