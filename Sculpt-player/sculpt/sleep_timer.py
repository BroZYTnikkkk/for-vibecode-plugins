# Sculpt Player for exteraGram. Copyright 2026 BroNik (@BroZYTnikkkk).

"""The sleep timer: after the chosen minutes the music pauses, fading out the way exteraGram's own pause does.

Checked once a minute, and once more at the end: a long wait posted at once would outlive a plugin reload."""

import time

from android_utils import run_on_ui_thread
from java import jclass

from .common import MEDIA_CONTROLLER, _log

PRESETS = (15, 30, 45, 60, 90)  # minutes
STEP_MS = 60000


class SleepTimer:
    def __init__(self, plugin):
        self.plugin = plugin
        self.ends = None  # time.monotonic() when the music stops
        self.token = 0

    def minutes_left(self):
        """Whole minutes left, rounded up; None when the timer is off."""
        if self.ends is None:
            return None
        return max(1, int((self.ends - time.monotonic() + 59) // 60))

    def start(self, minutes):
        self.token += 1
        self.ends = time.monotonic() + minutes * 60
        self.wait(self.token)

    def cancel(self):
        self.token += 1
        self.ends = None

    def wait(self, token):
        left = (self.ends - time.monotonic()) * 1000 if self.ends is not None else 0
        run_on_ui_thread(lambda: self.check(token), int(max(50, min(STEP_MS, left))))

    def check(self, token):
        if token != self.token or self.ends is None:
            return  # cancelled, set again, or the plugin was unloaded
        if time.monotonic() < self.ends - 0.05:
            self.wait(token)
            return
        self.ends = None
        controller = jclass(MEDIA_CONTROLLER).getInstance()
        playing = controller.getPlayingMessageObject()
        if playing is not None and not controller.isMessagePaused():
            controller.pauseMessage(playing, True)
        _log("sleep timer: paused")
