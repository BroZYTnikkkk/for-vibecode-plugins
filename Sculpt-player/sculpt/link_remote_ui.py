# SPDX-License-Identifier: LGPL-3.0-only
# Sculpt Player for exteraGram. Copyright 2026 BroNik (@BroZYTnikkkk).
# Mornye Link comes from Mornye by zarzet (https://github.com/mornyeapp/Mornye), LGPL-3.0-only.

"""The computer's player on the phone: what plays in Mornye there, and the buttons to steer it."""

import time

from android_utils import run_on_ui_thread
from java import dynamic_proxy, jclass

from . import link
from .common import _dp
from .link_stream import saved_server
from .link_ui import LinkBase
from .queue_ui import clock

COVER_DP = 220
SEEK_STEPS = 1000
NEXT_ROWS = 30  # the songs coming up, of the 200 the computer sends
REPEAT_NEXT = {"none": "all", "all": "one", "one": "none"}
REPEAT_ICONS = {"none": "player_new_repeat_off", "all": "player_new_repeatall", "one": "player_new_repeatone"}
REPEAT_WORDS = {"none": "выключен", "all": "вся очередь", "one": "одна песня"}


def name_key(title, artist=""):
    """Letters and digits only: the computer may join several authors differently."""
    return "".join(ch for ch in ("%s|%s" % (title or "", artist or "")).casefold() if ch.isalnum() or ch == "|")


class SeekChanged(dynamic_proxy(jclass("android.widget.SeekBar$OnSeekBarChangeListener"))):
    def __init__(self, screen):
        super().__init__()
        self.screen = screen

    def onProgressChanged(self, bar, value, from_user):
        if from_user and self.screen is not None:
            self.screen.guarded(self.screen.dragged, int(value))

    def onStartTrackingTouch(self, bar):
        if self.screen is not None:
            self.screen.dragging = True

    def onStopTrackingTouch(self, bar):
        if self.screen is not None:
            self.screen.guarded(self.screen.released, int(bar.getProgress()))


