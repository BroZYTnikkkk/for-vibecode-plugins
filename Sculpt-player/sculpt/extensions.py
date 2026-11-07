# SPDX-License-Identifier: LGPL-3.0-only
# Sculpt Player for exteraGram. Copyright 2026 BroNik (@BroZYTnikkkk).
# Mornye extensions come from Mornye by zarzet (https://github.com/mornyeapp/Mornye), LGPL-3.0-only.

"""Mornye extensions for the whole plugin: one manager, work off the UI thread, a .sflx from any chat."""

import os
import threading

from android_utils import run_on_ui_thread
from ui.bulletin import BulletinHelper

from .common import _log

# shown on a message only when it is a Mornye extension package
SFLX_CONDITION = ("message != null && message.getDocumentName() != null"
                  " && message.getDocumentName().toLowerCase().endsWith('.sflx')")

TYPE_NAMES = {"download_provider": "Скачивание", "metadata_provider": "Метаданные", "lyrics_provider": "Тексты"}

# what the extension code says when something fails, in the words this plugin uses
ERRORS = (
    ("checksum mismatch", "Файл расширения не совпал с каталогом. Попробуй ещё раз позже."),
    ("cannot downgrade", "Установлена более новая версия этого расширения."),
    ("registry not found", "По этой ссылке нет каталога расширений. Нужна ссылка на GitHub-репозиторий или registry.json."),
    ("invalid registry", "По этой ссылке не каталог расширений: в файле нет списка extensions."),
    ("must use https", "Ссылка должна начинаться с https://."),
    ("manifest", "Файл не похож на расширение Mornye: в нём нет верного manifest.json."),
    ("too large", "Расширение слишком большое: больше 256 МБ."),
)


def describe(error):
    text = str(error)
    low = text.lower()
    for key, message in ERRORS:
        if key in low:
            return message
    if "timed out" in low or "connection" in low or "resolve" in low or "network" in low:
        return "Нет связи с сервером. Проверь интернет и попробуй ещё раз."
    return text


def type_names(types):
    return ", ".join(TYPE_NAMES.get(t, t) for t in types)


class Extensions:
    def __init__(self, plugin):
        self.plugin = plugin
        self.lock = threading.Lock()
        self.manager = None
        self.root = os.path.join(plugin.music.dir, "extensions")

    def get(self):
        """The manager, made on first use: it reads the installed packages from disk. Call off the UI thread."""
        with self.lock:
            if self.manager is None:
                from .ext.ext_manager import ExtensionManager
                self.manager = ExtensionManager(self.root)
            return self.manager

    def work(self, task, done=None, failed=None):
        """task(manager) on its own thread; done(result) or failed(message) back on the UI thread."""

        def run():
            try:
                result = task(self.get())
            except Exception as e:
                _log("extensions: %s" % e)
                message = describe(e)
                if failed is not None:
                    run_on_ui_thread(lambda: failed(message))
                return
            if done is not None:
                run_on_ui_thread(lambda: done(result))

        threading.Thread(target=run, name="sculpt-ext", daemon=True).start()

    def close(self):
        with self.lock:
            manager, self.manager = self.manager, None
        if manager is not None:
            try:
                manager.close()
            except Exception:
                pass

    # -- a .sflx sent to any chat

    def install_message(self, context):
        message = context.get("message") if context else None
        if message is None:
            return
        from org.telegram.messenger import FileLoader
        try:
            file = FileLoader.getInstance(message.currentAccount).getPathToMessage(message.messageOwner)
        except Exception:
            file = None
        if file is None or not file.exists():
            BulletinHelper.show_info("Сначала скачай файл расширения в чате, потом установи его.")
            return
        path = str(file.getAbsolutePath())

        def installed(ext):
            manifest = self.get().manifest(ext)
            name = manifest.display_name if manifest is not None else ext
            BulletinHelper.show_success("Расширение «%s» установлено. Оно во вкладке Mornye плеера." % name)
            player = self.plugin.player
            if player is not None and player.mornye is not None:
                player.mornye.data_changed()

        self.work(lambda manager: manager.install_file(path), installed,
                  lambda text: BulletinHelper.show_error("Расширение не установлено. " + text))
