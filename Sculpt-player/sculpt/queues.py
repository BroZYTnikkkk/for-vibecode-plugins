# Sculpt Player for exteraGram. Copyright 2026 BroNik (@BroZYTnikkkk).

"""Several queues, as in Musicolet: every list the music was started from keeps its own song and place.

A queue from the media library is known by the list it came from ("Все песни", an album, an author) and is
saved with the plugin's files. A queue from a chat is known by the chat; its songs are Telegram messages, kept as
references and asked of Telegram again after a restart.
"""

import random

from client_utils import run_on_queue
from java import jclass

from .i18n import source, tr
from . import chat_songs
from .common import MEDIA_CONTROLLER, QUEUES_MAX, _log, sculpt_method
from .music import local_path

LIBRARY_TITLE = tr("Медиатека")


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
            if (entry.get("kind") == "library" and entry.get("paths")) or (entry.get("kind") == "telegram" and entry.get("songs")):
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
        def work():
            for entry in list(self.entries):
                java = entry.get("java")
                # made only when the chat's queue changed in size: every song is several calls into Java
                if entry["kind"] == "telegram" and java is not None and len(entry.get("songs") or []) != java.size():
                    try:
                        entry["songs"] = [chat_songs.ref_of(java.get(i)) for i in range(java.size())]
                    except Exception as e:
                        _log("queue refs: %s" % type(e).__name__)  # the other queues are still saved
            data = {"active": self.active, "entries": [{k: v for k, v in e.items() if k not in ("java", "loading", "tried")} for e in self.entries]}
            self.plugin.music._save("queues.json", data)

        run_on_queue(work)

    def ensure_java(self, entry, done):
        """A chat's queue saved before a restart: its messages are asked of Telegram once; done() when they answered."""
        if entry.get("java") is not None or entry.get("loading") or entry.get("tried") or not entry.get("songs"):
            return
        entry["loading"] = True

        def loaded(found):
            entry["loading"] = False
            entry["tried"] = True  # all of them deleted: not asked again and again
            kept = [found[chat_songs.key_of(ref)] for ref in entry["songs"] if chat_songs.key_of(ref) in found]
            if kept:
                java = jclass("java.util.ArrayList")()
                for message in kept:
                    java.add(message)
                entry["java"] = java
            done()

        chat_songs.load(entry["songs"], loaded)

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
            self.keep_order(entry, controller)
        else:
            if path is not None or message.getDialogId() != entry["dialog"]:
                return
            entry["current"] = message.getId()
            # the chat's queue may have grown since it started: Telegram loads more of its music as it plays
            entry["java"] = jclass("java.util.ArrayList")(controller.getPlaylist())
        entry["progress"] = float(message.audioProgress)

    # -- the order a mixed queue plays in ---------------------------------------------

    @staticmethod
    def shuffle_on():
        return jclass("org.telegram.messenger.SharedConfig").shuffleMusic is True

    def keep_order(self, entry, controller):
        """With shuffle on, the active library queue remembers the order it plays in, as places in its list."""
        if not self.shuffle_on():
            entry.pop("played", None)
            return
        reader = sculpt_method("sculpt.Queue", "paths")
        mixed = self.plugin.media_fields.get(controller, "shuffledPlaylist")
        if reader is None or mixed is None or mixed.isEmpty():
            return
        text = reader.invoke(None, mixed)
        if text is None:
            return
        place = {path: i for i, path in enumerate(entry["paths"])}
        order, seen = [], set()
        # the mixed list is walked towards index 0: its last song plays first
        for path in reversed(str(text).split("\n")):
            i = place.get(path)
            if i is not None and i not in seen:
                seen.add(i)
                order.append(i)
        if len(order) == len(entry["paths"]):  # not while the queue is still being built
            entry["played"] = order

    def play_order(self, entry):
        """The paths of a library queue in the order it plays with shuffle on; None when it plays as listed.

        A queue that has none yet is mixed here once: what the Queue tab shows is then what plays."""
        if entry["kind"] != "library" or not self.shuffle_on():
            return None
        paths = entry["paths"]
        played = entry.get("played")
        if not (isinstance(played, list) and len(played) == len(paths) and sorted(played) == list(range(len(paths)))):
            played = list(range(len(paths)))
            random.shuffle(played)
            entry["played"] = played
        return [paths[i] for i in played]

    # -- where queues come from -------------------------------------------------------

    def library_started(self, title, tracks, index, progress=0.0, played=None):
        self.snapshot()
        title = source(title or LIBRARY_TITLE)  # saved in one language, so a queue stays the same one when the language changes
        entry = {"key": "lib:" + title, "kind": "library", "title": title, "paths": [t["path"] for t in tracks],
                 "current": tracks[index]["path"], "progress": float(progress)}
        if played is not None:
            entry["played"] = list(played)
        self.put(entry)

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
        return tr("Чат")

    def gone(self):
        self.plugin.bulletin(self.plugin.player.sheet, "info", tr("Песни этой очереди больше недоступны в Telegram."))

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
                self.plugin.bulletin(self.plugin.player.sheet, "info", tr("Песен этой очереди больше нет на телефоне."))
                return
            index = next((i for i, t in enumerate(tracks) if t["path"] == entry.get("current")), 0)
            if tracks[index]["path"] != entry.get("current"):
                progress = 0.0
            order = self.play_order(entry)
            self.plugin.music.play_in_place(tracks, index, tr(entry["title"]), progress,
                                            order=None if order is None else [by_path[p] for p in order if p in by_path])
            return
        java = entry.get("java")
        if java is None and entry.get("songs"):
            if entry.get("tried"):
                self.gone()
            else:
                self.ensure_java(entry, lambda: self.switch(key))
            return
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
