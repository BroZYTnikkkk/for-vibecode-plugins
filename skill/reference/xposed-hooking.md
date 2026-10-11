# Xposed-Style Method Hooking

Source: `from base_plugin import MethodHook, MethodReplacement, BaseHook, HookFilter, hook_filters`

Intercept Java method calls, modify arguments, inspect or replace return values, or skip the original implementation entirely. Powerful and easy to misuse.

## Hook Handler Styles

### 1. `MethodHook` — before/after

```python
from base_plugin import MethodHook

class TitleLoggerHook(MethodHook):
    def before_hooked_method(self, param):
        title = param.args[0]
        print(f"Title about to become: {title}")

    def after_hooked_method(self, param):
        print(f"Method finished with result: {param.getResult()}")
```

### 2. `MethodReplacement` — fully replace

```python
from base_plugin import MethodReplacement

class TitleReplacer(MethodReplacement):
    def replace_hooked_method(self, param):
        print("Original method was replaced.")
        return None
```

### 3. Functional hooks / `BaseHook`

For simpler cases, pass `before=` and/or `after=` directly:

```python
self.hook_method(
    some_method,
    before=lambda param: self.log("About to run!"),
    after=lambda param: self.log(f"Finished with result: {param.getResult()}"),
)
```

The SDK wraps that into `BaseHook` (a small `MethodHook` subclass).

## The `param` Object

All callbacks receive `de.robv.android.xposed.XC_MethodHook.MethodHookParam`.

| Member | Description |
|--------|-------------|
| `param.thisObject` | instance the method was called on, or `None` for static |
| `param.args` | method argument array — readable **and** modifiable |
| `param.method` | the hooked `Method` or `Constructor` |
| `param.getResult()` | return value of the original (available after execution) |
| `param.setResult(value)` | set a result manually |

Calling `param.setResult(...)` inside `before_hooked_method(...)` **skips the original method**:

```python
def before_hooked_method(self, param):
    if param.args[0] == "blocked":
        param.setResult(None)
```

## Filters

Filters decide whether your callback runs. Two styles:

- `@hook_filters(...)` on class-based hook methods
- `before_filters=[...]` / `after_filters=[...]` for functional hooks

```python
from base_plugin import HookFilter

self.hook_method(
    some_method,
    before=lambda p: self.log("Arg 0 is null!"),
    before_filters=[HookFilter.ArgumentIsNull(0)],
)
```

### Available `HookFilter` helpers

| Filter | Effect |
|--------|--------|
| `HookFilter.RESULT_IS_NULL` | result is `null` |
| `HookFilter.RESULT_IS_TRUE` | result is `true` |
| `HookFilter.RESULT_IS_FALSE` | result is `false` |
| `HookFilter.RESULT_NOT_NULL` | result is not `null` |
| `HookFilter.ResultIsInstanceOf(clazz)` | result is instance of `clazz` |
| `HookFilter.ResultEqual(value)` | result equals `value` |
| `HookFilter.ResultNotEqual(value)` | result not equals `value` |
| `HookFilter.ArgumentIsNull(index)` | arg at `index` is `null` |
| `HookFilter.ArgumentNotNull(index)` | arg at `index` is not `null` |
| `HookFilter.ArgumentIsFalse(index)` | arg at `index` is `false` |
| `HookFilter.ArgumentIsTrue(index)` | arg at `index` is `true` |
| `HookFilter.ArgumentIsInstanceOf(index, clazz)` | arg is instance of `clazz` |
| `HookFilter.ArgumentEqual(index, value)` | arg equals `value` |
| `HookFilter.ArgumentNotEqual(index, value)` | arg not equals `value` |
| `HookFilter.Condition(expr, object=None)` | MVEL condition |
| `HookFilter.Or(*filters)` | logical OR of filters |

### Class-based filters

```python
from base_plugin import HookFilter, MethodHook, hook_filters

class ExampleHook(MethodHook):
    @hook_filters(HookFilter.ArgumentIsNull(0))
    def before_hooked_method(self, param):
        ...

    @hook_filters(HookFilter.RESULT_NOT_NULL)
    def after_hooked_method(self, param):
        ...
```

### MVEL condition filter

```python
class ConditionalHook(MethodHook):
    @hook_filters(
        HookFilter.Condition(
            "param.args[0] == object || this instanceof android.view.View",
            object=500,
        )
    )
    def before_hooked_method(self, param):
        ...
```

## The Hooking Process

### 1. Find the target method/constructor

Start with `find_class(...)` (from `hook_utils`), then Java reflection directly.

