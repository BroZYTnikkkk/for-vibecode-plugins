# Android Utilities (android_utils)

Source: `from android_utils import run_on_ui_thread, R, OnClickListener, OnLongClickListener, log, copy_to_clipboard`

Small but frequently used helpers for Android-side work: UI thread, click listeners, logging, clipboard.

## Wrappers for Java Interfaces

### `R(fn)` — Runnable proxy

Creates a real `java.lang.Runnable` backed by a Python callable. Use when an API explicitly requires a `Runnable`.

```python
from android_utils import R, log

def my_task():
    log("Runnable task executed.")

runnable_instance = R(my_task)
some_view.post(runnable_instance)
```

> `run_on_ui_thread(...)` already wraps your callable in a `Runnable` internally. Use `R(...)` only when an API explicitly requires a `Runnable` object.

### `OnClickListener(fn)`

Convenience wrapper for `android.view.View.OnClickListener`. The callable receives the clicked `View`.

```python
from android_utils import OnClickListener, log
from android.view import View

def handle_button_click(view: View):
    log(f"Button {view.getId()} was clicked.")

button.setOnClickListener(OnClickListener(handle_button_click))
```

### `OnLongClickListener(fn)`

Wrapper for `android.view.View.OnLongClickListener`. The callable must return a bool: `True` to consume, `False` to let Android continue.

```python
from android_utils import OnLongClickListener, log

def handle_long_click(view):
    log(f"Long-clicked {view.getId()}")
    return True

button.setOnLongClickListener(OnLongClickListener(handle_long_click))

# Lambda form:
button.setOnLongClickListener(
    OnLongClickListener(lambda v: (log("Long click!"), True)[1])
)
```

## Utility Functions

### `run_on_ui_thread(func, delay=0)`

Schedules a Python callable on the Android UI thread. All UI mutations (changing text, updating views, showing dialogs, attaching adapters) must happen here.

```python
from android_utils import run_on_ui_thread

def update_ui():
    text_view.setText("Updated on UI thread")

run_on_ui_thread(update_ui)
run_on_ui_thread(update_ui, 500)  # 500 ms delay
```

### `log(data)`

Sends data into the app's logging pipeline.

- Simple values (`str`, `int`, `float`, `bool`, `None`) log as text.
- Complex objects go to the Java-side object inspector — useful for debugging Telegram/Android objects.

```python
from android_utils import log

log("Simple message.")
log(f"Current account: {2}")
log(True)
log(user_object)   # inspected
log(some_list)     # inspected

try:
    x = 1 / 0
except Exception as e:
    log(f"Error: {e}")
    import traceback
    log(traceback.format_exc())
```

### `copy_to_clipboard(text)`

Copies a string to the Android clipboard and, on success, shows the standard "copied" bulletin.

```python
from android_utils import copy_to_clipboard

copy_to_clipboard("https://t.me/exteraPlugins")
```

Useful for deeplinks, debug info, exported IDs, user-facing share actions.
