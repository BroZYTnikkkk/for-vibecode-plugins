# SPDX-License-Identifier: LGPL-3.0-only
# Sculpt Player for exteraGram. Copyright 2026 BroNik (@BroZYTnikkkk).
# Mornye extensions come from Mornye by zarzet (https://github.com/mornyeapp/Mornye), LGPL-3.0-only.

"""Mornye extensions for the whole plugin: one manager, work off the UI thread, a .sflx from any chat."""

import os
import threading

from android_utils import run_on_ui_thread
from java import dynamic_proxy, jarray, jclass
from ui.bulletin import BulletinHelper

from .common import PANEL_LIBRARY, _ctx, _log

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


STAGES = {"checking_session": "Проверяю сессию", "resolving_metadata": "Ищу данные песни", "resolving_stream": "Ищу поток",
          "downloading": "Скачиваю", "finalizing": "Сохраняю"}
QUALITIES = (("LOSSLESS", "Lossless, 16 бит"), ("HI_RES_LOSSLESS", "Hi-Res Lossless, 24 бит"), ("HI_RES", "Hi-Res"),
             ("HIGH", "Высокое, до 320 кбит/с"), ("LOW", "Низкое"))


HEALTH_TTL = 600  # seconds a service's health is trusted; an unknown one is asked again sooner
HEALTH_UNKNOWN_TTL = 120
TRANSIENT = ("timeout", "timed out", "temporar", "try again", "unavailable", "rate limit")


def _health_word(value):
    """A status word from a service's answer, the way Mornye's health.rs reads it."""
    text = str(value or "").strip().lower()
    if text in ("degraded", "partial", "warning"):
        return "degraded"
    if text in ("down", "offline", "error", "failed", "unhealthy"):
        return "offline"
    return "online"


def _health_code(code, message=""):
    if 200 <= code < 300:
        return "online"
    if code in (401, 403):
        return "degraded"
    if code in (408, 429, 502, 503, 504) or any(word in str(message).lower() for word in TRANSIENT):
        return "unknown"
    return "offline"


def check_one(manifest, check):
    """One health check of a manifest: GET or HEAD over https to a host the extension may reach."""
    import requests
    from urllib.parse import urlsplit
    url = str(check.get("url") or "")
    parts = urlsplit(url)
    if parts.scheme != "https" or not manifest.is_domain_allowed(parts.hostname or ""):
        return "offline"
    method = "HEAD" if str(check.get("method") or "GET").upper() == "HEAD" else "GET"
    timeout = max(1.0, float(check.get("timeoutMs") or check.get("timeout_ms") or 4000) / 1000.0)
    try:
        response = requests.request(method, url, timeout=timeout, headers={"Accept": "application/json"})
    except requests.exceptions.Timeout:
        return "unknown"
    except requests.exceptions.ConnectionError as e:
        return "unknown" if any(word in str(e).lower() for word in TRANSIENT) else "offline"
    if not 200 <= response.status_code < 300:
        return "offline"
    if method == "HEAD":
        return "online"
    try:
        body = response.json()
    except Exception:
        return "online"
    if not isinstance(body, dict):
        return "online"
    key = str(check.get("serviceKey") or check.get("service_key") or "")
    services = body.get("services")
    if key and isinstance(services, dict) and key in services:
        entry = services[key]
        if isinstance(entry, dict):
            if isinstance(entry.get("status"), int):
                return _health_code(entry["status"], entry.get("message") or "")
            if isinstance(entry.get("ok"), bool):
                return "online" if entry["ok"] else "offline"
            return _health_word(entry.get("status"))
        return _health_word(entry)
    return _health_word(body.get("status"))


def check_health(manifest):
    """A service's state from all its checks: "online", "degraded", "unknown", "offline"; None without checks."""
    raw = manifest.raw if isinstance(manifest.raw, dict) else {}
    checks = [c for c in (raw.get("serviceHealth") or raw.get("service_health") or []) if isinstance(c, dict) and c.get("url")]
    if not checks:
        return None
    status = "online"
    for check in checks:
        one = check_one(manifest, check)
        required = bool(check.get("required", True))
        if one == "offline":
            status = "offline" if required else ("degraded" if status != "offline" else status)
        elif one == "degraded" and status == "online":
            status = "degraded"
        elif one == "unknown" and status == "online":
            status = "unknown"
    return status


