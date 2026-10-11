# Plugin Settings (ui.settings)

Source: `from ui.settings import Header, Divider, Switch, Selector, Input, EditText, Text, Custom, SimpleSettingFactory`

Implement `create_settings(self) -> List[Any]` on `BasePlugin`. Return a list of dataclass instances.

## General Example

```python
from typing import Any, List
from base_plugin import BasePlugin
from ui.settings import Header, Switch, Selector, Input, Text, Divider

class MyPlugin(BasePlugin):
    def _on_switch_change(self, new_value: bool):
        self.log(f"Switch: {new_value}")

    def create_settings(self) -> List[Any]:
        return [
            Header(text="General"),
            Switch(
                key="enabled",
                text="Enable feature",
                default=True,
                subtext="Sample switch",
                icon="msg_settings",
                on_change=self._on_switch_change,
                link_alias="enabled_link",
            ),
            Selector(
                key="mode",
                text="Mode",
                default=1,
                items=["Off", "Basic", "Advanced"],
                icon="msg_list",
            ),
            Input(
                key="name",
                text="Name",
                default="Alice",
                subtext="Single-line text",
                icon="msg_text",
            ),
            Divider(text="Section divider"),
            Text(
                text="Tap for sub-page",
                icon="msg_arrow_forward",
                on_click=self._on_text_click,
                create_sub_fragment=self._sub_page,
            ),
            Text(text="Warning", icon="msg_error", red=True),
        ]

    def _sub_page(self) -> List[Any]:
        return [Header(text="Sub-Page"), Text(text="Nested settings.")]

    def _on_text_click(self, view):
        self.log("Text clicked")
```

## Access and Modify Settings

Use `BasePlugin` helpers:

```python
is_enabled = self.get_setting("enabled", False)

self.set_setting("enabled", True)
self.set_setting("mode", "advanced", reload_settings=True)  # rebuild open screen

all_settings = self.export_settings()
self.import_settings({"enabled": False, "name": "Bob"})
```

## Built-in Setting Types

| Control | `key` | `text` | `default` | Other params |
|---------|-------|--------|-----------|--------------|
| `Header` | — | required | — | (section title only) |
| `Divider` | — | — | — | `text` (optional caption) |
| `Switch` | required | required | required (bool) | `subtext`, `icon`, `on_change`, `on_long_click`, `link_alias` |
| `Selector` | required | required | required (int index) | `items` (List[str]), `icon`, `on_change`, `on_long_click`, `link_alias` |
| `Input` | required | required | optional str | `subtext`, `icon`, `on_change`, `on_long_click`, `link_alias` |
| `Text` | — | required | — | `subtext`, `icon`, `accent`, `red`, `on_click`, `on_long_click`, `create_sub_fragment`, `link_alias` |
| `EditText` | required | — | optional str | `hint` (required), `multiline`, `max_length`, `mask`, `on_change` |
| `Custom` | — | — | — | `item`, `view`, `factory`, `factory_args`, `on_click`, `on_long_click`, `create_sub_fragment`, `link_alias` |

## Parameter Details

| Parameter | Type | Description |
|-----------|------|-------------|
| `key` | str | unique key for persisted value; used by `get_setting` / `set_setting` |
| `text` | str | main visible text |
| `default` | Any | value when setting was never saved |
| `subtext` | str | optional second line |
| `icon` | str | optional drawable name like `"msg_settings"` |
| `on_change` | Callable | runs when value changes; signature depends on control |
| `on_click` | Callable | runs when row is clicked; usually receives the clicked `View` |
| `on_long_click` | Callable | runs on long press |
| `link_alias` | str | enables a copyable deeplink alias for the row |
| `items` | List[str] | `Selector` option labels |
| `create_sub_fragment` | Callable[[], List[Any]] | builds a nested settings page when tapped |
| `accent` | bool | accent coloring on `Text` |
| `red` | bool | red coloring on `Text` |
| `hint` | str | placeholder for `EditText` |
| `multiline` | bool | multiline `EditText` |
| `max_length` | int | max `EditText` length |
| `mask` | str | regex-like `EditText` input restriction |
| `factory` | CustomSetting.Factory | Java factory for advanced custom items |
| `item` | UItem | prebuilt Telegram `UItem` instance |
| `view` | View | plain Android `View` instance |

