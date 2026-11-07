# Sculpt Player for exteraGram. Copyright 2026 BroNik (@BroZYTnikkkk).

"""Several queues, as in Musicolet: every list the music was started from keeps its own song and place.

A queue from the media library is known by the list it came from ("Все песни", an album, an author) and is
saved with the plugin's files. A queue from a chat is known by the chat; its songs are Telegram messages, so
it lives until Telegram restarts (keeping the player across restarts is a later step of the plan).
"""

from client_utils import run_on_queue
from java import jclass

from .common import MEDIA_CONTROLLER, QUEUES_MAX
from .music import local_path

LIBRARY_TITLE = "Медиатека"


class QueueStore:
    """The queues, oldest first, and which of them is playing."""

    def __init__(self, plugin):
        self.plugin = plugin
        self.entries = []
        self.active = None
        self.on_change = None
        # set while this plugin itself hands a queue to MediaController, so the hook does not count it twice
        self.starting = False
        saved = plugin.music._load("queues.json", {})
        for entry in saved.get("entries", []) if isinstance(saved, dict) else []:
            if entry.get("kind") == "library" and entry.get("paths"):
                self.entries.append(entry)
        if self.find(saved.get("active") if isinstance(saved, dict) else None) is not None:
            self.active = saved["active"]

    # -- state ----------------------------------------------------------------------

    def find(self, key):
        for entry in self.entries:
            if entry["key"] == key:
                return entry
        return None

    def save(self):
        data = {"active": self.active,
                "entries": [{k: v for k, v in e.items() if k != "java"} for e in self.entries if e["kind"] == "library"]}
        run_on_queue(lambda: self.plugin.music._save("queues.json", data))

    def changed(self):
        self.save()
        callback = self.on_change
        if callback is not None:
            callback()

    def put(self, entry):
        """A started queue becomes the active one, in the place it had if it was there before."""
        for index, old in enumerate(self.entries):
            if old["key"] == entry["key"]:
                self.entries[index] = entry
                break
        else:
            self.entries.append(entry)
            while len(self.entries) > QUEUES_MAX:
                self.entries.pop(0)
        self.active = entry["key"]
        self.changed()

    def remove(self, key):
        """Lets a queue go; returns what restore() needs to bring it back, or None when there was no such queue."""
        for index, entry in enumerate(self.entries):
            if entry["key"] == key:
                break
        else:
            return None
        was_active = self.active == key
        del self.entries[index]
        if was_active:
            self.active = None
        self.changed()
        return index, entry, was_active

    def restore(self, removed):
        """Undo of remove(): the queue comes back at its place, active again if it was."""
        if removed is None:
            return
        index, entry, was_active = removed
        if self.find(entry["key"]) is not None:
            return  # started again from its list in the meantime: that one is newer
        self.entries.insert(min(index, len(self.entries)), entry)
        while len(self.entries) > QUEUES_MAX:
            self.entries.pop(0)
        if was_active and self.active is None:
            self.active = entry["key"]
        self.changed()

    def snapshot(self):
        """The active queue remembers the song playing now and how far into it, before something replaces it."""
        entry = self.find(self.active)
        controller = jclass(MEDIA_CONTROLLER).getInstance()
        message = controller.getPlayingMessageObject()
        if entry is None or message is None:
            return
        path = local_path(message)
        if entry["kind"] == "library":
            if path is None:
                return  # a chat's song plays: this queue was left before
            entry["current"] = path
        else:
            if path is not None or message.getDialogId() != entry["dialog"]:
                return
            entry["current"] = message.getId()
            # the chat's queue may have grown since it started: Telegram loads more of its music as it plays
            entry["java"] = jclass("java.util.ArrayList")(controller.getPlaylist())
        entry["progress"] = float(message.audioProgress)

    # -- where queues come from -------------------------------------------------------

    def library_started(self, title, tracks, index, progress=0.0):
        self.snapshot()
        title = title or LIBRARY_TITLE
        self.put({"key": "lib:" + title, "kind": "library", "title": title, "paths": [t["path"] for t in tracks],
                  "current": tracks[index]["path"], "progress": float(progress)})

    def before_playlist(self):
        """Before MediaController.setPlaylist from anywhere: the queue it replaces keeps its place."""
        if not self.starting:
            self.snapshot()

    def after_playlist(self):
        """After MediaController.setPlaylist from a chat: that chat's music is a queue of its own."""
        if self.starting:
            return
        controller = jclass(MEDIA_CONTROLLER).getInstance()
        message = controller.getPlayingMessageObject()
        if message is None or local_path(message) is not None or not message.isMusic():
            return
        dialog = message.getDialogId()
        self.put({"key": "tg:%d" % dialog, "kind": "telegram", "title": self.chat_title(message), "dialog": dialog,
                  "current": message.getId(), "progress": 0.0,
                  "java": jclass("java.util.ArrayList")(controller.getPlaylist())})

    @staticmethod
    def chat_title(message):
        account = message.currentAccount
        dialog = message.getDialogId()
        controller = jclass("org.telegram.messenger.MessagesController").getInstance(account)
        Long = jclass("java.lang.Long")
        try:
            if dialog > 0:
                user = controller.getUser(Long(dialog))
                if user is not None:
                    if user.self:
                        return str(jclass("org.telegram.messenger.LocaleController").getString(
                            jclass("org.telegram.messenger.R$string").SavedMessages))
                    return str(jclass("org.telegram.messenger.UserObject").getUserName(user))
            else:
                chat = controller.getChat(Long(-dialog))
                if chat is not None and chat.title:
                    return str(chat.title)
        except Exception:
            pass
        return "Чат"

    # -- switching ---------------------------------------------------------------------

    def switch(self, key):
        """The chosen queue plays again from the song and the place it was left at."""
        entry = self.find(key)
        if entry is None:
            return
        self.snapshot()
        progress = float(entry.get("progress") or 0.0)
        if entry["kind"] == "library":
            by_path = self.plugin.music.by_path
            tracks = [by_path[p] for p in entry["paths"] if p in by_path]
            if not tracks:
                self.plugin.bulletin(self.plugin.player.sheet, "info", "Песен этой очереди больше нет на телефоне.")
                return
            index = next((i for i, t in enumerate(tracks) if t["path"] == entry.get("current")), 0)
            if tracks[index]["path"] != entry.get("current"):
                progress = 0.0
            self.plugin.music.play(tracks, index, entry["title"], progress)
            return
        java = entry.get("java")
        if java is None or java.isEmpty():
            return
        message = java.get(0)
        for i in range(java.size()):
            if java.get(i).getId() == entry.get("current"):
                message = java.get(i)
                break
        else:
            progress = 0.0
        if progress > 0.0:
            message.forceSeekTo = progress
        controller = jclass(MEDIA_CONTROLLER).getInstance()
        self.starting = True
        try:
            controller.setPlaylist(java, message, entry["dialog"])
        finally:
            self.starting = False
        self.active = key
        self.changed()
