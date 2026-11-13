# SPDX-License-Identifier: LGPL-3.0-only
# Mornye Player for exteraGram. Copyright 2026 BroNik (@BroZYTnikkkk).
# Based on Mornye by zarzet (https://github.com/mornyeapp/Mornye), LGPL-3.0-only.

"""Saved queues and playlists.

Kinds: "user" (made by hand, never changes by itself), "chat" (a playlist started from a Telegram chat,
named after it and refreshed on the next launch from that chat), "theme" (All songs, an album, Popular...,
refreshed when the user plays from that theme again). Renaming an automatic queue pins it: it stops
refreshing, and the next launch from the same source makes a fresh one.
"""

import threading
import time
import uuid

FILE = "queues.json"
MAX_TRACKS = 2000
MAX_AUTO = 30


def _clean(track):
    return {"path": track.get("path") or "", "title": track.get("title") or "", "artist": track.get("artist") or "",
            "album": track.get("album") or "", "duration": int(track.get("duration") or 0)}


class Queues:
    def __init__(self, library):
        self.lib = library
        self.lock = threading.Lock()
        data = library._load(FILE, [])
        self.items = [q for q in data if isinstance(q, dict) and q.get("id")] if isinstance(data, list) else []

    def _save(self):
        self.lib._save(FILE, self.items)

    def _find(self, qid):
        for q in self.items:
            if q["id"] == qid:
                return q
        raise KeyError("очередь не найдена")

    def summaries(self):
        with self.lock:
            return [{"id": q["id"], "name": q["name"], "kind": q["kind"], "pinned": bool(q.get("pinned")),
                     "count": len(q["tracks"]), "updated": q.get("updated", 0),
                     "cover": next((t["path"] for t in q["tracks"] if t.get("path")), "")}
                    for q in sorted(self.items, key=lambda q: q.get("updated", 0), reverse=True)]

    def get(self, qid):
        with self.lock:
            q = self._find(qid)
            return dict(q, tracks=list(q["tracks"]))

    def create(self, name, tracks, kind="user", key=""):
        q = {"id": uuid.uuid4().hex[:12], "name": (name or "Новая очередь").strip()[:80], "kind": kind, "key": key,
             "pinned": kind == "user", "tracks": [_clean(t) for t in tracks][:MAX_TRACKS], "updated": int(time.time())}
        with self.lock:
            self.items.append(q)
            self._save()
        return q["id"]

    def save_auto(self, kind, key, name, tracks):
        """Refresh the unpinned automatic queue for this source, or start one."""
        tracks = [_clean(t) for t in tracks][:MAX_TRACKS]
        if not tracks:
            return None
        with self.lock:
            for q in self.items:
                if q["kind"] == kind and q.get("key") == key and not q.get("pinned"):
                    q["tracks"], q["name"], q["updated"] = tracks, name, int(time.time())
                    self._save()
                    return q["id"]
            auto = [q for q in self.items if q["kind"] != "user" and not q.get("pinned")]
            if len(auto) >= MAX_AUTO:
                oldest = min(auto, key=lambda q: q.get("updated", 0))
                self.items.remove(oldest)
        return self.create(name, tracks, kind, key)

    def rename(self, qid, name):
        with self.lock:
            q = self._find(qid)
            q["name"] = (name or q["name"]).strip()[:80]
            q["pinned"] = True
            self._save()

    def delete(self, qid):
        with self.lock:
            self.items.remove(self._find(qid))
            self._save()

    def add(self, qid, tracks):
        with self.lock:
            q = self._find(qid)
            have = {t["path"] for t in q["tracks"]}
            q["tracks"].extend(_clean(t) for t in tracks if t.get("path") not in have)
            q["tracks"] = q["tracks"][:MAX_TRACKS]
            q["updated"] = int(time.time())
            self._save()
            return len(q["tracks"])

    def remove(self, qid, indexes):
        with self.lock:
            q = self._find(qid)
            drop = {int(i) for i in indexes}
            q["tracks"] = [t for i, t in enumerate(q["tracks"]) if i not in drop]
            self._save()

    def move(self, qid, src, dst):
        with self.lock:
            q = self._find(qid)
            tracks = q["tracks"]
            if 0 <= src < len(tracks) and 0 <= dst < len(tracks):
                tracks.insert(dst, tracks.pop(src))
                self._save()
