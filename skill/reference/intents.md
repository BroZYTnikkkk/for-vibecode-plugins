# Intents (intents)

Source: `from intents import IntentsManager as IM`

Register global **before** and **after** handlers for Telegram links, deeplinks, and custom intents.

> Only available on **exteraGram 66999 (12.6.4)** and newer.

Register:

- `new_global_before_handler(...)` — runs **before** the original method; can stop further handling.
- `new_global_after_handler(...)` — runs **after** the original method.

## Registration

```python
from intents import IntentsManager as IM

def on_chat_link(id):
    print("Chat id:", id)

handle = IM.new_global_before_handler(
    on_chat_link,
    scheme="tg",
    host="chat",
    required_path_args_names=["id"],
)
```

Both methods return a `HandlerHandle` — call `.unhandle()` to remove.

## Filters

Both registration methods accept the same filter arguments.

### `scheme`

Matches `intent.data.scheme`.

```python
handle = IM.new_global_before_handler(fn, scheme="tg")
```

### `host`

Matches `intent.data.host`.

```python
handle = IM.new_global_before_handler(fn, scheme="tg", host="chat")
```

### `path`

Matches `intent.data.path`. Adds a leading `/` automatically if missing.

```python
handle = IM.new_global_before_handler(fn, scheme="tg", host="profile", path="/user/42")
```

`path` supports **template variables** like `{user_id}`:

```python
def on_profile(user_id, path=None):
    print("User:", user_id, "Full:", path)

handle = IM.new_global_before_handler(
    on_profile,
    scheme="tg",
    host="profile",
    path="/user/{user_id}",
)
```

### `required_path_args_names`

Despite the name, this currently means **required query arguments**. If one is missing, the handler does not run.

```python
def on_chat(id):
    print("Chat:", id)

handle = IM.new_global_before_handler(
    on_chat,
    scheme="tg",
    host="chat",
    required_path_args_names=["id"],
)
```

Matches `tg://chat?id=123`; does **not** match `tg://chat`.

### `action`, `type`, `categories`

Match `intent.getAction()` / `intent.getType()` / `intent.getCategories()` (every listed category must be present).

```python
from android.content import Intent

handle = IM.new_global_before_handler(fn, action=Intent.ACTION_VIEW)
handle = IM.new_global_before_handler(fn, type="text/plain")
handle = IM.new_global_before_handler(fn, categories=[Intent.CATEGORY_BROWSABLE])
```

### `whitelist_flags` / `blacklist_flags`

Require every listed flag / reject if any listed flag is present in `intent.getFlags()`.

```python
from android.content import Intent

handle = IM.new_global_before_handler(
    fn,
    whitelist_flags=[Intent.FLAG_ACTIVITY_NEW_TASK],
)
handle = IM.new_global_before_handler(
    fn,
    blacklist_flags=[Intent.FLAG_ACTIVITY_LAUNCHED_FROM_HISTORY],
)
```

### `priority`

Handlers are sorted by ascending priority — lower numbers run first.

```python
IM.new_global_before_handler(first, scheme="tg", priority=0)
IM.new_global_before_handler(second, scheme="tg", priority=10)
```

## Callback Arguments

The SDK inspects your callback signature and **only passes values the function explicitly asks for**.

Standard names: `intent`, `scheme`, `host`, `path`, `query_args`, `action`, `flags`, `type`, `categories`.

Additionally:
- every query argument by name (e.g. `id`, `plugin`)
- every path-template variable by name (e.g. `user_id` from `/user/{user_id}`)

### One named value

```python
def on_link(host):
    print(host)
IM.new_global_before_handler(on_link, scheme="tg")
```

### Query args by name

```python
def on_setting_link(plugin, section=None):
    print("Plugin:", plugin, "Section:", section)
IM.new_global_after_handler(on_setting_link, scheme="https")
```

### `**kwargs` — full context

```python
def on_any_link(**kwargs):
    print(kwargs["intent"])
    print(kwargs.get("scheme"))
    print(kwargs.get("id"))
IM.new_global_before_handler(on_any_link, scheme="tg")
```

### `*args` — standard positional bundle

```python
def on_any_link(*args):
    intent, scheme, host, path, query_args, action, flags, type, categories = args
IM.new_global_before_handler(on_any_link, scheme="tg")
```

## Stopping Further Handling (before handlers only)

Return `True` from a before callback to stop the rest of the Python handlers **and** the original Java intent handling.

```python
def intercept_chat(id):
    print("Intercepted:", id)
    return True

IM.new_global_before_handler(
    intercept_chat,
    scheme="tg",
    host="chat",
    required_path_args_names=["id"],
)
```

- Only before handlers can stop handling.
- Once a before callback returns `True`, later handlers are not called.
- The SDK calls `param.setResult(true)` on the Java side.
- after handlers cannot stop the original flow.

Any value other than `True` does not stop handling.

## HandlerHandle and unhandle

```python
from intents import IntentsManager as IM

def on_link():
    print("called")

handle = IM.new_global_before_handler(on_link, scheme="tg")
handle.unhandle()
```

Or remove by id:

```python
IM.unhandle(handle.handler_id)
```

`IM.unhandle(...)` raises `IntentsManager.HandlerNotRegistered` if the id does not exist.

## `parse(url: str) -> dict`

Helper for parsing URL-like strings. Returns at least `scheme` and `host`; may include `path` and `query`.

```python
from intents import IntentsManager as IM

parts = IM.parse("tg://chat?id=123")
print(parts["scheme"])  # "tg"
print(parts["host"])    # "chat"
print(parts["query"])   # "id=123"
```

## Notes

- Matching by `scheme`/`host`/`path`/query/action/flags/type/categories happens on the **Java side**.
- Only matching handler ids are dispatched to Python.
- Handlers run in ascending `priority` order.
- `required_path_args_names` currently means required query-argument names.
