# SPDX-License-Identifier: LGPL-3.0-only
# Sculpt Player for exteraGram. Copyright 2026 BroNik (@BroZYTnikkkk).
# Mornye extensions come from Mornye by zarzet (https://github.com/mornyeapp/Mornye), LGPL-3.0-only.

"""The Mornye tab's extension screens: installed ones, the catalog, the repositories, one extension."""

from android_utils import run_on_ui_thread
from java import dynamic_proxy, jarray, jclass, jint

from .i18n import tr
from .common import _dp, advanced
from .extensions import describe, type_names
from .library_ui import Screen, TextChanged

SAVE_DELAY_MS = 800  # a typed setting is saved this long after the last letter


class Checked(dynamic_proxy(jclass("android.widget.CompoundButton$OnCheckedChangeListener"))):
    def __init__(self, action):
        super().__init__()
        self.action = action

    def onCheckedChanged(self, button, checked):
        if self.action is not None:
            self.action(bool(checked))


class ButtonClick(dynamic_proxy(jclass("org.telegram.ui.ActionBar.AlertDialog$OnButtonClickListener"))):
    def __init__(self, action):
        super().__init__()
        self.action = action

    def onClick(self, dialog, which):
        action, self.action = self.action, None
        if action is not None:
            action()


class ExtScreen(Screen):
    """A header over a scrolling column; a part of the column is rebuilt from data loaded off the UI thread."""

    def __init__(self, owner, title, subtitle=""):
        super().__init__(owner, title, subtitle)
        self.alive = True
        self.switches = []
        self.watchers = []
        self.content = None
        self.body = None
        self.marks = (0, 0, 0, 0)

    def page(self, trailing=None):
        owner = self.owner
        LinearLayout = jclass("android.widget.LinearLayout")
        Params = jclass("android.widget.LinearLayout$LayoutParams")
        page = LinearLayout(owner.context)
        page.setOrientation(1)
        page.addView(self.header(False, trailing))
        scroll = jclass("android.widget.ScrollView")(owner.context)
        scroll.setVerticalScrollBarEnabled(False)
        scroll.setOverScrollMode(2)
        self.content = LinearLayout(owner.context)
        self.content.setOrientation(1)
        self.content.setPadding(0, 0, 0, _dp(24))
        scroll.addView(self.content)
        page.addView(scroll, Params(-1, 0, 1.0))
        self.view = page

    def start_body(self):
        """Everything added to self.body after this is the rebuilt part."""
        self.body = jclass("android.widget.LinearLayout")(self.owner.context)
        self.body.setOrientation(1)
        self.content.addView(self.body, jclass("android.widget.LinearLayout$LayoutParams")(-1, -2))
        self.marks = (len(self.keep), len(self.tints), len(self.switches), len(self.watchers))

    def clear_body(self):
        keep, tints, switches, watchers = self.marks
        self.release(self.keep[keep:], self.switches[switches:], self.watchers[watchers:])
        del self.keep[keep:]
        del self.tints[tints:]
        del self.switches[switches:]
        del self.watchers[watchers:]
        self.body.removeAllViews()

    @staticmethod
    def release(keep, switches, watchers):
        for view, kind in keep:
            try:
                if kind == "click":
                    view.setOnClickListener(None)
                else:
                    view.setOnLongClickListener(None)
            except Exception:
                pass
        for switch, listener in switches:
            listener.action = None
            try:
                switch.setOnCheckedChangeListener(None)
            except Exception:
                pass
        for field, watcher in watchers:
            watcher.action = None
            try:
                field.removeTextChangedListener(watcher)
            except Exception:
                pass

    def dispose(self):
        self.alive = False
        self.release([], self.switches, self.watchers)
        self.switches = []
        self.watchers = []
        super().dispose()

    # -- work off the UI thread

    def run(self, task, done, failed=None):
        def finished(result):
            if self.alive:
                self.guarded(done, result)

        def broke(text):
            if not self.alive:
                return
            if failed is not None:
                self.guarded(failed, text)
            else:
                self.say(text)

        self.owner.plugin.extensions.work(task, finished, broke)

    def say(self, text, animation="info"):
        self.owner.plugin.bulletin(self.owner.player.sheet, animation, text)

    # -- building blocks

    def note(self, container, text, role="textSecondary", size=14, top=8):
        label = self.label(size, role)
        label.setSingleLine(False)
        label.setText(text)
        place = jclass("android.widget.LinearLayout$LayoutParams")(-1, -2)
        place.setMargins(_dp(20), _dp(top), _dp(20), 0)
        container.addView(label, place)
        return label

    def section(self, container, title):
        label = self.label(14, "accent", True)
        label.setText(title)
        place = jclass("android.widget.LinearLayout$LayoutParams")(-1, -2)
        place.setMargins(_dp(20), _dp(24), _dp(20), _dp(4))
        container.addView(label, place)
        return label

    def item_row(self, container, title, subtitle, action=None, image=None, icons=None, trailing=None, title_role="text"):
        """A row of a list: an image or an icon, two lines, something at the end. Returns (row, title, subtitle)."""
        owner = self.owner
        Params = jclass("android.widget.LinearLayout$LayoutParams")
        row = jclass("android.widget.LinearLayout")(owner.context)
        row.setOrientation(0)
        row.setGravity(16)
        row.setPadding(_dp(20), _dp(10), _dp(16), _dp(10))
        row.setMinimumHeight(_dp(56))
        if image is not None:
            row.addView(image, owner.params(40, 40))
        elif icons is not None:
            icon = jclass("android.widget.ImageView")(owner.context)
            owner.set_icon(icon, icons)
            self.tint_icon(icon, "icon")
            row.addView(icon, owner.params(24, 24))
        column = jclass("android.widget.LinearLayout")(owner.context)
        column.setOrientation(1)
        name = self.label(16, title_role)
        name.setText(title)
        column.addView(name)
        second = None
        if subtitle:
            second = self.label(13, "textSecondary")
            second.setSingleLine(False)
            second.setMaxLines(3)
            second.setText(subtitle)
            column.addView(second)
        place = Params(0, -2, 1.0)
        if image is not None or icons is not None:
            place.setMarginStart(_dp(16))
        row.addView(column, place)
        if trailing is not None:
            at = Params(-2, -2)
            at.setMarginStart(_dp(12))
            row.addView(trailing, at)
        if action is not None:
            row.setBackground(owner.selector(0))
            self.click(row, action)
        container.addView(row, Params(-1, -2))
        return row, name, second

    def fold_header(self, container, icons, title, subtitle, action):
        """The head of a folding block, the way "Search the internet" looks: an icon, the name with a line under it,
        an arrow that turns when it opens. Returns (head, arrow)."""
        owner = self.owner
        Params = jclass("android.widget.LinearLayout$LayoutParams")
        head = jclass("android.widget.LinearLayout")(owner.context)
        head.setOrientation(0)
        head.setGravity(16)
        head.setPadding(_dp(20), _dp(12), _dp(16), _dp(12))
        head.setBackground(owner.rounded(owner.color("surfaceContainer"), _dp(20)))
        icon = jclass("android.widget.ImageView")(owner.context)
        owner.set_icon(icon, icons)
        self.tint_icon(icon, "accent")
        head.addView(icon, owner.params(22, 22))
        column = jclass("android.widget.LinearLayout")(owner.context)
        column.setOrientation(1)
        name = self.label(16, "text", True)
        name.setText(title)
        column.addView(name)
        if subtitle:
            second = self.label(13, "textSecondary")
            second.setText(subtitle)
            column.addView(second)
        at = Params(0, -2, 1.0)
        at.setMarginStart(_dp(12))
        head.addView(column, at)
        arrow = jclass("android.widget.ImageView")(owner.context)
        owner.set_icon(arrow, ("arrow_more", "msg_arrow_more"))
        self.tint_icon(arrow, "textSecondary")
        head.addView(arrow, owner.params(20, 20))
        head.setContentDescription(tr("%s, развернуть") % title)
        self.click(head, action)
        place = Params(-1, -2)
        place.setMargins(_dp(12), _dp(12), _dp(12), _dp(4))
        container.addView(head, place)
        return head, arrow

    def switch(self, checked, action, description):
        owner = self.owner
        view = jclass("android.widget.Switch")(owner.context)
        view.setChecked(bool(checked))
        view.setContentDescription(description)
        States = jclass("android.content.res.ColorStateList")
        ColorUtils = jclass("androidx.core.graphics.ColorUtils")

        def colors(checked, unchecked):
            states = jarray(jarray(jint))([[16842912], []])  # android.R.attr.state_checked, then any other
            return States(states, jarray(jint)([checked, unchecked]))

        view.setThumbTintList(colors(owner.color("accent"), owner.color("icon")))
        view.setTrackTintList(colors(ColorUtils.setAlphaComponent(owner.color("accent"), 110),
                                     ColorUtils.setAlphaComponent(owner.color("icon"), 70)))
        listener = Checked(lambda on: self.guarded(action, on))
        view.setOnCheckedChangeListener(listener)
        self.switches.append((view, listener))
        return view

    def pill(self, text, filled, action):
        """A small button at the end of a row. While its work runs, it keeps its strength and changes its words."""
        owner = self.owner
        button = self.label(14, "onAccent" if filled else "accent", True)
        button.setText(text)
        button.setGravity(17)
        button.setPadding(_dp(16), _dp(8), _dp(16), _dp(8))
        button.setMinHeight(_dp(36))
        if filled:
            button.setBackground(owner.rounded(owner.color("accent"), _dp(18)))
        else:
            frame = jclass("android.graphics.drawable.GradientDrawable")()
            frame.setCornerRadius(float(_dp(18)))
            frame.setStroke(_dp(1), owner.color("accent"))
            button.setBackground(frame)
        if action is not None:
            self.click(button, action)
        return button

    def icon_image(self, path):
        """An extension's own icon, or the plugin icon when it has none."""
        owner = self.owner
        bitmap = None
        if path:
            try:
                bitmap = jclass("android.graphics.BitmapFactory").decodeFile(path)
            except Exception:
                bitmap = None
        if bitmap is not None:
            image = jclass("org.telegram.ui.Components.BackupImageView")(owner.context)
            image.setRoundRadius(_dp(10))
            image.setImageBitmap(bitmap)
            return image
        image = jclass("android.widget.ImageView")(owner.context)
        image.setScaleType(jclass("android.widget.ImageView$ScaleType").CENTER)
        image.setBackground(owner.rounded(owner.color("surfaceContainer"), _dp(10)))
        owner.set_icon(image, ("msg_plugins", "msg_bots"))
        self.tint_icon(image, "icon")
        return image


