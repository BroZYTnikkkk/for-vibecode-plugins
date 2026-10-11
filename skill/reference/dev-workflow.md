# Dev Workflow — Setup, Dev Server, PIP, Libraries, Common Classes

## Setup

### Install a recent app build

Use a recent exteraGram build with plugin support enabled. For SDK 1.4.4.3, treat **exteraGram 12.5.1+** as the practical minimum. Beta builds are usually published in the beta channel.

### Enable the plugin engine

After logging in: exteraGram Preferences → Plugins → enable the plugin engine. Then open the plugin info screen and enable **developer mode**.

### Create a local project

```
my-plugin/
`-- hello_world.py
```

Tips:
- keep the filename stable; the least surprising setup is `filename == __id__ + ".py"`
- point your IDE at the SDK's `src/` directory for imports and autocomplete
- keep metadata as plain top-level constants (loader parses them via AST)

### Connect the device

Connect via ADB (`adb` on PATH). Two common workflows:
- copy the `.py` file into the app's plugins directory and reload manually
- use helper tooling that talks to the built-in DevServer for write/reload/debug

On-device plugin files live at:

```
/data/user/0/com.exteragram.messenger/files/plugins/<plugin_id>.py
```

#### Debugging ports

Dev server listens on **42690** by default. Debugger port is separate (e.g. 5678). VS Code remote attach:

```json
{
    "version": "0.2.0",
    "configurations": [
        {
            "name": "Python Debugger: Attach exteraGram plugin",
            "type": "debugpy",
            "request": "attach",
            "connect": { "host": "localhost", "port": 5678 },
            "pathMappings": [
                {
                    "localRoot": "/path/to/your/workspace",
                    "remoteRoot": "/data/user/0/com.exteragram.messenger/files/plugins"
                }
            ]
        }
    ]
}
```

## First Plugin (`.hello` command)

Realistic first plugin — rewrites `.hello <name>` outgoing messages with a configurable template.

```python
from typing import Any, List
from base_plugin import BasePlugin, HookResult, HookStrategy
from ui.settings import Header, Input, Text

__id__ = "hello_world"
__name__ = "Hello World"
__description__ = "Rewrites .hello commands into a friendly message"
__author__ = "Your Name"
__version__ = "1.0.0"
__icon__ = "exteraPlugins/1"
__app_version__ = ">=12.5.1"
__sdk_version__ = ">=1.4.4.3"

DEFAULT_TEMPLATE = "Hello, {name}!"


class HelloWorldPlugin(BasePlugin):
    def on_plugin_load(self):
        # Register the outgoing-message hook once.
        self.add_on_send_message_hook()
        self.log("Hello World plugin loaded")

    def create_settings(self) -> List[Any]:
        return [
            Header(text="Hello World"),
            Input(
                key="template",
                text="Greeting template",
                default=DEFAULT_TEMPLATE,
                subtext="Use {name} where the name should appear.",
                icon="msg_edit",
            ),
            Text(text="Example", subtext=".hello Alice -> Hello, Alice!", icon="msg_info"),
        ]

    def on_send_message_hook(self, account: int, params: Any) -> HookResult:
        if not isinstance(getattr(params, "message", None), str):
            return HookResult()

        raw_text = params.message.strip()
        if not raw_text.startswith(".hello"):
            return HookResult()

        parts = raw_text.split(" ", 1)
        name = parts[1].strip() if len(parts) > 1 else ""

        if not name:
            params.message = "Usage: .hello <name>"
            return HookResult(strategy=HookStrategy.MODIFY, params=params)

        template = self.get_setting("template", DEFAULT_TEMPLATE)
        try:
            params.message = template.format(name=name)
        except Exception:
            params.message = "Template must contain valid placeholders, e.g. {name}."

        return HookResult(strategy=HookStrategy.MODIFY, params=params)
```

### What this teaches

1. **Metadata is parsed statically** — `__id__`, `__version__`, etc. stay as plain top-level constants.
2. **Hooks must be registered** — implementing `on_send_message_hook` is not enough; you also need `self.add_on_send_message_hook()` in `on_plugin_load`.
3. **Settings are dataclasses from `ui.settings`** — `Header`, `Input`, `Text`.
4. **`HookResult` decides what happens next** — `HookResult()` unchanged, `HookStrategy.MODIFY` use updated params, `HookStrategy.CANCEL` stop the send.

### Common beginner mistakes

- forgetting `self.add_on_send_message_hook()` in `on_plugin_load`
- building metadata dynamically instead of using plain constants
- assuming `params.message` always exists
- doing slow network/file work directly in a hook on the UI thread

For background work, use `run_on_queue(...)` from `client_utils`.

## Development Server

Small TCP dev server (default endpoint `127.0.0.1:42690`) for desktop tooling. Inspects/reloads plugins; Elyx extends it with multi-file sync.

> **Development use only.** Enable only while developing — the protocol can install, rewrite, enable, disable, reload, and delete plugin code.

### Connect via ADB

```powershell
adb devices
adb forward tcp:42690 tcp:42690
```

### Message format

Consecutive UTF-8 JSON objects. Basic request:

```json
{ "@": "ping", "#": "request-1" }
```

- `@` — command name
- `#` — client-generated request id
- additional fields depend on the command

Response repeats the request id:

```json
{ "#": "request-1", "pong": true }
```

### Core commands