class ScanDone(dynamic_proxy(jclass("android.media.MediaScannerConnection$OnScanCompletedListener"))):
    def __init__(self, action):
        super().__init__()
        self.action = action

    def onScanCompleted(self, path, uri):
        action, self.action = self.action, None
        if action is not None:
            action()


def download_dir():
    """Music/Mornye, the folder Mornye Player uses too; the app's own folder when that one cannot be written."""
    Environment = jclass("android.os.Environment")
    path = os.path.join(str(Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_MUSIC).getAbsolutePath()), "Mornye")
    try:
        os.makedirs(path, exist_ok=True)
        # Android lets an app make only media files in Music/: a probe without an audio extension is refused there
        probe = os.path.join(path, "sculpt-write-check.mp3")
        open(probe, "w").close()
        os.remove(probe)
        return path
    except Exception:
        fallback = os.path.join(str(_ctx().getExternalFilesDir(None).getAbsolutePath()), "Music")
        os.makedirs(fallback, exist_ok=True)
        return fallback


class Extensions:
    def __init__(self, plugin):
        self.plugin = plugin
        self.lock = threading.Lock()
        self.manager = None
        self.queue = None
        self.listeners = []  # called on the UI thread when a download changes
        self.change_posted = False
        self.health_cache = {}  # ext -> (status, when)
        self.root = os.path.join(plugin.music.dir, "extensions")

    def health(self, ext):
        """A download service's state, from its own health checks; cached for ten minutes. Off the UI thread."""
        import time
        cached = self.health_cache.get(ext)
        if cached is not None:
            status, when = cached
            if time.time() - when < (HEALTH_UNKNOWN_TTL if status == "unknown" else HEALTH_TTL):
                return status
        manifest = self.get().manifest(ext)
        status = check_health(manifest) if manifest is not None else None
        self.health_cache[ext] = (status, time.time())
        return status

    # -- downloads

    def downloads(self):
        """The download queue, made on first use; it picks up what was left unfinished. Call off the UI thread."""
        manager = self.get()
        with self.lock:
            if self.queue is None:
                from .ext.downloads import DownloadQueue
                self.queue = DownloadQueue(manager, download_dir, on_change=self.changed, on_done=self.done)
            return self.queue

    def changed(self):
        """From a download's thread, many times a second while it runs: the screens hear of it at most 4 times a second."""
        if self.change_posted:
            return
        self.change_posted = True

        def tell():
            self.change_posted = False
            for listener in list(self.listeners):
                try:
                    listener()
                except Exception as e:
                    _log("download listener: %s" % e)

        run_on_ui_thread(tell, 250)

    def done(self, item, result):
        """A finished download: Android indexes the file, the library looks again, and the song plays if asked."""
        if not result.get("success"):
            return
        path = result.get("file_path") or ""
        play = bool(item.get("play"))
        title = item.get("title") or os.path.basename(path)

        def scanned():
            track = self.plugin.music.by_path.get(path)
            player = self.plugin.player
            if play and track is not None and player is not None:
                if player.library is None:
                    player.show_tab(PANEL_LIBRARY)
                player.library.play([track], 0, "Скачанное")
            elif player is None:
                BulletinHelper.show_success("Скачано: «%s». Песня уже в медиатеке." % title)

        def index():
            try:
                jclass("android.media.MediaScannerConnection").scanFile(
                    _ctx(), jarray(jclass("java.lang.String"))([path]), None,
                    ScanDone(lambda: run_on_ui_thread(lambda: self.plugin.music.scan(scanned))))
            except Exception as e:
                _log("scan download: %s" % e)
                self.plugin.music.scan(scanned)

        run_on_ui_thread(index)

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
            queue, self.queue = self.queue, None
        self.listeners = []
        if queue is not None:
            # the queue's two workers wait on it forever; with nothing left queued they stay asleep
            queue.on_change = None
            queue.on_done = None
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