## Custom Settings

`Custom` is the flexible entry point for rows that don't fit built-in controls. Three main patterns.

### 1. Existing UItem

```python
from org.telegram.ui.Components import UItem
from ui.settings import Custom

setting = Custom(item=UItem.asShadow("Custom shadow text."))
```

### 2. Ready Android View

```python
from android.widget import TextView
from ui.settings import Custom

label = TextView(context)
label.setText("Hello from a custom View")
setting = Custom(view=label)
```

### 3. SimpleSettingFactory (recommended for custom rows)

```python
from android.view import Gravity
from android.widget import LinearLayout, TextView
from org.telegram.messenger import AndroidUtilities
from org.telegram.ui.Components import LayoutHelper
from ui.bulletin import BulletinHelper
from ui.settings import Custom, SimpleSettingFactory


def create_view(context, list_view, current_account, class_guid, resources_provider):
    layout = LinearLayout(context)
    layout.setOrientation(LinearLayout.VERTICAL)
    layout.setGravity(Gravity.CENTER)
    layout.setPadding(
        AndroidUtilities.dp(20), AndroidUtilities.dp(20),
        AndroidUtilities.dp(20), AndroidUtilities.dp(20),
    )
    title = TextView(context)
    title.setText("Tap me")
    layout.addView(title, LayoutHelper.createLinear(
        LayoutHelper.WRAP_CONTENT, LayoutHelper.WRAP_CONTENT))
    return layout


def bind_view(view, item, divider, adapter, list_view):
    view.getChildAt(0).setText("Tap me")


def on_click(plugin, item, view):
    BulletinHelper.show_info(f"Hello from {plugin.getName()}!")


InteractiveRowFactory = SimpleSettingFactory(
    create_view,
    bind_view,
    is_clickable=True,
    on_click=on_click,
)

# Use it:
setting = Custom(factory=InteractiveRowFactory.instance.java)
```

### `SimpleSettingFactory` callbacks

| Callback | Signature |
|----------|-----------|
| `create_view` | `(context, list_view, current_account, class_guid, resources_provider) -> View` |
| `bind_view` | `(view, item, divider, adapter, list_view) -> None` |
| `create_item` | `(plugin, setting, args) -> UItem` |
| `on_click` | `(plugin, item, view) -> None` |
| `on_long_click` | `(plugin, item, view) -> bool` |
| `attached_view` | `(list_view, view, item) -> None` |
| `equals` | `(a, b) -> bool` |
| `content_equals` | `(a, b) -> bool` |

Constructor: `SimpleSettingFactory(create_view, bind_view, is_clickable=False, is_shadow=False, create_item=None, on_click=None, on_long_click=None, attached_view=None, equals=None, content_equals=None)`.

Notes:
- `create_view` builds the row skeleton once; `bind_view` fills current data.
- `is_clickable` and `is_shadow` are optimized Java-side flags for hot paths.
- If `create_item` is omitted, the factory creates a default `UItem`.

### `SimpleSettingFactory` as a builder

It implements `__call__`, usable as a small builder for `Custom(...)`:

```python
StickerFactory = SimpleSettingFactory(create_sticker_view, bind_sticker_view)
setting = StickerFactory(link_alias="sticker_preview")
# Positional args land in factory_args:
setting = StickerFactory("CactusPlugins", 0)
```

### Advanced custom factories

If `SimpleSettingFactory` is not enough, generate your own `CustomSetting.Factory` subclass through the class proxy system — see [class-proxy.md](class-proxy.md).