class ExtensionsScreen(ExtScreen):
    """Installed extensions, with the ways to get more."""

    def __init__(self, owner):
        super().__init__(owner, tr("Расширения"))
        self.page()
        self.nav_row(self.content, ("msg_plugins", "msg_bots"), tr("Каталог расширений"), owner.open_catalog)
        # where extensions come from is for the curious: the official catalog is enough for everyone else
        self.repo_count = None
        if advanced(owner.plugin):
            self.repo_count = self.nav_row(self.content, ("msg_link", "msg_link2"), tr("Репозитории"), owner.open_repos)
        self.nav_row(self.content, ("msg_settings",), tr("Скачивание"), owner.open_download_settings)
        self.section(self.content, tr("Установленные"))
        self.start_body()
        self.note(self.content, tr("Расширение можно установить и из файла .sflx в любом чате: зажми сообщение с файлом "
                                "и выбери «Установить расширение»."), top=20)
        self.status = self.note(self.body, tr("Загружаю…"))
        self.refresh()

    def refresh(self):
        self.run(lambda m: (m.installed(), list(m.state.get("repos") or [])), self.show)

    def show(self, data):
        items, repos = data
        self.clear_body()
        if self.repo_count is not None:
            self.repo_count.setText(str(len(repos)))
        self.set_subtitle(str(len(items)) if items else "")
        if not items:
            self.note(self.body, tr("Пока ничего не установлено. В каталоге есть расширения, которые ищут и скачивают песни: "
                                 "открой его и выбери нужное."), size=15)
            return
        for item in items:
            ext = item["id"]
            details = "v%s · %s" % (item["version"], type_names(item["types"]))
            if item.get("error"):
                details += tr("\nОшибка: %s") % item["error"]
            switch = self.switch(item["enabled"], lambda on, e=ext: self.toggle(e, on),
                                 "%s: %s" % (item["name"], tr("включено") if item["enabled"] else tr("выключено")))
            self.item_row(self.body, item["name"], details, lambda e=ext: self.owner.open_extension(e),
                          image=self.icon_image(item.get("icon")), trailing=switch)

    def toggle(self, ext, on):
        self.run(lambda m: m.set_enabled(ext, on), lambda _: None, lambda text: (self.say(text), self.refresh()))


