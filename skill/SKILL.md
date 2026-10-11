---
name: exteragram-plugin-dev
description: >-
  Build exteraGram plugins (Python on BasePlugin SDK 1.4.4.3, exteraGram 12.5.1+,
  Python 3.11 via Chaquopy v16). Use when writing or editing .plugin files,
  implementing hooks (on_send_message_hook, pre_request_hook, post_request_hook,
  on_update_hook), creating plugin settings (ui.settings: Header/Switch/Selector/
  Input/Text/Custom), sending messages (send_text/send_photo/send_document/
  edit_message), Xposed method hooking (MethodHook/HookFilter), Java class proxy
  (java_subclass/joverride/jmethod), file handlers (FilesController), bulletins
  (BulletinHelper), dialogs (AlertDialogBuilder), intents (IntentsManager), Elyx
  structured plugins (refmap/metainfo/assets/strings), reflection (hook_utils
  find_class/get_private_field), or debugging the dev server (127.0.0.1:42690).
  Covers multi-account scoping, text formatting, PIP dependencies, AyuGram, and
  the for-vibecode-plugins repo (allpg/ analyses, community/ catalog, security vetting).
---

# exteraGram Plugin Development

## Baseline

- SDK version: `1.4.4.3` (multi-account helpers need `>=1.4.5.0`, Elyx needs `>=1.4.5.3`)
- Python runtime: **3.11** (bytecode builds MUST use 3.11)
- Minimum app: **exteraGram 12.5.1+** (older builds enter safe mode and refuse plugin init)
- Engine: Chaquopy v16 + Xposed-style method hooking
- SDK modules are stub imports on desktop — IDE flags them as missing; add `# pyright: ignore[reportMissingImports]` or `# noqa`

## Quickstart — Minimal Plugin

A plugin is one Python file (extension `.plugin` in the repo, `.py` on device). The file must contain:

1. **Metadata as plain top-level constants** (loader parses them via AST — never build dynamically)
2. **One class inheriting from `BasePlugin`**

```python
from base_plugin import BasePlugin

__id__ = "hello_world"              # 2-32 chars, latin/digits/_/-, start with letter
__name__ = "Hello World"            # required
__description__ = "My first plugin" # markdown supported in UI
__author__ = "@yourUsername"
__version__ = "1.0.0"               # default "1.0" if omitted
__icon__ = "exteraPlugins/1"        # StickerPackShortName/index
__app_version__ = ">=12.5.1"        # supports >=, <=, ==, >, <
__sdk_version__ = ">=1.4.4.3"
__requirements__ = ["mpmath"]       # PEP 508, pure-Python wheels only


class HelloWorldPlugin(BasePlugin):
    pass
```