class LinkRemoteScreen(LinkBase):
    def __init__(self, owner, saved):
        super().__init__(owner, "Пульт компьютера", saved["name"])
        self.saved = saved
        self.share = owner.plugin.link_share
        self.state = None
        self.heard_at = 0.0
        self.dragging = False
        self.shown_file = -1
        self.queue_shown = None
        self.seek_listener = SeekChanged(self)
        self.by_name, self.by_title = self.phone_songs()
        self.page()
        self.build()
        self.start_body()
        self.paint()
        self.background(lambda: link.api_get(saved, "state"), self.received, self.failed)
        self.share.desktop_listener = self.received_from_thread
        self.share.start()  # for this screen too, even with the phone's songs not shown on the computer
        run_on_ui_thread(self.tick, 1000)

    def phone_songs(self):
        """The computer names a song only by its title and author: this is how it is found among the phone's."""
        by_name, by_title = {}, {}
        for track in self.owner.plugin.music.tracks:
            by_name[name_key(track.get("title"), track.get("artist"))] = track["path"]
            key = name_key(track.get("title"))
            by_title[key] = None if key in by_title else track["path"]  # one song of that name, or no guess at all
        return by_name, by_title

    def path_for(self, song):
        file_id = song.get("fileId")
        path = self.share.path_of(file_id) if file_id else None
        return path or self.by_name.get(name_key(song.get("title"), song.get("artist"))) or self.by_title.get(name_key(song.get("title")))

    def build(self):
        owner = self.owner
        Params = jclass("android.widget.LinearLayout$LayoutParams")
        LinearLayout = jclass("android.widget.LinearLayout")
        self.cover = owner.cover_view(16, COVER_DP)
        place = owner.params(COVER_DP, COVER_DP)
        place.gravity = 1
        place.setMargins(0, _dp(12), 0, _dp(16))
        self.content.addView(self.cover, place)
        self.title = self.centered(20, "text", True)
        self.artist = self.centered(15, "textSecondary", False)
        self.seek = jclass("android.widget.SeekBar")(owner.context)
        self.seek.setMax(SEEK_STEPS)
        self.seek.setContentDescription("Позиция в песне")
        self.seek.setOnSeekBarChangeListener(self.seek_listener)
        place = Params(-1, _dp(40))
        place.setMargins(_dp(8), _dp(12), _dp(8), 0)
        self.content.addView(self.seek, place)
        times = LinearLayout(owner.context)
        times.setOrientation(0)
        times.setPadding(_dp(20), 0, _dp(20), 0)
        self.position = self.label(13, "textSecondary")
        times.addView(self.position, Params(0, -2, 1.0))
        self.duration = self.label(13, "textSecondary")
        times.addView(self.duration)
        self.content.addView(times, Params(-1, -2))

        row = LinearLayout(owner.context)
        row.setOrientation(0)
        row.setGravity(17)
        self.shuffle_button = self.icon_button(("player_new_shuffle",), "Перемешивание", self.toggle_shuffle)
        previous = self.icon_button(("ic_action_previous",), "Предыдущая песня", self.send, "previous")
        self.play_button = self.icon_button(("ic_action_play",), "Воспроизвести", self.toggle)
        following = self.icon_button(("ic_action_next",), "Следующая песня", self.send, "next")
        self.repeat_button = self.icon_button(("player_new_repeat_off",), "Повтор", self.next_repeat)
        for button, size in ((self.shuffle_button, 48), (previous, 56), (self.play_button, 64), (following, 56), (self.repeat_button, 48)):
            place = owner.params(size, size)
            place.setMargins(_dp(6), 0, _dp(6), 0)
            row.addView(button, place)
        self.play_button.setBackground(owner.rounded(owner.color("accent"), _dp(32)))
        self.owner.tint(self.play_button, owner.color("onAccent"))
        place = Params(-1, -2)
        place.setMargins(0, _dp(12), 0, _dp(8))
        self.content.addView(row, place)

    def centered(self, size, role, bold):
        label = self.label(size, role, bold)
        label.setGravity(17)
        label.setSingleLine(False)
        label.setMaxLines(2)
        place = jclass("android.widget.LinearLayout$LayoutParams")(-1, -2)
        place.setMargins(_dp(20), _dp(2), _dp(20), 0)
        self.content.addView(label, place)
        return label

    def dispose(self):
        if self.share.desktop_listener == self.received_from_thread:
            self.share.desktop_listener = None
        if not self.share.enabled():
            self.share.stop()
        self.seek_listener.screen = None
        self.seek.setOnSeekBarChangeListener(None)
        super().dispose()

    # -- what the computer says

    def received_from_thread(self, state):
        run_on_ui_thread(lambda: self.guarded(self.received, state) if self.alive else None)

    def received(self, state):
        self.state = state if isinstance(state, dict) else None
        self.heard_at = time.monotonic()
        self.paint()

    def failed(self, error):
        self.say(str(error))

    def position_ms(self):
        state = self.state
        if state is None:
            return 0
        at = int(state.get("positionMs") or 0)
        if state.get("playing"):
            at += int((time.monotonic() - self.heard_at) * 1000)
        duration = self.duration_ms()
        return min(at, duration) if duration else at

    def duration_ms(self):
        state = self.state or {}
        return int(state.get("durationMs") or (state.get("track") or {}).get("durationMs") or 0)

    def tick(self):
        if not self.alive:
            return
        self.guarded(self.paint_position)
        run_on_ui_thread(self.tick, 1000)

    def paint_position(self):
        duration, at = self.duration_ms(), self.position_ms()
        self.duration.setText(clock(duration // 1000))
        if not self.dragging:
            self.position.setText(clock(at // 1000))
            self.seek.setProgress(int(at * SEEK_STEPS / duration) if duration else 0)

    def paint(self):
        state = self.state or {}
        track = state.get("track")
        self.title.setText((track or {}).get("title") or "На компьютере ничего не играет")
        self.artist.setText((track or {}).get("artist") or ("" if track else "Запусти песню в Mornye на компьютере."))
        playing = bool(state.get("playing"))
        self.owner.set_icon(self.play_button, ("ic_action_pause",) if playing else ("ic_action_play",))
        self.owner.tint(self.play_button, self.owner.color("onAccent"))
        self.play_button.setContentDescription("Пауза" if playing else "Воспроизвести")
        shuffle = bool(state.get("shuffle"))
        self.owner.set_icon(self.shuffle_button, ("player_new_shuffle" if shuffle else "player_new_shuffle_off", "player_new_shuffle"))
        self.owner.tint(self.shuffle_button, self.owner.color("accent" if shuffle else "icon"))
        self.shuffle_button.setContentDescription("Перемешивание: %s" % ("включено" if shuffle else "выключено"))
        repeat = state.get("repeat") if state.get("repeat") in REPEAT_NEXT else "none"
        self.owner.set_icon(self.repeat_button, (REPEAT_ICONS[repeat],))
        self.owner.tint(self.repeat_button, self.owner.color("icon" if repeat == "none" else "accent"))
        self.repeat_button.setContentDescription("Повтор: %s" % REPEAT_WORDS[repeat])
        self.paint_cover(track)
        self.paint_position()
        self.paint_queue(state)

    def paint_cover(self, track):
        """A song the phone has too shows its cover; a song only on the computer stays plain for now."""
        path = self.path_for(track) if track else None
        if path != self.shown_file:
            self.shown_file = path
            self.owner.bind_cover(self.cover, path, COVER_DP)

    def paint_queue(self, state):
        queue = state.get("queue") or []
        index = int(state.get("index", -1))
        coming = [(i, song) for i, song in enumerate(queue) if i > index][:NEXT_ROWS]
        key = [(i, song.get("title"), song.get("artist")) for i, song in coming]
        if key == self.queue_shown:
            return
        self.queue_shown = key
        self.clear_body()
        if coming:
            self.section(self.body, "Дальше")
        for i, song in coming:
            image = self.owner.cover_view(8, 40)
            self.owner.bind_cover(image, self.path_for(song), 40)
            self.item_row(self.body, str(song.get("title") or ""), str(song.get("artist") or ""), lambda n=i: self.send("jump", index=n), image=image)

    # -- what is sent to the computer

    def send(self, action, **args):
        saved = saved_server(self.owner.plugin) or self.saved
        self.background(lambda: link.api_post(saved, "command", {"action": action, "args": args}), lambda _: None, self.failed)

    def toggle(self):
        if self.state is None:
            return
        # shown at once: the computer's own answer follows
        self.state = dict(self.state, playing=not self.state.get("playing"), positionMs=self.position_ms())
        self.heard_at = time.monotonic()
        self.paint()
        self.send("toggle")

    def toggle_shuffle(self):
        if self.state is not None:
            self.send("shuffle", enabled=not self.state.get("shuffle"))

    def next_repeat(self):
        if self.state is not None:
            current = self.state.get("repeat") if self.state.get("repeat") in REPEAT_NEXT else "none"
            self.send("repeat", mode=REPEAT_NEXT[current])

    def dragged(self, value):
        self.position.setText(clock(value * self.duration_ms() // SEEK_STEPS // 1000))

    def released(self, value):
        self.dragging = False
        duration = self.duration_ms()
        if self.state is None or not duration:
            return
        target = value * duration // SEEK_STEPS
        self.state = dict(self.state, positionMs=target)
        self.heard_at = time.monotonic()
        self.send("seek", positionMs=target)