class CatalogScreen(ExtScreen):
    """What the repositories offer; a button installs or updates one."""

    def __init__(self, owner):
        super().__init__(owner, tr("Каталог"))
        self.page(self.icon_button(("msg_link", "msg_link2"), tr("Репозитории"), owner.open_repos) if advanced(owner.plugin) else None)
        self.busy = set()
        self.items = []
        self.errors = []
        self.repos = []
        self.start_body()
        self.refresh()

    def refresh(self):
        self.clear_body()
        self.note(self.body, tr("Загружаю каталог…"), size=15)

        def task(manager):
            urls = list(manager.state.get("repos") or [])
            items, errors = [], []
            for url in urls:
                try:
                    for item in manager.fetch_registry(url):
                        item["repo"] = url
                        items.append(item)
                except Exception as e:
                    errors.append(describe(e))
            return items, errors, urls

        self.run(task, self.loaded)

    def loaded(self, data):
        self.items, self.errors, self.repos = data
        self.draw()

    def draw(self):
        self.clear_body()
        for text in self.errors:
            self.note(self.body, text, "accent")
        if not self.repos:
            self.note(self.body, tr("Нет ни одного репозитория. Добавь ссылку на каталог расширений в «Репозиториях»."), size=15)
            return
        if not self.items and not self.errors:
            self.note(self.body, tr("В этих репозиториях пока нет расширений."), size=15)
        for item in self.items:
            ext = item["id"]
            name = item.get("display_name") or item.get("displayName") or item.get("name") or ext
            if ext in self.busy:
                button = self.pill(tr("Устанавливаю…"), True, None)
            elif item.get("has_update"):
                button = self.pill(tr("Обновить"), True, lambda i=item: self.install(i))
            elif item.get("installed_version"):
                button = self.pill(tr("Установлено"), False, lambda e=ext: self.owner.open_extension(e))
            else:
                button = self.pill(tr("Установить"), True, lambda i=item: self.install(i))
            button.setContentDescription("%s: %s" % (name, button.getText()))
            details = item.get("description") or ""
            version = item.get("version")
            if version:
                details = ("v%s · %s" % (version, details)) if details else "v%s" % version
            self.item_row(self.body, name, details, trailing=button, icons=("msg_plugins", "msg_bots"))
        sources = "\n".join(self.repos)
        self.note(self.body, tr("Источники:\n%s\nАвторы расширений указаны в их пакетах (LICENSE, NOTICE).") % sources, size=12, top=20)

    def install(self, item):
        ext = item["id"]
        name = item.get("display_name") or item.get("displayName") or item.get("name") or ext
        self.busy.add(ext)
        self.draw()

        def done(_):
            self.busy.discard(ext)
            item["installed_version"] = item.get("version") or ""
            item["has_update"] = False
            self.draw()
            self.say(tr("Расширение «%s» установлено") % name, "saved_messages")

        def failed(text):
            self.busy.discard(ext)
            self.draw()
            self.say(tr("«%s» не установлено. %s") % (name, text))

        self.run(lambda m: m.install_from_registry(item), done, failed)


