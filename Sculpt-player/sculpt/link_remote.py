# SPDX-License-Identifier: LGPL-3.0-only
# Sculpt Player for exteraGram. Copyright 2026 BroNik (@BroZYTnikkkk).
# Mornye Link comes from Mornye by zarzet (https://github.com/mornyeapp/Mornye), LGPL-3.0-only.

"""Mornye on the computer as a remote for this phone: it is told what plays here, and its commands are carried out.
The phone's volume is left alone: a volume command is ignored."""

import threading
import time

from android_utils import run_on_ui_thread
from java import jclass

from .common import MEDIA_CONTROLLER, _log
from .music import local_path

QUEUE_WINDOW = 200  # songs around the current one, as Mornye sends
POLL = 1.0
HEARTBEAT = 15.0  # while playing, even when nothing changed
SEEK_NOTICE = 1500  # ms between where the song should be and where it is
REPEAT_NAMES = {0: "none", 1: "all", 2: "one"}
REPEAT_MODES = {name: mode for mode, name in REPEAT_NAMES.items()}
ORDER_NORMAL, ORDER_REVERSED, ORDER_SHUFFLE = 0, 1, 2


def now_ms():
    return int(time.time() * 1000)


class Remote:
    def __init__(self, plugin, share):
        self.plugin = plugin
        self.share = share
        self.items = []
        self.start = 0
        self.refs = []
        self.queue_key = None

    @staticmethod
    def controller():
        return jclass(MEDIA_CONTROLLER).getInstance()

    @staticmethod
    def config():
        return jclass("org.telegram.messenger.SharedConfig")

    def active_order(self, controller):
        """The songs in the order they will play, and whether the player walks its list backwards."""
        config = self.config()
        if config.shuffleMusic:
            mixed = self.plugin.media_fields.get(controller, "shuffledPlaylist")
            if mixed is not None and not mixed.isEmpty():
                return mixed, True
        return controller.getPlaylist(), not config.playOrderReversed

    def ref(self, message):
        title, artist = message.getMusicTitle(), message.getMusicAuthor()
        ref = {"title": str(title) if title else "", "artist": str(artist) if artist else ""}
        duration = int(float(message.getDuration() or 0) * 1000)
        if duration > 0:
            ref["durationMs"] = duration
        path = local_path(message)
        file_id = self.share.file_ids.get(path) if path else None
        if file_id:
            ref["fileId"] = file_id  # which also tells the computer the song's cover
        return ref

    def refresh_queue(self, controller, playing):
        """(the index of the playing song in the sent window). The refs are made again only when the queue moved."""
        listed, backwards = self.active_order(controller)
        size = listed.size()
        number = controller.getPlayingMessageObjectNum()
        index = size - 1 - number if backwards else number
        if not 0 <= index < size:
            index = -1
        key = (size, index, playing.getId(), playing.getDialogId(), backwards)
        if key != self.queue_key:
            self.queue_key = key
            start = max(0, min(index - QUEUE_WINDOW // 2, size - QUEUE_WINDOW)) if index >= 0 else 0
            if backwards:
                order = range(size - 1 - start, max(-1, size - 1 - start - QUEUE_WINDOW), -1)
            else:
                order = range(start, min(size, start + QUEUE_WINDOW))
            self.items = [listed.get(i) for i in order]
            self.refs = [self.ref(m) for m in self.items]
            self.start = start
        return index - self.start if index >= 0 else -1

    def state(self):
        controller, config = self.controller(), self.config()
        state = {"playing": False, "positionMs": 0, "updatedMs": now_ms(), "index": -1, "shuffle": bool(config.shuffleMusic),
                 "repeat": REPEAT_NAMES.get(int(config.repeatMode), "none"), "volume": 1.0}
        playing = controller.getPlayingMessageObject()
        if playing is None:
            if self.queue_key is not None:
                self.items, self.refs, self.queue_key = [], [], None
            state["queue"] = self.refs
            return state
        index = self.refresh_queue(controller, playing)
        duration = int(float(playing.getDuration() or 0) * 1000)
        state.update(track=self.ref(playing), playing=not controller.isMessagePaused(), queue=self.refs, index=index,
                     positionMs=int(float(playing.audioProgress) * duration))
        if duration > 0:
            state["durationMs"] = duration
        return state

    @staticmethod
    def changed(last, state):
        if last is None or last["queue"] is not state["queue"]:
            return True
        for key in ("track", "playing", "index", "shuffle", "repeat", "durationMs"):
            if last.get(key) != state.get(key):
                return True
        expected = last["positionMs"]
        if last["playing"]:
            expected += state["updatedMs"] - last["updatedMs"]
        return abs(expected - state["positionMs"]) > SEEK_NOTICE

    def loop(self, sock, stopping):
        """Every second while this connection lives: anything new goes to the computer."""
        last, sent_at = None, 0.0
        while not stopping.is_set() and self.share.socket is sock:
            try:
                state = self.state()
                moment = time.monotonic()
                if self.changed(last, state) or (state["playing"] and moment - sent_at >= HEARTBEAT):
                    sock.send({"type": "player.state", "state": state})
                    last, sent_at = state, moment
            except OSError:
                return
            except Exception as e:
                _log("link: state %s" % type(e).__name__)
            stopping.wait(POLL)

    def start_loop(self, sock, stopping):
        threading.Thread(target=self.loop, args=(sock, stopping), name="sculpt-link-state", daemon=True).start()

    def command(self, message):
        args = message.get("args")
        action, args = message.get("action"), args if isinstance(args, dict) else {}
        run_on_ui_thread(lambda: self.apply(action, args))

    def apply(self, action, args):
        try:
            controller, config = self.controller(), self.config()
            playing = controller.getPlayingMessageObject()
            paused = controller.isMessagePaused()
            if action in ("play", "toggle") and playing is not None and paused:
                controller.playMessage(playing)
            elif action in ("pause", "toggle") and playing is not None and not paused:
                controller.pauseMessage(playing)
            elif action == "next":
                controller.playNextMessage()
            elif action == "previous":
                controller.playPreviousMessage()
            elif action == "seek" and playing is not None and isinstance(args.get("positionMs"), (int, float)):
                controller.seekToProgressMs(playing, max(0, int(args["positionMs"])))
            elif action == "shuffle":
                reversed_order = ORDER_REVERSED if config.playOrderReversed else ORDER_NORMAL
                controller.setPlaybackOrderType(ORDER_SHUFFLE if args.get("enabled") is True else reversed_order)
            elif action == "repeat" and args.get("mode") in REPEAT_MODES:
                config.setRepeatMode(REPEAT_MODES[args["mode"]])
            elif action == "jump" and isinstance(args.get("index"), int) and 0 <= args["index"] < len(self.items):
                controller.playMessage(self.items[args["index"]])
            elif action != "volume":
                _log("link: command not done here: %s" % action)
        except Exception as e:
            _log("link: command %s %s" % (action, type(e).__name__))
