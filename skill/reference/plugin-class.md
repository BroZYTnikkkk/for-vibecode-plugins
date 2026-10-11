# Plugin Class (base_plugin)

Source: `from base_plugin import BasePlugin, HookResult, HookStrategy, MenuItemData, MenuItemType, AppEvent, MethodHook, MethodReplacement, HookFilter, hook_filters`

## Metadata

Plain top-level constants. The loader parses them via AST — **never** build them dynamically.

```python
__id__ = "better_previews"          # required, 2-32 chars: letters/digits/_/-
__name__ = "Better Previews"        # required
__description__ = "Modifies URLs"   # optional, markdown rendered in UI
__author__ = "@immat0x1"            # optional, plain text or @handle
__version__ = "1.0.0"               # optional, default "1.0"
__icon__ = "exteraPlugins/1"        # optional, StickerPackShortName/index
__app_version__ = ">=12.5.1"        # optional, supports >= <= == > <
__sdk_version__ = ">=1.4.4.3"       # optional, min SDK API version
__requirements__ = ["mpmath", "tinydb"]  # optional, PEP 508, pure-Python only
```

- `__min_version__` is legacy alias for `__app_version__ = ">=..."`.
- `__description__` supports basic markdown rendering.
- Declare `__sdk_version__ = ">=1.4.5.0"` when using multi-account helpers so older installs fail with a clear message.

## Basic Structure

One class inheriting from `BasePlugin`:

```python
from base_plugin import BasePlugin

class WeatherPlugin(BasePlugin):
    pass
```

To expose a settings screen, implement `create_settings`:

```python
from typing import Any, List
from ui.settings import Header, Switch

class MyPlugin(BasePlugin):
    def create_settings(self) -> List[Any]:
        return [
            Header(text="General"),
            Switch(key="enabled", text="Enable feature", default=True),
        ]
```

See [settings.md](settings.md) for the full settings system.

## Lifecycle

```python
class DebugPlugin(BasePlugin):
    def on_plugin_load(self):
        # Register hooks, listeners, start background tasks here.
        self.log("Plugin loaded!")

    def on_plugin_unload(self):
        # Cleanup not handled automatically: threads, sockets, observers.
        self.log("Plugin unloaded!")
```

- `on_plugin_load` runs on enable and on app startup restore.
- `on_plugin_unload` runs on disable and on app shutdown.

## App Events

```python
from base_plugin import AppEvent, BasePlugin

class DebugPlugin(BasePlugin):
    def on_app_event(self, event_type: AppEvent):
        if event_type == AppEvent.START:
            self.log("App starting")
        elif event_type == AppEvent.STOP:
            self.log("App stopping")
        elif event_type == AppEvent.PAUSE:
            self.log("App backgrounded")
        elif event_type == AppEvent.RESUME:
            self.log("App foregrounded")
```

`AppEvent` values: `START`, `STOP`, `PAUSE`, `RESUME`.

## Settings Storage Helpers

Built into `BasePlugin`:

```python
self.get_setting(key, default=None)
self.set_setting(key, value, reload_settings=False)
self.export_settings()
self.import_settings(settings, reload_settings=True)
```

```python
current = self.get_setting("enabled", True)
self.set_setting("enabled", not current, reload_settings=True)

backup = self.export_settings()
self.import_settings(backup, reload_settings=False)
```

`reload_settings=True` rebuilds the open settings screen — use only when row visibility/structure depends on the value.

## Menu Items

Add entries to app menus via `MenuItemData`:

```python
from typing import Any, Dict
from base_plugin import BasePlugin, MenuItemData, MenuItemType

class MyMenuPlugin(BasePlugin):
    def on_plugin_load(self):
        self.message_item_id = self.add_menu_item(
            MenuItemData(
                menu_type=MenuItemType.MESSAGE_CONTEXT_MENU,
                text="Log Message Info",
                on_click=self.handle_message_click,
                icon="msg_info",
                subtext="Debug helper",
                priority=10,
            )
        )

    def handle_message_click(self, context: Dict[str, Any]):
        message = context.get("message")
        if message:
            self.log(f"Message ID: {message.getId()}")
```

### `MenuItemData` fields

| Field | Required | Description |
|-------|----------|-------------|
| `menu_type: MenuItemType` | yes | target menu |
| `text: str` | yes | visible title |
| `on_click: Callable[[Dict[str, Any]], None]` | yes | click handler |
| `item_id: Optional[str]` | no | stable id for later removal |
| `icon: Optional[str]` | no | drawable name, e.g. `"msg_info"` |
| `subtext: Optional[str]` | no | secondary line |
| `condition: Optional[str]` | no | MVEL expression controlling visibility |
| `priority: int` | no | larger usually appears earlier |

