# UI Helpers (ui.bulletin, ui.alert)

Source: `from ui.bulletin import BulletinHelper` · `from ui.alert import AlertDialogBuilder`

Telegram-style bulletins (bottom-screen notifications) and alert dialogs.

## BulletinHelper

Static/class methods that show Telegram's "Bulletin" — small, non-intrusive messages at the bottom that dismiss automatically.

Fragment fallbacks when not passed explicitly: the fragment you passed → current safe fragment from `LaunchActivity` → the visible bulletin bottom sheet → the global bulletin factory.

> All `show_...` methods ensure the bulletin is shown on the Android UI thread — no need to wrap in `run_on_ui_thread`.

```python
from ui.bulletin import BulletinHelper
from client_utils import get_last_fragment
from org.telegram.messenger import R as R_tg  # for Lottie animation resource ids

current_fragment = get_last_fragment()

BulletinHelper.show_info("Information.", current_fragment)
BulletinHelper.show_error("An error occurred.", current_fragment)
BulletinHelper.show_success("Done!", current_fragment)
```

### Standard bulletins

| Method | Description |
|--------|-------------|
| `show_info(message, fragment=None)` | default info icon |
| `show_error(message, fragment=None)` | default error icon |
| `show_success(message, fragment=None)` | default success icon |

### Custom simple bulletins

```python
BulletinHelper.show_simple("Processing...", R_tg.raw.timer, current_fragment)
BulletinHelper.show_two_line("Download Complete", "Saved to gallery.", R_tg.raw.ic_download_done, current_fragment)
```

### Bulletins with actions

```python
def open_settings_action():
    print("Settings clicked!")

BulletinHelper.show_with_button(
    "Settings updated.",
    R_tg.raw.info,
    "Configure",
    open_settings_action,
    current_fragment,
)
```

### Undo-style

```python
def perform_delete():
    print("Permanently deleted.")

def undo_delete():
    print("Undone.")

BulletinHelper.show_undo(
    "Item moved to trash.",
    on_undo=undo_delete,
    on_action=perform_delete,
    fragment=current_fragment,
)
```

### Contextual bulletins (predefined)

| Method | Description |
|--------|-------------|
| `show_copied_to_clipboard(message=None, fragment=None)` | "Text copied" |
| `show_link_copied(is_private_link_info=False, fragment=None)` | "Link copied" |
| `show_file_saved_to_gallery(is_video=False, amount=1, fragment=None)` | "Photo/Video saved" |
| `show_file_saved_to_downloads(file_type_enum_name="UNKNOWN", amount=1, fragment=None)` | "File saved to downloads" — `file_type_enum_name` is a `BulletinFactory.FileType` enum name (e.g. `"MUSIC"`, `"PHOTO_TO_DOWNLOADS"`, `"GIF"`) |

### Durations

`BulletinHelper.DURATION_SHORT` (1500ms), `BulletinHelper.DURATION_LONG` (2750ms), `BulletinHelper.DURATION_PROLONG` (5000ms). Use with `show_with_button`.

### Finding Lottie animations

Browse Telegram source `TMessagesProj/src/main/res/raw/` for available animations (e.g. `info.json`, `success.json`, `delete.json`). Access as `R_tg.raw.info`.

## AlertDialogBuilder

Source: `from ui.alert import AlertDialogBuilder`

Pythonic wrapper for `org.telegram.ui.ActionBar.AlertDialog.Builder`.

### Basic message dialog

```python
from ui.alert import AlertDialogBuilder
from client_utils import get_last_fragment
from android_utils import log

current_fragment = get_last_fragment()
if not current_fragment:
    log("No current fragment.")
    # return / handle

activity = current_fragment.getParentActivity()
if not activity:
    log("No parent activity.")
    # return / handle

builder = AlertDialogBuilder(activity)  # default ALERT_TYPE_MESSAGE
builder.set_title("My Plugin Alert")
builder.set_message("Important message.")

def on_positive(bld: AlertDialogBuilder, which: int):
    log("Positive!")
    bld.dismiss()

def on_negative(bld: AlertDialogBuilder, which: int):
    log("Negative!")
    bld.dismiss()

builder.set_positive_button("OK", on_positive)
builder.set_negative_button("Cancel", on_negative)

builder.create()
builder.set_cancelable(True)
builder.show()
```

### Dialog types

Pass `progress_style` to the constructor:

| Type | Description |
|------|-------------|
| `AlertDialogBuilder.ALERT_TYPE_MESSAGE` (default) | standard message dialog |
| `AlertDialogBuilder.ALERT_TYPE_LOADING` | determinate progress bar — use `builder.set_progress(value)` |
| `AlertDialogBuilder.ALERT_TYPE_SPINNER` | indeterminate spinner for loading |

```python
loading = AlertDialogBuilder(activity, AlertDialogBuilder.ALERT_TYPE_SPINNER)
loading.set_title("Loading Data...")
loading.set_message("Please wait.")
loading.show()
loading.set_cancelable(False)  # best after create() or show()
# later: loading.dismiss()
```

### Key methods

**Content:** `set_title(title)`, `set_message(message)`, `set_message_text_view_clickable(clickable)`, `set_view(view, height=-2)`, `set_items(items, listener=None, icons=None)`.

**Buttons:** `set_positive_button(text, listener=None)`, `set_negative_button(text, listener=None)`, `set_neutral_button(text, listener=None)`. Listeners receive `(AlertDialogBuilder, button_id)`. `make_button_red(button_type)` styles a button red (e.g. `AlertDialogBuilder.BUTTON_NEGATIVE`).

**Listeners:** `set_on_back_button_listener(...)`, `set_on_dismiss_listener(...)`, `set_on_cancel_listener(...)`.

**Appearance/behavior:** `set_top_image(res_id, bg_color)`, `set_top_drawable(drawable, bg_color)`, `set_top_animation(res_id, size, auto_repeat, bg_color, layer_colors=None)`, `set_dim_enabled(enabled)`, `set_dialog_button_color_key(theme_key)`, `set_blurred_background(blur, blur_behind_if_possible=True)`, `set_cancelable(cancelable)` (after create/show), `set_canceled_on_touch_outside(cancel)` (after create/show).

**Lifecycle:** `create() -> AlertDialogBuilder`, `show() -> AlertDialogBuilder`, `dismiss()`, `get_dialog() -> Optional[AlertDialog]`, `get_button(button_type) -> Optional[View]` (after create/show).

**Progress:** `set_progress(progress)` for `ALERT_TYPE_LOADING` (0–100).

### Dialog with items

```python
def on_item_click(bld: AlertDialogBuilder, which: int):
    items = ["Option A", "Option B", "Option C"]
    log(f"Selected: {items[which]} (index {which})")
    bld.dismiss()

item_builder = AlertDialogBuilder(activity)
item_builder.set_title("Choose an Option")
item_builder.set_items(["Option A", "Option B", "Option C"], on_item_click)
item_builder.set_negative_button("Cancel", lambda b, w: b.dismiss())
item_builder.show()
```

### Important notes

- **Context:** always pass a valid Android `Context` (usually an `Activity`). `get_last_fragment().getParentActivity()` is the common way.
- **Listeners:** receive the Python `AlertDialogBuilder` as first arg — call `bld.dismiss()` from inside.
- **Thread safety:** dialog manipulation should happen on the UI thread — wrap with `run_on_ui_thread` from background threads.
- **Error handling:** proxy listeners include try/except that logs errors from your Python callbacks, preventing crashes.