class ReposScreen(ExtScreen):
    """The catalogs the extensions come from: the official one, and any added by link."""

    def __init__(self, owner):
        super().__init__(owner, tr("Репозитории"))
        self.page()
        self.adding = False
        self.note(self.content, tr("Ссылка на GitHub-репозиторий с registry.json или на сам файл registry.json."), top=4)
        Params = jclass("android.widget.LinearLayout$LayoutParams")
        line = jclass("android.widget.LinearLayout")(owner.context)
        line.setOrientation(0)
        line.setGravity(16)
        line.setPadding(_dp(20), _dp(8), _dp(16), _dp(8))
        self.field = jclass("android.widget.EditText")(owner.context)
        self.field.setHint("https://github.com/…")
        self.field.setTextSize(1, 15.0)
        self.field.setSingleLine(True)
        self.field.setTextColor(owner.color("text"))
        self.field.setHintTextColor(owner.color("textSecondary"))
        line.addView(self.field, Params(0, -2, 1.0))
        self.add_button = self.pill(tr("Добавить"), True, self.add)
        at = Params(-2, -2)
        at.setMarginStart(_dp(8))
        line.addView(self.add_button, at)
        self.content.addView(line, Params(-1, -2))
        self.section(self.content, tr("Добавленные"))
        self.start_body()
        self.refresh()

    def colors_changed(self):
        self.field.setTextColor(self.owner.color("text"))
        self.field.setHintTextColor(self.owner.color("textSecondary"))

    def refresh(self):
        self.run(lambda m: list(m.state.get("repos") or []), self.show)

    def show(self, repos):
        self.clear_body()
        if not repos:
            self.note(self.body, tr("Ни одного репозитория. Без них каталог пуст."), size=15)
        for url in repos:
            remove = self.icon_button(("msg_delete",), tr("Убрать репозиторий %s") % url, self.remove, url)
            self.item_row(self.body, url.replace("https://", ""), "", trailing=remove)

    def remove(self, url):
        def task(manager):
            with manager.lock:
                manager.state["repos"] = [r for r in manager.state["repos"] if r != url]
                manager.save_state()

        self.run(task, lambda _: (self.say(tr("Репозиторий убран"), "ic_delete"), self.refresh()))

    def add(self):
        url = str(self.field.getText()).strip()
        if not url or self.adding:
            if not url:
                self.say(tr("Вставь ссылку на репозиторий."))
            return
        self.adding = True
        self.add_button.setText(tr("Проверяю…"))

        def task(manager):
            items = manager.fetch_registry(url)
            with manager.lock:
                if url not in manager.state["repos"]:
                    manager.state["repos"].append(url)
                manager.save_state()
            return len(items)

        def done(count):
            self.adding = False
            self.add_button.setText(tr("Добавить"))
            self.field.setText("")
            self.say(tr("Репозиторий добавлен, расширений в нём: %d") % count, "saved_messages")
            self.refresh()

        def failed(text):
            self.adding = False
            self.add_button.setText(tr("Добавить"))
            self.say(tr("Репозиторий не добавлен. ") + text)

        self.run(task, done, failed)