For a fuller first plugin (`.hello` command + settings + outgoing-message hook), see [examples/hello_command.py](https://raw.githubusercontent.com/BroZYTnikkkk/for-vibecode-plugins/main/skill/examples/hello_command.py).

## API Map by Module

| Module | Key capabilities | Reference |
|--------|------------------|-----------|
| `base_plugin` | `BasePlugin`, metadata, lifecycle, hooks, menu items, `MethodHook`/`MethodReplacement`/`HookFilter`/`MenuItemData`/`AppEvent` | [plugin-class.md](https://raw.githubusercontent.com/BroZYTnikkkk/for-vibecode-plugins/main/skill/reference/plugin-class.md) |
| `ui.settings` | `Header`/`Divider`/`Switch`/`Selector`/`Input`/`EditText`/`Text`/`Custom`, `SimpleSettingFactory` | [settings.md](https://raw.githubusercontent.com/BroZYTnikkkk/for-vibecode-plugins/main/skill/reference/settings.md) |
| `client_utils` | `run_on_queue`, `send_request`, `send_text`/`send_photo`/`send_document`/`send_video`/`send_audio`/`send_message`, `edit_message`, `get_last_fragment`/`get_messages_controller`/..., `NotificationCenterDelegate` | [client-utils.md](https://raw.githubusercontent.com/BroZYTnikkkk/for-vibecode-plugins/main/skill/reference/client-utils.md) |
| `android_utils` | `run_on_ui_thread`, `R` (Runnable proxy), `OnClickListener`/`OnLongClickListener`, `log`, `copy_to_clipboard` | [android-utils.md](https://raw.githubusercontent.com/BroZYTnikkkk/for-vibecode-plugins/main/skill/reference/android-utils.md) |
| `hook_utils` | `find_class`, `get_private_field`/`set_private_field`, static variants — reflection | [hook-utils.md](https://raw.githubusercontent.com/BroZYTnikkkk/for-vibecode-plugins/main/skill/reference/hook-utils.md) |
| `extera_utils.classes` | `@java_subclass`, `@joverride`/`@joverload`/`@jmethod`/`jfield`/`@jconstructor`, MVEL, `JA`/`JGS`/`JIR`/`JS` modifiers | [class-proxy.md](https://raw.githubusercontent.com/BroZYTnikkkk/for-vibecode-plugins/main/skill/reference/class-proxy.md) |
| `extera_utils.text_formatting` | `parse_text(text, parse_mode="HTML"\|"Markdown")`, `TLEntityType` | [text-formatting.md](https://raw.githubusercontent.com/BroZYTnikkkk/for-vibecode-plugins/main/skill/reference/text-formatting.md) |
| `file_utils` | `get_plugins_dir`/`get_cache_dir`/..., `read_file`/`write_file`/`read_file_bytes`/`write_file_bytes`, `list_dir`, `FilesController` | [file-utils.md](https://raw.githubusercontent.com/BroZYTnikkkk/for-vibecode-plugins/main/skill/reference/file-utils.md) |
| `ui.bulletin` | `BulletinHelper.show_info`/`show_error`/`show_success`/`show_with_button`/`show_undo` | [ui-helpers.md](https://raw.githubusercontent.com/BroZYTnikkkk/for-vibecode-plugins/main/skill/reference/ui-helpers.md) |
| `ui.alert` | `AlertDialogBuilder` — message/loading/spinner dialogs | [ui-helpers.md](https://raw.githubusercontent.com/BroZYTnikkkk/for-vibecode-plugins/main/skill/reference/ui-helpers.md) |
| `intents` | `IntentsManager.new_global_before_handler`/`new_global_after_handler`, scheme/host/path/action/flags filters | [intents.md](https://raw.githubusercontent.com/BroZYTnikkkk/for-vibecode-plugins/main/skill/reference/intents.md) |
| multi-account | `account=` on every hook/controller, `self.client(account)` → `AccountClient`, `get_selected_account`, `get_hook_account` | [multi-account.md](https://raw.githubusercontent.com/BroZYTnikkkk/for-vibecode-plugins/main/skill/reference/multi-account.md) |
| `elyx` | Structured multi-file plugins: `refmap.yml`, `metainfo.yml`, `assets`, `strings`, bundled wheels, `ElyxBuilder` CLI | [elyx.md](https://raw.githubusercontent.com/BroZYTnikkkk/for-vibecode-plugins/main/skill/reference/elyx.md) |
| dev workflow | Setup, dev server (`127.0.0.1:42690`), PIP deps, pre-installed libs, common Telegram classes | [dev-workflow.md](https://raw.githubusercontent.com/BroZYTnikkkk/for-vibecode-plugins/main/skill/reference/dev-workflow.md) |
| repo (for-vibecode-plugins) | `allpg/` analyses, `community/` catalog, security vetting, adding a plugin | [repo-conventions.md](https://raw.githubusercontent.com/BroZYTnikkkk/for-vibecode-plugins/main/skill/reference/repo-conventions.md) |

## Hooks (most-used API)

Register in `on_plugin_load`:

```python
class MyPlugin(BasePlugin):
    def on_plugin_load(self):
        self.add_hook("TL_messages_setTyping")     # request by name
        self.add_on_send_message_hook()             # outgoing messages
```

Signatures and `HookResult`:

| Hook | Signature | Modify via |
|------|-----------|------------|
| `pre_request_hook` | `(self, request_name, account, request)` | `HookResult.request` |
| `post_request_hook` | `(self, request_name, account, response, error)` | `HookResult.response` |
| `on_update_hook` | `(self, update_name, account, update)` | `HookResult.update` |
| `on_updates_hook` | `(self, container_name, account, updates)` | `HookResult.updates` |
| `on_send_message_hook` | `(self, account, params)` | `HookResult.params` |

```python
from base_plugin import HookResult, HookStrategy

# Strategies:
HookStrategy.DEFAULT       # do nothing
HookStrategy.CANCEL        # stop the operation
HookStrategy.MODIFY        # use the modified object
HookStrategy.MODIFY_FINAL  # modify and stop further plugin processing

def on_send_message_hook(self, account, params) -> HookResult:
    if isinstance(getattr(params, "message", None), str) and params.message.startswith(".hello"):
        params.message = "Hello!"
        return HookResult(strategy=HookStrategy.MODIFY, params=params)
    return HookResult()  # unchanged
```

## Multi-Account Rule (critical)

exteraGram keeps every logged-in account connected. Background accounts still fire hooks. **Every hook callback receives `account`** — use it for anything you do in response:

```python
def on_update_hook(self, update_name, account, update) -> HookResult:
    client = self.client(account)  # AccountClient bound to one account
    client.send_text(update.message.dialog_id, "reply")
    return HookResult()
```

Without `account=`, helpers default to the UI-selected account and the SDK logs a warning once per helper. See [multi-account.md](https://raw.githubusercontent.com/BroZYTnikkkk/for-vibecode-plugins/main/skill/reference/multi-account.md).

## Source Repo: for-vibecode-plugins

Primary source of real, working examples: **https://github.com/BroZYTnikkkk/for-vibecode-plugins**
(raw base `https://raw.githubusercontent.com/BroZYTnikkkk/for-vibecode-plugins/main/`; if the repo is checked out locally, read the files there instead). Analyses are in Russian.

Before writing a plugin, look for prior art:

1. `plugins-index.md` and `allpg/<Name>/<name>-analysis.md` — our plugins with "what didn't work and why".
2. `community/README.md` — ~55 third-party plugins by topic with a "чему научиться" column (which class/method each one hooks); `community/analyses/` — detailed teardowns.
3. `community/java-dex.md` (embedded Java/DEX) and `community/elyx.md` (Elyx in practice).
4. `community/security.md` — vet any foreign code before copying from it (`exec` on decoded blobs, calls to bare `IP:port`, DEX downloaded at runtime).

Rules: never commit third-party `.plugin` files (no open license) — only our analysis and short credited excerpts. Class/method names change between app versions (R8): verify against [decompiled exteraGram](https://github.com/Podyshka1/extera-full-decompiled) or [Telegram for Android](https://github.com/DrKLO/Telegram). Full conventions: [repo-conventions.md](https://raw.githubusercontent.com/BroZYTnikkkk/for-vibecode-plugins/main/skill/reference/repo-conventions.md).

## Common Beginner Mistakes

1. **Forgetting `self.add_on_send_message_hook()`** in `on_plugin_load` — implementing the method alone does nothing.
2. **Dynamic metadata** — `__version__ = compute_version()` breaks AST parsing; use plain constants.
3. **`params.message` without `isinstance` check** — some sends are media-only; always validate.
4. **Slow work on the UI thread** — use `run_on_queue(...)` (from `client_utils`) for network/file/long compute.
5. **Wrong account** — see Multi-Account Rule above.
6. **Shadowing SDK/stdlib module names** — never name a local file `json.py`, `ui.py`, `java.py`, `elyx.py`.

## Elyx (Structured Multi-File Plugins)

Use Elyx instead of single-file when you need multiple modules, bundled assets, localization, or bundled wheels. Same `BasePlugin` API; Elyx adds `refmap.yml` + `metainfo.yml` + `assets/` + `strings/`.

```yaml
# refmap.yml
metainfo: metainfo.yml
main: main.py
assets: assets
strings: strings
```

```yaml
# metainfo.yml
id: my_plugin
name: My Plugin
version: "1.0.0"
sdk_version: ">=1.4.5.3"
```

Scaffold: `python -m pip install --upgrade ElyxBuilder && elyb new -g -n "My Plugin" -a author`. Build: `elyb build --ast -v -nf`. Full guide: [elyx.md](https://raw.githubusercontent.com/BroZYTnikkkk/for-vibecode-plugins/main/skill/reference/elyx.md).

## Examples

- [examples/minimal.py](https://raw.githubusercontent.com/BroZYTnikkkk/for-vibecode-plugins/main/skill/examples/minimal.py) — bare skeleton (metadata + `BasePlugin`)
- [examples/hello_command.py](https://raw.githubusercontent.com/BroZYTnikkkk/for-vibecode-plugins/main/skill/examples/hello_command.py) — `.hello` command + settings + `on_send_message_hook`
- [examples/ghost_mode.py](https://raw.githubusercontent.com/BroZYTnikkkk/for-vibecode-plugins/main/skill/examples/ghost_mode.py) — `pre_request_hook` cancel/modify + settings + menu items
- [examples/custom_setting.py](https://raw.githubusercontent.com/BroZYTnikkkk/for-vibecode-plugins/main/skill/examples/custom_setting.py) — `SimpleSettingFactory` + custom Java view row

## Source

SDK reference distilled from [plugins.exteragram.app/docs](https://plugins.exteragram.app/docs) (32 pages, SDK 1.4.4.3) by abuztrade ([makarworld/exteragram-plugin-skill](https://github.com/makarworld/exteragram-plugin-skill), MIT), adapted to use [BroZYTnikkkk/for-vibecode-plugins](https://github.com/BroZYTnikkkk/for-vibecode-plugins) as the source repo. When the live docs disagree with this skill, the live docs win for SDK behavior; the repo's analyses win for what actually works on real app versions.
