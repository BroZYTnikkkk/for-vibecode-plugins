# Hook Utilities / Reflection (hook_utils)

Source: `from hook_utils import find_class, get_private_field, set_private_field, get_static_private_field, set_static_private_field`

Java reflection helpers — find classes and access/modify private fields. Essential for advanced Xposed hooking when you need non-public members.

> **Use with caution.** Reflection is fragile — it breaks if the underlying app code changes. Always wrap in `try/except` and check for `None` returns.

## `find_class(class_name: str) -> Optional[JavaClass]`

Safely finds a Java class by fully qualified name. Returns the `Class` object or `None`.

```python
from hook_utils import find_class

ActionBarClass = find_class("org.telegram.ui.ActionBar.ActionBar")
if ActionBarClass:
    self.log(f"Found: {ActionBarClass.getName()}")
else:
    self.log("Could not find class.")
```

> `find_class(...)` already returns a Java `Class`. Call `getDeclaredMethod(...)` / `getDeclaredConstructor(...)` directly on it — **do not** call `getClass()` first.

## `get_private_field(obj, field_name: str)`

Accesses a private/public **instance** field anywhere in the class hierarchy. Returns the value or `None`.

```python
from hook_utils import get_private_field

# chatActivity is an instance of org.telegram.ui.ChatActivity
chat_list_view = get_private_field(chatActivity, "chatListView")
if chat_list_view:
    self.log("Accessed chatListView.")
```

## `set_private_field(obj, field_name: str, new_value) -> bool`

Modifies a private/public instance field. Returns `True` on success.

```python
from hook_utils import set_private_field

user_object = ...
success = set_private_field(user_object, "verified", True)
if success:
    self.log("User is now verified!")
```

## `get_static_private_field(clazz, field_name: str)`

Accesses a **static** private/public field on a class.

```python
from hook_utils import find_class, get_static_private_field

ExteraConfigClass = find_class("com.exteragram.messenger.ExteraConfig")
if ExteraConfigClass:
    config_loaded = get_static_private_field(ExteraConfigClass, "configLoaded")
    self.log(f"Config loaded: {config_loaded}")
```

## `set_static_private_field(clazz, field_name: str, new_value) -> bool`

Modifies a **static** private/public field on a class.

```python
from hook_utils import find_class, set_static_private_field

BuildVarsClass = find_class("org.telegram.messenger.BuildVars")
if BuildVarsClass:
    if set_static_private_field(BuildVarsClass, "DEBUG_VERSION", True):
        self.log("DEBUG_VERSION enabled.")
```

## Full Hooking Flow

Reflection + Xposed hooking together:

```python
from base_plugin import MethodHook
from hook_utils import find_class
from java import jint

class ToastHook(MethodHook):
    def before_hooked_method(self, param):
        # makeText(Context, CharSequence, int)
        original = param.args[1]
        param.args[1] = f"(Plugin) {original}"

ToastClass = find_class("android.widget.Toast")
ContextClass = find_class("android.content.Context")
CharSequenceClass = find_class("java.lang.CharSequence")

make_text = ToastClass.getDeclaredMethod("makeText", ContextClass, CharSequenceClass, jint)
make_text.setAccessible(True)
self.hook_method(make_text, ToastHook())
```

See [xposed-hooking.md](xposed-hooking.md) for the full `MethodHook` / `HookFilter` API.