| Command | Additional fields | Purpose |
|---------|-------------------|---------|
| `ping` | — | test connection |
| `get_plugins` | — | list loaded plugins and state |
| `enable_plugin` | `plugin_id` | enable an installed plugin |
| `disable_plugin` | `plugin_id` | disable an installed plugin |
| `reload_plugin` | `plugin_id` | reload a regular single-file plugin |
| `write_plugin` | `plugin_id`, `content` | install or update Python source |
| `remove_plugin` | `plugin_id` | delete an installed plugin |
| `start_debugger` | `host`, `port`, `platform` | start a remote debugger |
| `stop_debugger` | `platform` | stop a remote debugger |

`write_plugin.content` is the complete Python source as a JSON string.

### Elyx multi-file commands

| Command | Purpose |
|---------|---------|
| `elyx_ping` | check that Elyx dev support is active |
| `get_elyx_plugins` | list loaded structured plugins |
| `elyx_compare_folder` | compare local hashes with installed files |
| `elyx_changes` | apply file changes and reload one Elyx plugin |

Elyx payloads are compressed JSON carried in a base64 `data` field. See [elyx.md](elyx.md) for the payload format and `elyx_dev_client.py` workflow.

### Remote debugging

```json
{ "@": "start_debugger", "#": "debug-1", "host": "127.0.0.1", "port": 5678, "platform": "vscode" }
```

Supported platforms: `vscode`, `pycharm`. The debugger port is separate from 42690 — configure the IDE and any ADB reverse/forward rule for the direction used by that debugger.

### Client behavior (robust custom client)

- test `ping` or `elyx_ping` before sending changes
- apply socket timeouts
- preserve request ids
- display complete server errors
- ignore build caches and version-control directories
- debounce rapid editor events into one change batch
- reconnect after the app restarts

### Connection troubleshooting

- confirm developer mode and the server are enabled
- `adb devices`
- recreate `adb forward tcp:42690 tcp:42690`
- check no other process owns local port 42690
- restart the server after changing device
- if `ping` works but `elyx_ping` doesn't: regular server running but Elyx dev support not initialized

## PIP & Dependencies

Built-in PIP-like manager downloads deps from PyPI. Declare in metadata:

```python
__id__ = "inline_calculator"
__name__ = "Inline Calculator"
__requirements__ = ["mpmath", "tinydb"]
```

On install, exteraGram downloads the libraries automatically.

### How it works

- **Resolution:** fetches package metadata from PyPI to find a satisfying version.
- **Pure-Python only:** only `*-none-any.whl` wheels.
- **Isolation:** shared libs directory; same version shared across plugins.
- **Cleanup:** when a plugin is uninstalled, deps no longer needed by any plugin are removed.

### Limitations

1. **No binary extensions.** numpy, pandas, scipy, cryptography, opencv, etc. won't work — they must be compiled for Android. Only "Universal" / "none-any" wheels.
2. **Dependency conflicts.** All plugins share the same installed libs. If A wants `requests==2.25.1` and B wants `2.31.0`, the system tries a satisfying version; if none, the second install fails.
3. **Network access** required for installation.
4. **Limited marker support** — basic `python_version`, `sys_platform`; complex markers/`extra` may not work.

### Troubleshooting

- **"No pure-Python wheel found"** — library has compiled code; can't use unless added to core app.
- **"Dependency conflict"** — another plugin needs an incompatible version.
- **"Package not found"** — spelling or not on PyPI.

## Available Libraries (pre-installed)

Python **3.11**. These are pre-installed and importable without `__requirements__`:

| Library | Use |
|---------|-----|
| `beautifulsoup4` | HTML/XML scraping |
| `debugpy` | remote debugging (used by dev server) |
| `lxml` | XML/HTML processing |
| `packaging` | package utilities |
| `pillow` | image manipulation (PIL fork) |
| `requests` | HTTP client |
| `PyYAML` | YAML parser/emitter |

Other pure-Python libraries can be added via `__requirements__` — binary extensions are not supported.

## Common Telegram Classes

Have a local copy of Telegram sources open in Android Studio for reference.

| Class | Path |
|-------|------|
| `LaunchActivity` | `TMessagesProj/src/main/java/org/telegram/ui/LaunchActivity.java` — app init, custom links |
| `ProfileActivity` | `org/telegram/ui/ProfileActivity.java` — user/channel profile |
| `ChatActivity` | `org/telegram/ui/ChatActivity.java` — chat rendering |
| `MessageObject` | `org/telegram/messenger/MessageObject.java` — wraps `TLRPC.Message` |
| `ChatMessageCell` | `org/telegram/ui/Cells/ChatMessageCell.java` — message rendering |
| `AndroidUtilities` | `org/telegram/messenger/AndroidUtilities.java` — utilities |
| `MessagesController` | `org/telegram/messenger/MessagesController.java` — app state + requests |
| `MessagesStorage` | `org/telegram/messenger/MessagesStorage.java` — local DB (`database` field for SQLite) |
| `SendMessagesHelper` | `org/telegram/messenger/SendMessagesHelper.java` — sending messages/files |
| `BulletinFactory` | `org/telegram/ui/Components/BulletinFactory.java` — bottom bulletins |
| `AlertDialog` | `org/telegram/ui/ActionBar/AlertDialog.java` — alert dialogs |
| `TLRPC` | `org/telegram/tgnet/` — `TLRPC.java` + additional models |

Human-readable schema list: `https://corefork.telegram.org/schema` (not always up-to-date).
