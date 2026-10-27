# SPDX-License-Identifier: LGPL-3.0-only
# Mornye Player for exteraGram. Copyright 2026 BroNik (@BroZYTnikkkk).
# Based on Mornye by zarzet (https://github.com/mornyeapp/Mornye), LGPL-3.0-only.

"""Full-screen window and signed-session verification."""

import time
from base_plugin import MethodHook
from client_utils import run_on_queue
from ui.bulletin import BulletinHelper
from urllib.parse import parse_qs, urlsplit
from android.os import Build
from android_utils import log, run_on_ui_thread
from java import dynamic_proxy, jclass
from java.lang import Boolean as JBoolean


# ---------------------------------------------------------------------------
# Full-screen window and signed-session verification
# ---------------------------------------------------------------------------


class _KeyListener(dynamic_proxy(jclass("android.content.DialogInterface$OnKeyListener"))):
    def __init__(self, fn):
        super().__init__()
        self.fn = fn

    def onKey(self, dialog, key_code, event):
        try:
            return bool(self.fn(key_code, event))
        except Exception as e:
            log("[Mornye] key: %s" % e)
            return False


class _DismissListener(dynamic_proxy(jclass("android.content.DialogInterface$OnDismissListener"))):
    def __init__(self, fn):
        super().__init__()
        self.fn = fn

    def onDismiss(self, dialog):
        try:
            self.fn()
        except Exception:
            pass


class _ValueCallback(dynamic_proxy(jclass("android.webkit.ValueCallback"))):
    def __init__(self, fn):
        super().__init__()
        self.fn = fn

    def onReceiveValue(self, value):
        try:
            self.fn(str(value) if value is not None else "")
        except Exception:
            pass


_BACK_CALLBACK = {}


def _back_callback(fn):
    """OnBackInvokedCallback (Android 13+); with predictive back the key listener never sees Back."""
    cls = _BACK_CALLBACK.get("cls")
    if cls is None:
        class _Back(dynamic_proxy(jclass("android.window.OnBackInvokedCallback"))):
            def __init__(self, fn):
                super().__init__()
                self.fn = fn

            def onBackInvoked(self):
                try:
                    self.fn()
                except Exception as e:
                    log("[Mornye] back: %s" % e)
        cls = _BACK_CALLBACK["cls"] = _Back
    return cls(fn)


def fullscreen_webview(activity, url, on_back=None, on_close=None):
    """A full-screen dialog holding one WebView; Back goes to on_back first."""
    Dialog = jclass("android.app.Dialog")
    WebView = jclass("android.webkit.WebView")
    Color = jclass("android.graphics.Color")
    style = jclass("android.R$style").Theme_Black_NoTitleBar_Fullscreen
    dialog = Dialog(activity, style)
    view = WebView(activity)
    settings = view.getSettings()
    settings.setJavaScriptEnabled(True)
    settings.setDomStorageEnabled(True)
    settings.setMediaPlaybackRequiresUserGesture(False)
    view.setBackgroundColor(Color.parseColor("#0B0B0F"))
    view.setWebViewClient(jclass("android.webkit.WebViewClient")())
    dialog.setContentView(view)
    window = dialog.getWindow()
    try:
        window.setStatusBarColor(Color.parseColor("#0B0B0F"))
        window.setNavigationBarColor(Color.parseColor("#0B0B0F"))
    except Exception:
        pass

    last = [0.0]

    def back():
        # The key listener and the back callback can both fire on some builds.
        now = time.time()
        if now - last[0] < 0.3:
            return
        last[0] = now
        if on_back is None:
            dialog.dismiss()
        else:
            on_back(view, dialog)

    def on_key(code, event):
        if code != 4:
            return False
        if event.getAction() == 1:
            back()
        return True

    def closed():
        try:
            view.destroy()
        except Exception:
            pass
        if on_close:
            on_close()

    dialog.setCancelable(False)
    dialog.setOnKeyListener(_KeyListener(on_key))
    dialog.setOnDismissListener(_DismissListener(closed))
    dialog.show()
    if Build.VERSION.SDK_INT >= 33:
        try:
            # Registered after show() so it sits above the dialog's own default callback.
            dialog.getOnBackInvokedDispatcher().registerOnBackInvokedCallback(0, _back_callback(back))
        except Exception as e:
            log("[Mornye] back callback: %s" % e)
    view.loadUrl(url)
    return dialog, view


_VERIFY = {"active": None}


class _GrantUrlHook(MethodHook):
    """Catches the mornye://session-grant callback inside the verification page."""

    def before_hooked_method(self, param):
        active = _VERIFY.get("active")
        if active is None:
            return
        try:
            target = param.args[1]
            url = str(target.getUrl().toString()) if hasattr(target, "getUrl") else str(target)
        except Exception:
            return
        if active.offer(url):
            param.setResult(JBoolean.TRUE)


class _Verification:
    def __init__(self, plugin, ext, pending):
        self.plugin = plugin
        self.ext = ext
        self.pending = pending
        self.done = False
        self.dialog = None

    def offer(self, url):
        callback = (self.pending.get("callback") or "mornye://session-grant").split("?")[0]
        if self.done or not (url.startswith(callback) or url.startswith("mornye://session-grant")):
            return False
        query = parse_qs(urlsplit(url).query)
        grant = (query.get("grant") or [""])[0]
        state = (query.get("state") or [""])[0]
        if not grant or (self.pending.get("state") and state != self.pending["state"]):
            run_on_ui_thread(lambda: BulletinHelper.show_error("Mornye: проверка вернула неверный ответ"))
            return True
        self.done = True
        _VERIFY["active"] = None
        dialog = self.dialog
        if dialog is not None:
            run_on_ui_thread(lambda: dialog.dismiss())

        def work():
            try:
                self.plugin.extensions().complete_grant(self.ext, grant)
                run_on_ui_thread(lambda: BulletinHelper.show_success("Mornye: проверка пройдена, повторите загрузку"))
            except Exception as e:
                err = str(e)
                run_on_ui_thread(lambda: BulletinHelper.show_error("Mornye: %s" % err))
        run_on_queue(work)
        return True
