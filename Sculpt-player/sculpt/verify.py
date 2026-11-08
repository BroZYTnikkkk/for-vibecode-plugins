# SPDX-License-Identifier: LGPL-3.0-only
# Sculpt Player for exteraGram. Copyright 2026 BroNik (@BroZYTnikkkk).
# Based on Mornye Player's signed-session check; Mornye by zarzet (https://github.com/mornyeapp/Mornye), LGPL-3.0-only.

"""A service's session check: its page in a full-screen WebView, the grant it hands back, the downloads retried."""

from urllib.parse import parse_qs, urlsplit

from android_utils import run_on_ui_thread
from base_plugin import MethodHook
from java import dynamic_proxy, jclass
from java.lang import Boolean as JBoolean

from .i18n import tr
from .common import _log

GRANT = "mornye://session-grant"
TICK_MS = 400


class Runnable(dynamic_proxy(jclass("java.lang.Runnable"))):
    def __init__(self, action):
        super().__init__()
        self.action = action

    def run(self):
        if self.action is not None:
            self.action()


class Keys(dynamic_proxy(jclass("android.content.DialogInterface$OnKeyListener"))):
    def __init__(self, action):
        super().__init__()
        self.action = action

    def onKey(self, dialog, code, event):
        if code != 4 or self.action is None:  # KEYCODE_BACK
            return False
        if event.getAction() == 1:
            self.action()
        return True


class Closed(dynamic_proxy(jclass("android.content.DialogInterface$OnDismissListener"))):
    def __init__(self, action):
        super().__init__()
        self.action = action

    def onDismiss(self, dialog):
        action, self.action = self.action, None
        if action is not None:
            action()


class GrantHook(MethodHook):
    """WebViewClient.shouldOverrideUrlLoading: the grant link is caught before the WebView tries to open it."""

    def __init__(self, check):
        super().__init__()
        self.check = check

    def before_hooked_method(self, param):
        check = self.check
        if check is None:
            return
        try:
            target = param.args[1]
            url = str(target.getUrl().toString()) if hasattr(target, "getUrl") else str(target)
        except Exception:
            return
        if check.offer(url):
            param.setResult(JBoolean.TRUE)


class Verification:
    def __init__(self, plugin, ext, pending, on_done):
        self.plugin = plugin
        self.ext = ext
        self.pending = pending
        self.on_done = on_done
        self.done = False
        self.dialog = None
        self.view = None
        self.hooks = []
        self.handler = None
        self.listeners = []

    def start(self):
        activity = jclass("org.telegram.ui.LaunchActivity").instance
        if activity is None:
            return
        self.hook()
        Color = jclass("android.graphics.Color")
        dialog = jclass("android.app.Dialog")(activity, jclass("android.R$style").Theme_Black_NoTitleBar_Fullscreen)
        view = jclass("android.webkit.WebView")(activity)
        settings = view.getSettings()
        settings.setJavaScriptEnabled(True)
        settings.setDomStorageEnabled(True)
        view.setBackgroundColor(Color.parseColor("#0B0B0F"))
        view.setWebViewClient(jclass("android.webkit.WebViewClient")())
        dialog.setContentView(view)
        keys, closed = Keys(self.back), Closed(self.closed)
        self.listeners = [keys, closed]
        dialog.setOnKeyListener(keys)
        dialog.setOnDismissListener(closed)
        self.dialog, self.view = dialog, view
        dialog.show()
        view.loadUrl(self.pending["auth_url"])
        # some pages open the grant link from a script, past shouldOverrideUrlLoading: the address is watched too
        self.handler = jclass("android.os.Handler")(jclass("android.os.Looper").getMainLooper())
        self.handler.postDelayed(Runnable(self.tick), TICK_MS)

    def hook(self):
        try:
            # reflection needs the real java.lang.Class: jclass gives a Python wrapper without getDeclaredMethod
            forName = jclass("java.lang.Class").forName
            client = forName("android.webkit.WebViewClient")
            web_view = forName("android.webkit.WebView")
            for argument in (forName("android.webkit.WebResourceRequest"), forName("java.lang.String")):
                method = client.getDeclaredMethod("shouldOverrideUrlLoading", web_view, argument)
                handle = self.plugin.hook_method(method, GrantHook(self))
                if handle:
                    self.hooks.append(handle)
        except Exception as e:
            _log("grant hook: %s" % e)

    def unhook(self):
        for handle in self.hooks:
            try:
                self.plugin.unhook_method(handle)
            except Exception:
                pass
        self.hooks = []

    def tick(self):
        if self.done or self.view is None:
            return
        try:
            url = self.view.getUrl()
            if url is not None and self.offer(str(url)):
                return
        except Exception:
            pass
        self.handler.postDelayed(Runnable(self.tick), TICK_MS)

    def back(self):
        if self.view is not None and self.view.canGoBack():
            self.view.goBack()
        elif self.dialog is not None:
            self.dialog.dismiss()

    def closed(self):
        self.unhook()
        view, self.view = self.view, None
        if view is not None:
            try:
                view.destroy()
            except Exception:
                pass
        for listener in self.listeners:
            listener.action = None
        self.listeners = []
        if not self.done:
            self.done = True
            self.on_done(None)

    def offer(self, url):
        callback = (self.pending.get("callback") or GRANT).split("?")[0]
        if self.done or not (url.startswith(callback) or url.startswith(GRANT)):
            return False
        query = parse_qs(urlsplit(url).query)
        grant = (query.get("grant") or [""])[0]
        state = (query.get("state") or [""])[0]
        if not grant or (self.pending.get("state") and state != self.pending["state"]):
            _log("session check for %s: wrong answer" % self.ext)
            return True
        self.done = True
        run_on_ui_thread(self.finish_dialog)
        self.on_done(grant)
        return True

    def finish_dialog(self):
        dialog, self.dialog = self.dialog, None
        if dialog is not None:
            dialog.dismiss()


def verify(plugin, ext, name, say, then=None):
    """Asks the service for its check page and opens it; with the grant the extension finishes its session.
    then() runs after a passed check; say(text) reports each step."""
    extensions = plugin.extensions

    def prepare(manager):
        pending = manager.pending_verification(ext)
        if pending is None:
            from .ext.ext_runtime import CallContext
            manager.preflight(ext, CallContext(), download_only=False)
            pending = manager.pending_verification(ext)
        return pending

    def finished(grant):
        if grant is None:
            return
        say(tr("Проверка «%s» пройдена, завершаю…") % name)
        extensions.work(lambda m: m.complete_grant(ext, grant),
                        lambda _: (say(tr("Проверка «%s» пройдена") % name), then() if then is not None else None),
                        lambda text: say(tr("Проверка «%s» не завершилась. %s") % (name, text)))

    def open_page(pending):
        if pending is None or not pending.get("auth_url"):
            say(tr("Сервису «%s» проверка сейчас не нужна. Попробуй скачать снова.") % name)
            return
        Verification(plugin, ext, pending, lambda grant: run_on_ui_thread(lambda: finished(grant))).start()

    extensions.work(prepare, open_page, lambda text: say(tr("Не удалось начать проверку «%s». %s") % (name, text)))
