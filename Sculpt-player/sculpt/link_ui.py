# SPDX-License-Identifier: LGPL-3.0-only
# Sculpt Player for exteraGram. Copyright 2026 BroNik (@BroZYTnikkkk).
# Mornye Link comes from Mornye by zarzet (https://github.com/mornyeapp/Mornye), LGPL-3.0-only.

"""The Mornye Link screen: find the computer, enter its code, see that it answers."""

import collections
import json
import re
import threading

from android_utils import run_on_ui_thread
from java import dynamic_proxy, jarray, jclass

from . import link, link_share, link_stream
from .common import _dp, _log
from .ext_ui import ButtonClick, ExtScreen
from .link_stream import SERVER_KEY, device_id, saved_server

NSD = "android.net.nsd.NsdManager"
PROTOCOL_DNS_SD = 1
ICONS = ("msg2_devices", "menu_devices", "msg_link")
SEARCH_MS = 10000  # after this long without a computer the screen says so


def address_of(server):
    return "%s:%d" % (server["host"], server["port"])


class Discovery(dynamic_proxy(jclass(NSD + "$DiscoveryListener"))):
    def __init__(self, finder):
        super().__init__()
        self.finder = finder

    def onStartDiscoveryFailed(self, kind, code):
        _log("link: discovery failed, %d" % code)

    def onStopDiscoveryFailed(self, kind, code):
        pass

    def onDiscoveryStarted(self, kind):
        pass

    def onDiscoveryStopped(self, kind):
        pass

    def onServiceFound(self, info):
        self.finder.service_found(info)

    def onServiceLost(self, info):
        pass


class Resolved(dynamic_proxy(jclass(NSD + "$ResolveListener"))):
    def __init__(self, finder):
        super().__init__()
        self.finder = finder

    def onResolveFailed(self, info, code):
        self.finder.next_one()

    def onServiceResolved(self, info):
        self.finder.resolved(info)
        self.finder.next_one()


class Finder:
    """Computers announcing Mornye on this network. NsdManager resolves one service at a time, so they queue."""

    def __init__(self, context, found):
        self.manager = context.getSystemService("servicediscovery")
        self.found = found
        self.discovery = Discovery(self)
        self.lock = threading.Lock()
        self.waiting = collections.deque()
        self.busy = False
        self.stopped = False

    def start(self):
        self.manager.discoverServices(link.SERVICE_TYPE, PROTOCOL_DNS_SD, self.discovery)

    def stop(self):
        with self.lock:
            self.stopped = True
            self.waiting.clear()
        try:
            self.manager.stopServiceDiscovery(self.discovery)
        except Exception:
            pass

    def service_found(self, info):
        with self.lock:
            self.waiting.append(info)
        self.resolve_next()

    def next_one(self):
        with self.lock:
            self.busy = False
        self.resolve_next()

    def resolve_next(self):
        with self.lock:
            if self.busy or self.stopped or not self.waiting:
                return
            self.busy = True
            info = self.waiting.popleft()
        self.manager.resolveService(info, Resolved(self))

    def resolved(self, info):
        try:
            hosts = [str(a.getHostAddress()) for a in info.getHostAddresses()]
        except Exception:
            hosts = [str(info.getHost().getHostAddress())]
        hosts = [h for h in hosts if ":" not in h]  # a computer in a VPN too announces every address it has
        port = int(info.getPort())

        def check():
            for host in hosts:
                try:
                    self.found(link.probe(host, port, 3))
                    return
                except link.LinkError:
                    continue
                except Exception as e:
                    _log("link: probe %s" % type(e).__name__)

        threading.Thread(target=check, name="sculpt-link-probe", daemon=True).start()


class LinkBase(ExtScreen):
    def background(self, task, done, failed):
        def finish(action, value):
            run_on_ui_thread(lambda: self.guarded(action, value) if self.alive else None)

        def go():
            try:
                result = task()
            except link.LinkError as e:
                finish(failed, e)
                return
            except Exception as e:
                _log("link: %s" % type(e).__name__)
                finish(failed, link.LinkError("Не получилось связаться с компьютером. Попробуй ещё раз."))
                return
            finish(done, result)

        threading.Thread(target=go, name="sculpt-link", daemon=True).start()


class LinkSongsScreen(LinkBase):
    """The computer's songs, played through Telegram's own player."""

    def __init__(self, owner, saved):
        super().__init__(owner, "Песни компьютера", saved["name"])
        self.page()
        self.tracks = []
        self.start_body()
        self.waiting = self.note(self.body, "Загружаю список песен…", top=12)
        self.background(lambda: link_stream.tracks_of(link.songs(saved)), self.show, self.broke)

    def broke(self, error):
        self.waiting.setText(str(error))

    def show(self, tracks):
        self.tracks = tracks
        if not tracks:
            self.waiting.setText("На компьютере пока нет песен.")
            return
        self.clear_body()
        for index, track in enumerate(tracks):
            self.item_row(self.body, track["title"], track["artist"], lambda i=index: self.play(i))

    def play(self, index):
        self.owner.play(self.tracks, index, "Компьютер")