```python
from hook_utils import find_class

ActionBarClass = find_class("org.telegram.ui.ActionBar.ActionBar")
if not ActionBarClass:
    self.log("ActionBar class not found!")
    return

# Example: public void setTitle(CharSequence title)
CharSequenceClass = find_class("java.lang.CharSequence")
set_title_method = ActionBarClass.getDeclaredMethod("setTitle", CharSequenceClass)
set_title_method.setAccessible(True)

# Example constructor: public ActionBar(Context context)
ContextClass = find_class("android.content.Context")
ctor = ActionBarClass.getDeclaredConstructor(ContextClass)
ctor.setAccessible(True)
```

> `find_class(...)` already returns a Java `Class`. Call `getDeclaredMethod(...)` / `getDeclaredConstructor(...)` on it **directly** — do not call `getClass()` first.

### 2. Implement the handler

```python
from base_plugin import MethodHook, MethodReplacement

class TitleLoggerHook(MethodHook):
    def __init__(self, plugin):
        self.plugin = plugin

    def before_hooked_method(self, param):
        title = param.args[0]
        self.plugin.log(f"Title being set to: {title}")
        param.args[0] = f"[Hooked] {title}"

    def after_hooked_method(self, param):
        self.plugin.log("Title has been set.")


class TitleReplacer(MethodReplacement):
    def __init__(self, plugin):
        self.plugin = plugin

    def replace_hooked_method(self, param):
        self.plugin.log("ActionBar.setTitle() was replaced.")
        return None
```

### 3. Apply the hook

```python
ActionBarClass = find_class("org.telegram.ui.ActionBar.ActionBar")
CharSequenceClass = find_class("java.lang.CharSequence")
method = ActionBarClass.getDeclaredMethod("setTitle", CharSequenceClass)
method.setAccessible(True)

self.unhook_obj = self.hook_method(method, TitleLoggerHook(self), priority=10)
if self.unhook_obj:
    self.log("Hooked ActionBar.setTitle()")
```

Hooks are removed automatically on plugin unload. You can also unhook manually (see step 5).

### 4. Hook all methods or all constructors

```python
MyViewClass = find_class("com.example.MyCustomView")
unhooks = self.hook_all_methods(MyViewClass, "onMeasure", TitleLoggerHook(self))
if unhooks:
    self.log(f"Hooked {len(unhooks)} onMeasure overload(s).")

SomeClass = find_class("com.example.SomeClass")
unhooks = self.hook_all_constructors(SomeClass, TitleLoggerHook(self))
```

### 5. Manual unhooking

```python
if self.unhook_obj:
    self.unhook_method(self.unhook_obj)
    self.unhook_obj = None
```

For `hook_all_methods` / `hook_all_constructors`, iterate the returned list and unhook each.

## Practical Examples

### Modify arguments before the call

```python
from base_plugin import MethodHook
from hook_utils import find_class
from java import jint

class ToastHook(MethodHook):
    def before_hooked_method(self, param):
        # makeText(Context context, CharSequence text, int duration)
        original = param.args[1]
        param.args[1] = f"(Plugin) {original}"

ToastClass = find_class("android.widget.Toast")
ContextClass = find_class("android.content.Context")
CharSequenceClass = find_class("java.lang.CharSequence")
method = ToastClass.getDeclaredMethod("makeText", ContextClass, CharSequenceClass, jint)
self.hook_method(method, ToastHook())
```

### Change the return value after the call

```python
from base_plugin import MethodHook
from hook_utils import find_class

class BuildVarsHook(MethodHook):
    def __init__(self, plugin):
        self.plugin = plugin

    def after_hooked_method(self, param):
        self.plugin.log(f"Original result: {param.getResult()}")
        param.setResult(False)

BuildVarsClass = find_class("org.telegram.messenger.BuildVars")
method = BuildVarsClass.getDeclaredMethod("isMainApp")
self.hook_method(method, BuildVarsHook(self))
```

### Skip the original call in `before_hooked_method`

```python
from base_plugin import MethodHook
from hook_utils import find_class
from java.lang import Boolean, Long

class FormatFileSizeHook(MethodHook):
    def before_hooked_method(self, param):
        size = param.args[0]
        if size < 1024:
            param.setResult(f"{size} bytes (edited)")  # skip original

AndroidUtilitiesClass = find_class("org.telegram.messenger.AndroidUtilities")
method = AndroidUtilitiesClass.getDeclaredMethod("formatFileSize", Long.TYPE, Boolean.TYPE, Boolean.TYPE)
self.hook_method(method, FormatFileSizeHook())
```

### Fully replace a method

```python
from java.lang import String as JString
from base_plugin import MethodReplacement
from hook_utils import find_class

class NoOpLogger(MethodReplacement):
    def replace_hooked_method(self, param):
        return None  # original never called

FileLogClass = find_class("org.telegram.messenger.FileLog")
method = FileLogClass.getDeclaredMethod("d", JString)
self.hook_method(method, NoOpLogger())
```

In `MethodReplacement`, return a value compatible with the original signature: `None` for void, Python primitives for primitive returns, compatible object for reference returns.
