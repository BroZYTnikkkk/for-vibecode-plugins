# Sculpt Player for exteraGram. Copyright 2026 BroNik (@BroZYTnikkkk).

"""Playlists of the songs on the phone, kept with the plugin's files.

Every song is stored with its kind: a song from a chat will need other fields, and has a list of its own later."""

import time
import uuid

from client_utils import run_on_queue

FILE = "playlists.json"
VERSION = 1
KIND_FILE = "file"


class PlaylistStore:
    def __init__(self, plugin):
        self.plugin = plugin
        saved = plugin.music._load(FILE, {})
        self.items = [item for item in (saved.get("items") or []) if isinstance(item, dict) and item.get("id")] if isinstance(saved, dict) else []

    def find(self, playlist_id):
        return next((item for item in self.items if item["id"] == playlist_id), None)

    def changed(self):
        data = {"version": VERSION, "items": [dict(item, songs=list(item["songs"])) for item in self.items]}
        run_on_queue(lambda: self.plugin.music._save(FILE, data))
        player = self.plugin.player
        view = getattr(player, "playlists", None) if player is not None else None
        if view is not None:
            view.data_changed()

    def create(self, name, paths=()):
        item = {"id": uuid.uuid4().hex, "name": name, "created": int(time.time()), "songs": []}
        self.items.insert(0, item)
        self.fill(item, paths)
        self.changed()
        return item

    @staticmethod
    def fill(item, paths):
        """Adds what is not there yet; returns how many songs were new."""
        known = {song.get("path") for song in item["songs"]}
        added = 0
        for path in paths:
            if path and path not in known:
                known.add(path)
                item["songs"].append({"kind": KIND_FILE, "path": path, "added": int(time.time())})
                added += 1
        return added

    def add(self, playlist_id, paths):
        item = self.find(playlist_id)
        if item is None:
            return 0
        added = self.fill(item, paths)
        if added:
            self.changed()
        return added

    def remove_song(self, playlist_id, path):
        item = self.find(playlist_id)
        if item is not None:
            item["songs"] = [song for song in item["songs"] if song.get("path") != path]
            self.changed()

    def rename(self, playlist_id, name):
        item = self.find(playlist_id)
        if item is not None:
            item["name"] = name
            self.changed()

    def delete(self, playlist_id):
        """The playlist only: the songs stay on the phone."""
        self.items = [item for item in self.items if item["id"] != playlist_id]
        self.changed()

    def tracks(self, playlist_id):
        """The songs that are still on the phone, in the playlist's order."""
        item = self.find(playlist_id)
        by_path = self.plugin.music.by_path
        return [by_path[song["path"]] for song in item["songs"] if song.get("path") in by_path] if item is not None else []
