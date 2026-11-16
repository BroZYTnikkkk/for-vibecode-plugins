# Sculpt Player for exteraGram. Copyright 2026 BroNik (@BroZYTnikkkk).

"""Where the plugin's time goes, for a pass of optimisation: every hook and list row is timed, and the totals are
written to the log every 10 seconds. Off unless asked for from a computer:

    adb shell setprop log.tag.SculptProfile VERBOSE   (then reload the plugin; "INFO" turns it off again)
"""

import time

from java import jclass

from .common import _log

EVERY = 10.0

_on = None
_stats = {}  # name -> [calls, seconds, worst]
_since = [0.0]


def enabled():
    global _on
    if _on is None:
        try:
            log = jclass("android.util.Log")
            _on = bool(log.isLoggable("SculptProfile", log.VERBOSE))
        except Exception:
            _on = False
        if _on:
            _log("profile: on")
    return _on


def add(name, spent):
    entry = _stats.get(name)
    if entry is None:
        entry = _stats[name] = [0, 0.0, 0.0]
    entry[0] += 1
    entry[1] += spent
    if spent > entry[2]:
        entry[2] = spent
    now = time.monotonic()
    if now - _since[0] >= EVERY:
        window = now - _since[0] if _since[0] else EVERY
        _since[0] = now
        top = sorted(_stats.items(), key=lambda kv: -kv[1][1])[:14]
        _log("profile %.0fs: " % window + "; ".join(
            "%s %dx %.0fms max %.1f" % (n, c, t * 1000, w * 1000) for n, (c, t, w) in top))
        _stats.clear()


def timed(name, function):
    """The same function, timed when profiling is on."""
    if not enabled():
        return function

    def wrapper(*args, **kwargs):
        started = time.perf_counter()
        try:
            return function(*args, **kwargs)
        finally:
            add(name, time.perf_counter() - started)

    return wrapper


def wrap_hook(name, handler):
    """A hook's before and after methods timed under its name."""
    if not enabled():
        return handler
    for side in ("before_hooked_method", "after_hooked_method"):
        if side in type(handler).__dict__ or any(side in base.__dict__ for base in type(handler).__mro__[1:-1] if base.__name__ != "MethodHook"):
            setattr(handler, side, timed("%s.%s" % (name, side[0]), getattr(handler, side)))
    return handler


class Marks:
    """Times the parts of one call: each mark(name) adds the time since the previous mark."""

    def __init__(self):
        self.last = time.perf_counter()

    def __call__(self, name):
        now = time.perf_counter()
        add(name, now - self.last)
        self.last = now