### `MenuItemType` values

`MESSAGE_CONTEXT_MENU`, `DRAWER_MENU`, `MAIN_MENU`, `CHAT_ACTION_MENU`, `PROFILE_ACTION_MENU`.

### The `on_click` context dict

Keys depend on menu type and screen. Common: `account`, `context`, `fragment`, `dialog_id`, `user`, `userId`, `userFull`, `chat`, `chatId`, `chatFull`, `encryptedChat`, `message`, `groupedMessages`, `botInfo`. Inspect during dev:

```python
def handle_click(self, context):
    self.log(f"Available keys: {list(context.keys())}")
```

### Removing

Menu items are removed automatically on unload. Manual removal:

```python
if self.message_item_id:
    self.remove_menu_item(self.message_item_id)
```

## Event Hooks

Intercept Telegram requests, responses, updates, and outgoing messages.

### Registration

```python
def on_plugin_load(self):
    self.add_hook("TL_messages_setTyping")          # by request name
    self.add_hook("TL_account_updateStatus")
    self.add_on_send_message_hook()                 # outgoing messages
    # Optional: self.add_hook(name, match_substring=False, priority=0)
```

### Hook callbacks

Every callback receives `account: int`. Background accounts stay connected and keep firing hooks — **use that account** for any response (see [multi-account.md](multi-account.md)).

```python
from typing import Any, List
from base_plugin import BasePlugin, HookResult, HookStrategy
from ui.settings import Switch

TYPING_REQUESTS = ["TL_messages_setTyping", "TL_messages_setEncryptedTyping"]

class GhostModePlugin(BasePlugin):
    def on_plugin_load(self):
        for req in TYPING_REQUESTS:
            self.add_hook(req)
        self.add_hook("TL_account_updateStatus")

    def pre_request_hook(self, request_name, account, request) -> HookResult:
        if request_name in TYPING_REQUESTS and self.get_setting("dont_send_typing", True):
            return HookResult(strategy=HookStrategy.CANCEL)
        if request_name == "TL_account_updateStatus" and self.get_setting("force_offline", True):
            request.offline = True
            return HookResult(strategy=HookStrategy.MODIFY, request=request)
        return HookResult()

    def post_request_hook(self, request_name, account, response, error) -> HookResult:
        if request_name == "TL_messages_sendMessage" and not error:
            self.log("Sent a message!")
        return HookResult()

    def create_settings(self) -> List[Any]:
        return [
            Switch(key="dont_send_typing", text="Don't send typing", default=True),
            Switch(key="force_offline", text="Always appear offline", default=True),
        ]
```

### Hook strategies

| Strategy | Effect |
|----------|--------|
| `HookStrategy.DEFAULT` | do nothing special |
| `HookStrategy.CANCEL` | stop the operation |
| `HookStrategy.MODIFY` | return a modified object |
| `HookStrategy.MODIFY_FINAL` | modify and stop further plugin processing for that event |

Assign the modified object to the matching `HookResult` field:

| Hook | Field |
|------|-------|
| `pre_request_hook` / `post_request_hook` | `request` / `response` |
| `on_update_hook` | `update` |
| `on_updates_hook` | `updates` |
| `on_send_message_hook` | `params` |

### Update hooks

```python
def on_update_hook(self, update_name, account, update) -> HookResult:
    if update_name == "TL_updateNewMessage":
        self.log(f"Intercepted: {update_name}")
    return HookResult()

def on_updates_hook(self, container_name, account, updates) -> HookResult:
    if container_name == "TL_updates":
        self.log(f"Container: {container_name}")
    return HookResult()
```

### Outgoing message hook

```python
def on_send_message_hook(self, account, params) -> HookResult:
    result = HookResult()
    if hasattr(params, "message") and isinstance(params.message, str):
        if params.message.startswith(".hello"):
            params.message = params.message.replace(".hello", "Hello from plugin")
            result.strategy = HookStrategy.MODIFY
            result.params = params
    return result
```

## Xposed-Style Java Hooking

For low-level Java method hooking (`MethodHook`, `MethodReplacement`, `HookFilter`), see [xposed-hooking.md](xposed-hooking.md). For Java subclasses with `super()`, see [class-proxy.md](class-proxy.md).