class ExtensionScreen(ExtScreen):
    """One extension: what it is, on or off, its settings, removing it, its log."""

    def __init__(self, owner, ext):
        super().__init__(owner, tr("Расширение"))
        self.ext = ext
        self.values = {}
        self.save_generation = 0
        self.pending = False
        self.page()
        self.start_body()
        self.note(self.body, tr("Загружаю…"))
        self.refresh()

    def refresh(self):
        ext = self.ext

        def task(manager):
            man = manager.manifest(ext)
            if man is None:
                return None
            return {"name": man.display_name, "version": man.version, "description": man.description,
                    "homepage": man.homepage, "types": list(man.types), "settings": list(man.settings),
                    "values": manager.settings(ext), "enabled": manager.is_enabled(ext), "signed": bool(man.signed_session),
                    "error": manager.state["errors"].get(ext, ""),
                    "logs": [(e[1], e[3]) for e in list(manager.logs) if e[2] == ext][-30:]}

        self.run(task, self.show)

    def show(self, data):
        self.clear_body()
        if data is None:
            self.note(self.body, tr("Этого расширения больше нет."), size=15)
            return
        self.title_view.setText(data["name"])
        self.set_subtitle("v%s · %s" % (data["version"], type_names(data["types"])))
        self.values = dict(data["values"])
        self.note(self.body, data["description"], "text", 15, top=4)
        if data["homepage"]:
            self.item_row(self.body, tr("Сайт расширения"), data["homepage"].replace("https://", ""),
                          lambda: self.owner.open_link(data["homepage"]), icons=("msg_link", "msg_link2"))
        switch = self.switch(data["enabled"], self.toggle, tr("Расширение включено"))
        self.item_row(self.body, tr("Включено"), tr("Выключенное расширение не ищет и не скачивает."), trailing=switch)
        if data["signed"]:
            self.item_row(self.body, tr("Проверка сессии"), tr("Сервис иногда просит подтвердить, что качает человек. "
                                                         "Откроется его страница; после проверки загрузки пойдут снова."),
                          lambda: self.check(data["name"]), icons=("msg_permissions", "msg_secret", "msg_info"))
        if data["error"]:
            self.note(self.body, tr("Последняя ошибка: %s") % data["error"], "accent")
        if data["settings"]:
            self.section(self.body, tr("Настройки"))
            for setting in data["settings"]:
                self.setting(setting)
        self.section(self.body, tr("Удаление"))
        self.item_row(self.body, tr("Удалить расширение"), tr("Вместе с его настройками и данными на телефоне."),
                      self.confirm_remove, icons=("msg_delete",))
        if data["logs"] and advanced(self.owner.plugin):
            self.section(self.body, tr("Журнал"))
            log = self.note(self.body, "\n".join("%s %s" % (level, text) for level, text in data["logs"]), size=12, top=0)
            log.setTypeface(jclass("android.graphics.Typeface").MONOSPACE)
            log.setTextIsSelectable(True)

    def toggle(self, on):
        self.run(lambda m: m.set_enabled(self.ext, on), lambda _: None, lambda text: (self.say(text), self.refresh()))

    def check(self, name):
        from .verify import verify
        verify(self.owner.plugin, self.ext, name, self.say)

    # -- settings, the way Mornye's own screen shows them

    def setting(self, setting):
        key = str(setting.get("key") or "")
        if not key:
            return
        label = str(setting.get("label") or key)
        hint = str(setting.get("description") or "")
        kind = str(setting.get("type") or "string")
        value = self.values.get(key, setting.get("default"))
        if kind == "button":
            self.item_row(self.body, label, hint, lambda: self.action(str(setting.get("action") or key), label),
                          icons=("msg_played",))
        elif kind in ("bool", "boolean"):
            switch = self.switch(bool(value), lambda on: self.change(key, on), label)
            self.item_row(self.body, label, hint, trailing=switch)
        elif kind == "select":
            options = [o if isinstance(o, dict) else {"value": o, "label": o} for o in (setting.get("options") or [])]
            current = next((str(o.get("label") or o.get("value")) for o in options if str(o.get("value")) == str(value)), str(value or ""))
            row, _, second = self.item_row(self.body, label, current or tr("Не выбрано"), None)
            self.click(row, self.choose, row, key, options)
            row.setBackground(self.owner.selector(0))
            if hint:
                self.note(self.body, hint, size=12, top=0)
        else:
            self.text_setting(key, label, hint, kind, value, bool(setting.get("secret")), str(setting.get("placeholder") or ""))

    def text_setting(self, key, label, hint, kind, value, secret, placeholder):
        owner = self.owner
        title = self.note(self.body, label, "text", 15, top=12)
        title.setSingleLine(True)
        field = jclass("android.widget.EditText")(owner.context)
        field.setTextSize(1, 15.0)
        field.setSingleLine(True)
        field.setText("" if value is None else str(value))
        field.setHint(placeholder)
        field.setTextColor(owner.color("text"))
        field.setHintTextColor(owner.color("textSecondary"))
        InputType = jclass("android.text.InputType")
        if secret:
            field.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD)
        elif kind == "number":
            field.setInputType(InputType.TYPE_CLASS_NUMBER | InputType.TYPE_NUMBER_FLAG_DECIMAL | InputType.TYPE_NUMBER_FLAG_SIGNED)
        field.setContentDescription(label)
        place = jclass("android.widget.LinearLayout$LayoutParams")(-1, -2)
        place.setMargins(_dp(16), 0, _dp(16), 0)
        self.body.addView(field, place)

        def typed(text):
            if kind == "number":
                try:
                    number = float(text.replace(",", "."))
                    self.values[key] = int(number) if number.is_integer() else number
                except ValueError:
                    return
            else:
                self.values[key] = text
            self.save_later()

        watcher = TextChanged(lambda text: self.guarded(typed, text))
        field.addTextChangedListener(watcher)
        self.watchers.append((field, watcher))
        if hint:
            self.note(self.body, hint, size=12, top=0)

    def choose(self, row, key, options):
        owner = self.owner
        menu = owner.make_menu(row, False)
        later = owner.player.start_menu()
        check = owner.resource("msg_text_check")
        for option in options:
            value = option.get("value")
            menu.add(check if str(value) == str(self.values.get(key)) else 0, str(option.get("label") or value),
                     later(lambda v=value: (menu.dismiss(), self.change(key, v, self.refresh))))
        owner.player.show_menu(menu)

    def change(self, key, value, then=None):
        self.values[key] = value
        self.pending = False
        values, ext = dict(self.values), self.ext
        self.run(lambda m: m.update_settings(ext, values), lambda _: then() if then is not None else None)

    def save_later(self):
        self.save_generation += 1
        generation = self.save_generation
        self.pending = True
        run_on_ui_thread(lambda: generation == self.save_generation and self.save_now(), SAVE_DELAY_MS)

    def save_now(self):
        self.pending = False
        values, ext = dict(self.values), self.ext
        self.owner.plugin.extensions.work(lambda m: m.update_settings(ext, values))

    def action(self, name, label):
        def done(result):
            text = ""
            if isinstance(result, dict):
                text = str(result.get("message") or result.get("error") or "")
            elif isinstance(result, str):
                text = result
            self.say(text or tr("«%s»: готово") % label)

        self.say(tr("«%s»: выполняю…") % label)
        self.run(lambda m: m.action(self.ext, name), done)

    def confirm_remove(self):
        owner = self.owner
        name = str(self.title_view.getText())
        Builder = jclass("org.telegram.ui.ActionBar.AlertDialog$Builder")
        builder = Builder(owner.context)
        builder.setTitle(tr("Удалить «%s»?") % name)
        builder.setMessage(tr("Расширение, его настройки и данные удалятся с телефона. Вернуть его можно, только установив заново."))
        builder.setPositiveButton(tr("Удалить"), ButtonClick(lambda: self.remove(name)))
        builder.setNegativeButton(tr("Отмена"), ButtonClick(None))
        dialog = builder.create()
        dialog.show()
        button = dialog.getButton(-1)
        if button is not None:
            Theme = jclass("org.telegram.ui.ActionBar.Theme")
            button.setTextColor(Theme.getColor(Theme.key_text_RedBold))

    def remove(self, name):
        ext = self.ext

        def done(_):
            self.say(tr("Расширение «%s» удалено") % name, "ic_delete")
            self.owner.back()

        self.run(lambda m: m.remove(ext), done)

    def dispose(self):
        if self.pending:
            self.save_now()
        super().dispose()