class LinkScreen(LinkBase):
    def __init__(self, owner):
        super().__init__(owner, "Mornye Link")
        self.page()
        self.plugin = owner.plugin
        self.found = {}
        self.chosen = None
        self.busy = False
        self.gave_up = False
        self.status = None
        self.found_box = None
        self.address_field = None
        self.pin_field = None
        self.connect_button = None
        self.busy_button = None
        self.button_text = ""
        self.status_label = None
        self.share_label = None
        self.finder = None
        self.start_body()
        self.render()
        self.start_search()

    def dispose(self):
        if self.plugin.link_share.on_status == self.share_status:
            self.plugin.link_share.on_status = None
        if self.finder is not None:
            self.finder.stop()
            self.finder = None
        super().dispose()

    def start_search(self):
        try:
            self.finder = Finder(self.owner.context, self.server_found)
            self.finder.start()
        except Exception as e:
            _log("link: search %s" % type(e).__name__)
            self.finder = None
        run_on_ui_thread(lambda: self.guarded(self.search_over) if self.alive else None, SEARCH_MS)

    def search_over(self):
        self.gave_up = True
        self.paint_found()

    def server_found(self, server):
        run_on_ui_thread(lambda: self.guarded(self.add_server, server) if self.alive else None)

    def add_server(self, server):
        saved = saved_server(self.plugin)
        if saved is not None:
            # the computer got a new address from the router: the same certificate says it is the same computer
            same = saved["serverId"] == server["serverId"] and saved["fingerprint"] == server["fingerprint"]
            if same and address_of(saved) != address_of(server):
                saved.update(host=server["host"], port=server["port"])
                self.plugin.set_setting(SERVER_KEY, json.dumps(saved))
                self.render()
            return
        self.found[server["serverId"]] = server
        self.paint_found()

    # -- what the screen shows

    def render(self):
        self.clear_body()
        self.found_box = self.address_field = self.pin_field = self.connect_button = None
        saved = saved_server(self.plugin)
        if saved is not None:
            self.render_paired(saved)
        elif self.chosen is not None:
            self.render_pin(self.chosen)
        else:
            self.render_search()

    def field(self, container, hint, input_type):
        owner = self.owner
        view = jclass("android.widget.EditText")(owner.context)
        view.setSingleLine(True)
        view.setTextSize(1, 16.0)
        view.setInputType(input_type)
        view.setTextColor(owner.color("text"))
        view.setHintTextColor(owner.color("textSecondary"))
        view.setHint(hint)
        view.setContentDescription(hint)
        place = jclass("android.widget.LinearLayout$LayoutParams")(-1, -2)
        place.setMargins(_dp(16), _dp(4), _dp(16), 0)
        container.addView(view, place)
        return view

    def button(self, container, text, filled, action):
        button = self.pill(text, filled, action)
        place = jclass("android.widget.LinearLayout$LayoutParams")(-2, -2)
        place.setMargins(_dp(20), _dp(12), _dp(20), 0)
        container.addView(button, place)
        return button

    def render_search(self):
        body = self.body
        self.note(body, "Подключи Mornye на компьютере, чтобы слушать его песни и управлять им отсюда. Телефон и компьютер должны быть в одной сети.",
                  top=12)
        self.section(body, "Компьютеры рядом")
        self.found_box = jclass("android.widget.LinearLayout")(self.owner.context)
        self.found_box.setOrientation(1)
        body.addView(self.found_box, jclass("android.widget.LinearLayout$LayoutParams")(-1, -2))
        self.paint_found()
        self.section(body, "Адрес вручную")
        self.address_field = self.field(body, "192.168.0.10:47710", 1)
        self.connect_button = self.button(body, "Найти компьютер", False, self.find_by_address)

    def paint_found(self):
        box = self.found_box
        if box is None:
            return
        box.removeAllViews()
        for server in self.found.values():
            self.item_row(box, server["name"], address_of(server), lambda s=server: self.choose(s), icons=ICONS)
        if not self.found:
            self.note(box, "Компьютер не нашёлся. Открой на нём Mornye или введи адрес ниже." if self.gave_up else "Ищу компьютер с Mornye…", top=0)

    def find_by_address(self):
        if self.busy:
            return
        try:
            host, port = link.parse_address(str(self.address_field.getText()))
        except link.LinkError as e:
            self.say(str(e))
            return
        self.set_busy("Ищу…")
        self.background(lambda: link.probe(host, port), self.address_found, self.failed)

    def address_found(self, server):
        self.set_busy(None)
        self.choose(server)

    def choose(self, server):
        self.chosen = server
        self.render()

    def render_pin(self, server):
        body = self.body
        self.item_row(body, server["name"], address_of(server), icons=ICONS)
        self.note(body, "На компьютере открой настройки Mornye Link и нажми «Pair a phone». Введи 6 цифр, которые он покажет.", top=4)
        self.note(body, "Код безопасности на компьютере должен быть %s." % server["fingerprint"][:8])
        self.section(body, "Код с компьютера")
        self.pin_field = self.field(body, "000000", 2)
        length = jclass("android.text.InputFilter$LengthFilter")(6)
        self.pin_field.setFilters(jarray(jclass("android.text.InputFilter"))([length]))
        self.connect_button = self.button(body, "Подключить", True, self.connect)
        self.button(body, "Другой компьютер", False, self.back_to_search)

    def back_to_search(self):
        self.chosen = None
        self.render()

    def connect(self):
        if self.busy:
            return
        pin = str(self.pin_field.getText()).strip()
        if not re.fullmatch(r"\d{6}", pin):
            self.say("Код состоит из 6 цифр.")
            return
        jclass("org.telegram.messenger.AndroidUtilities").hideKeyboard(self.pin_field)
        self.set_busy("Подключаю…")
        server, device = self.chosen, device_id(self.plugin)
        name = "Sculpt Player (%s)" % jclass("android.os.Build").MODEL
        self.background(lambda: link.pair(server, pin, device, name), self.paired, self.failed)

    def paired(self, saved):
        self.set_busy(None)
        link_stream.stop()  # a stream of the previous pairing must not outlive its key
        self.plugin.set_setting(SERVER_KEY, json.dumps(saved))
        self.chosen = None
        self.status = "Подключено."
        self.render()
        self.say("Компьютер %s подключён." % saved["name"], "contact_check")

    def failed(self, error):
        self.set_busy(None)
        self.say(str(error))

    def set_busy(self, text):
        self.busy = text is not None
        if text is None:
            # the button that was changed: the screen may have been rebuilt since, with another one in its place
            if self.busy_button is not None:
                self.busy_button.setText(self.button_text)
            self.busy_button = None
        elif self.connect_button is not None:
            self.busy_button = self.connect_button
            self.button_text = str(self.busy_button.getText())
            self.busy_button.setText(text)

    def render_paired(self, saved):
        body = self.body
        self.item_row(body, saved["name"], address_of(saved), icons=ICONS)
        self.status_label = self.note(body, self.status or "Проверяю связь…", top=4)
        self.section(body, "Песни телефона")
        share = self.plugin.link_share
        switch = self.switch(share.enabled(), self.toggle_share, "Показывать песни на компьютере")
        _, _, self.share_label = self.item_row(body, "Показывать песни на компьютере", share.status, trailing=switch)
        share.on_status = self.share_status
        self.section(body, "Песни компьютера")
        self.nav_row(body, ("msg_filled_music", "msg_music", "msg_audio"), "Песни компьютера",
                     lambda: self.owner.push(LinkSongsScreen(self.owner, saved)))
        self.connect_button = self.button(body, "Проверить связь", False, self.check)
        self.button(body, "Забыть компьютер", False, self.confirm_forget)
        self.check()

    def share_status(self, text):
        if self.alive and self.share_label is not None:
            self.share_label.setText(text)

    def toggle_share(self, enabled):
        share = self.plugin.link_share
        self.plugin.set_setting(link_share.SETTING, bool(enabled))
        if enabled:
            share.start()
        else:
            share.stop(clear=True)

    def check(self):
        if self.busy:
            return
        saved = saved_server(self.plugin)
        if saved is None:
            return
        self.set_busy("Проверяю…")
        self.background(lambda: link.ping(saved), self.answered, self.silent)

    def answered(self, _):
        self.set_busy(None)
        self.status = "На связи."
        self.status_label.setText(self.status)

    def silent(self, error):
        self.set_busy(None)
        self.status = str(error)
        self.status_label.setText(self.status)

    def confirm_forget(self):
        saved = saved_server(self.plugin)
        builder = jclass("org.telegram.ui.ActionBar.AlertDialog$Builder")(self.owner.context)
        builder.setTitle("Забыть «%s»?" % saved["name"])
        builder.setMessage("Телефон отключится от этого компьютера. В списке устройств на компьютере он останется, убрать его можно там.")
        builder.setPositiveButton("Забыть", ButtonClick(self.forget))
        builder.setNegativeButton("Отмена", ButtonClick(None))
        dialog = builder.create()
        dialog.show()
        button = dialog.getButton(-1)
        if button is not None:
            Theme = jclass("org.telegram.ui.ActionBar.Theme")
            button.setTextColor(Theme.getColor(Theme.key_text_RedBold))

    def forget(self):
        share = self.plugin.link_share
        if share.enabled():
            share.stop(clear=True)
            self.plugin.set_setting(link_share.SETTING, False)
        self.plugin.set_setting(SERVER_KEY, "")
        self.status = None
        self.gave_up = False
        self.found = {}
        self.render()
        if self.finder is not None:
            self.finder.stop()
        self.start_search()
