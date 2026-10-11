# Elyx — Structured Multi-File Plugins

Elyx is the structured plugin format: keeps the `BasePlugin` API, but removes the one-file constraint. An Elyx archive can contain any number of Python modules, resources (images/SVG/Lottie/JSON/YAML), localization files, and bundled wheels.

> Requires SDK `>=1.4.5.3`. Declare it: `sdk_version: ">=1.4.5.3"`.

## When to Use Elyx

Use a regular single-file plugin when the implementation is small with no resources. Use Elyx when at least one is true:
- the source has grown into several modules
- UI needs bundled images/animations/config files
- text needs translation without editing Python code
- the plugin needs local libraries or a repeatable build
- several people work on the plugin
- fast file sync is more convenient than reinstalling a `.py` file

Elyx does **not** replace the rest of the SDK — lifecycle, hooks, menu items, requests, settings rows, class proxy, and Xposed-style hooking all still apply.

## Archive Layout

Elyx archives are ZIP-compatible with extension `.elyx`, `.eaf`, `.elyx.zip`, or `.eaf.zip`. The installable archive must contain project files directly at its root:

```
my_plugin.elyx
|-- refmap.yml        <- discovered at root
|-- metainfo.yml
|-- main.py
|-- src/
|-- assets/
`-- strings/
```

**Do not** add an extra wrapper directory (`my_plugin/refmap.yml` is wrong).

## refmap.yml

Maps physical layout to runtime meaning. Supported formats (discovered in order): `refmap.yaml`, `refmap.yml`, `refmap.json`. YAML is recommended.

```yaml
metainfo: metainfo.yml    # path to metadata
main: main.py             # entry module (must contain a BasePlugin subclass)
assets: assets            # resource directory
strings: strings          # localization file or directory
wheels: wheels            # bundled .whl directory
```

Runtime keys:

| Key | Required | Description |
|-----|----------|-------------|
| `main` | no (default `main.py` at root) | entry module; first `BasePlugin` subclass is instantiated |
| `metainfo` | no (auto-discovered) | path to metadata file |
| `assets` | no (auto-discovered) | resource directory |
| `strings` | no (auto-discovered) | localization file or directory |
| `wheels` | no | directory of bundled `.whl` files |

> Keep **one plugin class** in the entry module. Import helper classes from other files.

## metainfo.yml

```yaml
id: better_previews          # 2-32 chars, ASCII letters/digits/_ only
name: Better Previews
description: "{plugin_description}"   # markdown, supports {locale_key} placeholders
author: "@yourUsername"
version: "1.2.0"             # quote YAML strings!
icon: exteraPlugins/1
app_version: ">=12.5.1"
sdk_version: ">=1.4.5.3"
requirements: "requests>=2.32, PyYAML>=6"
requires:
  helper_plugin (1.4.0): https://example.com/helper_plugin.elyx
```

Field rules:
- `id` and `name` are required.
- `description` supports markdown and `{locale_key}` placeholders (resolved at load from current locale → English → key name).
- `version` / `app_version` / `sdk_version` should be **quoted** to avoid YAML reinterpretation.
- `requirements`: comma-separated string (or empty).
- `requires`: mapping of plugin id → optional `(min_version)` → optional download link.
- `min_version` is legacy — prefer `app_version`.

## Public API

Import only from `elyx`:

```python
from elyx import (
    Asset, AssetNotFoundException, Assets, AssetsDirNotFoundException,
    Callback, Callback2, Callback3, CallbackReturn, LazyDict,
    OnClickListener, Runnable, SettingsController, Strings,
    gen, gen2, get_environment, import_module, mvel_execute,
)
```

Plugin-bound environment values (not in `__all__`, accessed explicitly):

```python
from elyx import assets, metainfo, refmap, settings, strings
```

| Name | Available when |
|------|----------------|
| `settings` | always |
| `metainfo` | metadata loaded successfully |
| `refmap` | a refmap loaded |
| `assets` | asset directory declared or discovered |
| `strings` | at least one localization value loaded |

### `get_environment()`

Returns the full environment dict for the calling plugin. Raises `RuntimeError` outside Elyx plugin code.

```python
from elyx import get_environment
env = get_environment()
settings = env["settings"]
assets = env.get("assets")
strings = env.get("strings")
```

### `import_module(name, package=None)`

Imports a matching module relative to the calling plugin; falls back to normal Python import when no local module exists. Prefer over `importlib.import_module` for local modules.

## Modules and Imports

Every installed plugin gets its own namespace `ElyxPlugins.<plugin_id>.*` — you never type it. Two plugins can both have `src/greeting.py` without collision.

```python
# main.py
from helpers import normalize_url           # absolute
from features.links import build_preview
from .helpers import normalize_url          # relative
```

JSON/YAML/YML/TXT files import as data modules:

```python
import config        # config.json -> config.api_url, config["limits"].page_size
import notice        # notice.txt -> notice.content
```

### Reserved module roots

Do **not** create local packages with these names: `android`, `androidx`, `base_plugin`, `client_utils`, `com`, `de`, `elyx`, `hook_utils`, `importlib`, `java`, `org`, `ui`. Also avoid shadowing stdlib names (`json`, `pathlib`, `typing`).

## Assets

Declare in `refmap.yml`: `assets: plugin/res`. Import the plugin-bound collection:

```python
from elyx import assets

logo = assets.logo             # attribute lookup (normalized stem)
logo = assets["logo"]          # item access
logo = assets.get("logo")      # .get()
logo = assets["logo.svg"]      # full filename also works
add_icon = assets["icons/add"] # nested paths
add_icon = assets.icons.add
```

Attribute lookup normalizes non-alphanumerics to `_`: `empty-state.svg` → `assets.empty_state`. Avoid ambiguous stems (`logo.svg` and `logo.png` both normalize to `logo` — use full filename).

### Content methods

```python
raw_bytes = assets.banner.content_bytes()
text = assets.about.content_string()
json_data = assets.loading.content_json()
yaml_data = assets.defaults.content_yaml()
automatic = assets.defaults.content()   # parses json/yaml/yml → dict, else UTF-8 text, else bytes
```

### Android image helpers

```python
drawable = assets.banner.to_drawable()
location = assets.banner.to_image_location()
bitmap = assets.banner.to_bitmap_drawable(width=64, height=64)
svg_drawable = assets.logo.to_svg_drawable()
svg_bitmap = assets.logo.to_svg_bitmap(width=48, height=48)
white_bitmap = assets.logo.to_svg_bitmap(48, 48, white=True)
animation = assets.loading.to_lottie_drawable(width=32, height=32)

# Themed thumbnail:
from org.telegram.ui.ActionBar import Theme
thumb = assets.logo.to_svg_thumb(Theme.key_windowBackgroundWhiteBlueIcon, 1.0)
```

### Asset from path / URL

```python
from elyx import Asset

asset = Asset.from_path("/absolute/path/to/file.svg")   # also pathlib.Path / java.io.File
remote = Asset.temp_asset_from_url(
    "https://example.com/icon.svg",
    "downloaded_icon.svg",
)  # synchronous network+file I/O — run on a background queue, never in a UI callback
```

Bundled asset paths are **read-only**. Store mutable user data via [file-utils.md](file-utils.md).

## Localization

Declare in `refmap.yml`: `strings: plugin/locales`. Locale = part after the final `_` in the filename stem.

```
plugin/locales/
|-- strings_en.yml   -> en
|-- strings_ru.yml   -> ru
`-- strings_de.json  -> de
```

`strings.yml` (no locale in stem) is treated as `en`. Supported formats: `.yaml`, `.yml`, `.json`, `.py`. **Always ship an English catalog** as the fallback.

```yaml
# strings_en.yml
plugin_description: Adds useful greeting actions.
title: Greetings
hello: "Hello, {name}!"
downloaded: "Downloaded {count} files"
file_forms:
  - file
  - files
  - files
```

Read:

```python
from elyx import strings

title = strings["title"]
title = strings.title
title = strings.get("title")
title = strings("title")                       # callable form
message = strings("hello", name="Alice")       # formatted
downloaded = strings("downloaded", count=5)
coordinates = strings("coordinates", 10, 20)   # positional placeholders
```

Fallback order: selected plugin locale → English → the requested key itself.

```python
strings.get("missing_key")             # "missing_key"
strings.get("opt", "Fallback")         # "Fallback"
strings("opt", default="Fallback")
strings.get_with_locale("title", locale="ru")
strings("title", locale="en")
```

### Plural forms

`strings.pluralize(n, "file_forms")` uses three Slavic-style forms. Not a full CLDR engine — for languages with different plural rules, select the form in code or store complete phrases.

### Localize metadata

```yaml
# metainfo.yml
description: "{plugin_description}"
```
```yaml
# strings_en.yml
plugin_description: Adds better link previews.
```

Placeholders resolve at load with the same current-locale → English fallback.

## Settings Storage

`settings` is a `SettingsController` bound to the plugin id, same storage as `BasePlugin.get_setting` / settings rows.

```python
from elyx import settings

enabled = settings.get_setting("enabled", True)   # or settings.get(...)
enabled = settings["enabled"]
settings.set_setting("enabled", True)
settings["username"] = "Alice"
settings.set("mode", "advanced", reload_settings=True)
values = settings.get_settings()
settings.clear_settings()
```

## Dependencies

Three mechanisms — pick the smallest that fits.

### 1. PIP requirements

```yaml
requirements: "requests>=2.32, tinydb>=4.8"
```

The host PIP controller installs packages before importing `main`. Then normal imports work:

```python
import requests
from tinydb import TinyDB
```

> Android is not desktop Python. Packages with native extensions need a build compatible with Python 3.11, Android, and the device ABI. Windows/macOS/Linux wheels won't work.

### 2. Bundled wheels

```yaml
# refmap.yml
wheels: wheels
```

```
wheels/
|-- my_library-1.0.0-py3-none-any.whl
`-- another_library-2.1.0-py3-none-any.whl
```

Elyx extracts each wheel into plugin-specific local lib storage. **Rebuild or rename** the wheel when contents change — Elyx identifies extracted wheels by filename stem.

### 3. Local source packages

Small libraries don't need a wheel:

```
vendor/
|-- __init__.py
`-- parser.py
```
```python
from vendor.parser import parse
```

Local source is namespaced per plugin and participates in live reload.

### 4. Required plugins

```yaml
requires:
  helper_plugin: https://example.com/helper_plugin.elyx
  shared_runtime (2.1.0): https://example.com/shared_runtime.elyx
```

The installer reports missing/disabled/outdated required plugins. This checks availability — it does **not** create a stable Python API between plugins.

## ElyxBuilder CLI

```powershell
python -m pip install --upgrade ElyxBuilder
```

Requires Python 3.10+ (3.11 for compiled `.pyc` builds). Verify: `elyb --version && elyb --help`.

### Create a project

```powershell
elyb new
# or non-interactive:
elyb new -g -n "My Plugin" -a authorname
# Choose archive extension:
elyb new -g -n "My Plugin" -a authorname --zipformat elyx
```

Generates `refmap.yml` at the repo root plus a normalized plugin directory.

### Build

Run from the directory containing `refmap.yml`:

```powershell
elyb build --ast --verbose --no-folder      # source build with syntax validation
elyb build --compile 2 --verbose --no-folder # compiled build (Python 3.11 bytecode)
elyb build -c 2 -v -nf                       # short form
```

Builds go to `builds/`. `--ast` and `--compile` are mutually exclusive.

Useful options: `-v` verbose, `-a` AST validate, `-c [LEVEL]` compile (0/1/2), `-r` reset compile cache, `-nf` exclude `.elyxbuilder`, `--no-assets`, `-ni` no build info.

### Watch (rebuild on change)

```powershell
elyb watch 10 --args "--ast -v -nf"
```

First arg = polling interval (seconds). Latest build saved to `builds/latest.eaf`. In the interactive screen: `P` pause/resume, `Q` exit. `watch` rebuilds but does **not** install — use the `elyx_dev_client.py` workflow for that.

### Ignore lists

```powershell
elyb add-ignore "MyPlugin/generated/*" --all
elyb add-ignore "MyPlugin/res/preview.psd" --no-assets
elyb add-ignore "MyPlugin/src/compat.py" --compile
elyb del-ignore 0 --all
```

### Stats

```powershell
elyb stats builds
elyb stats lines
elyb stats size
elyb stats files
```

## Development and Reload

Productive loop: edit on PC → sync changed files → Elyx unloads + reloads the plugin → inspect errors → repeat.

### Prerequisites

- recent exteraGram with plugin support, plugin engine + developer mode enabled
- the SDK available to the IDE
- Python 3.11 for bytecode-compatible builds
- ADB for USB/emulator
- an Elyx archive **already installed** on the device (initial install)

### ADB forward

The dev server binds `127.0.0.1:42690` on the phone:

```powershell
adb devices
adb forward tcp:42690 tcp:42690
# Remove and recreate if another device was connected:
adb forward --remove tcp:42690
adb forward tcp:42690 tcp:42690
```

### `elyx_dev_client.py`

A custom client (not bundled in the SDK) that compares file hashes, sends created/modified/moved/deleted paths, and waits for the engine to reload the plugin.

```powershell
python elyx_dev_client.py --help
```

Needs: server host/port (`127.0.0.1:42690` after ADB forward), local project root, plugin id, ignore patterns (`.git`, `.elyx`, `builds`, `__pycache__`, IDE files). Keep the client version with your team — its CLI is not part of the runtime API.

### Reload-safe code

Elyx clears plugin-local Python modules, hooks, and menu items. **You** are responsible for:
- threads, sockets, observers, custom listeners created by your code (stop them in `on_plugin_unload`)
- mutations to third-party modules (process-global until restart)

```python
class ReloadSafePlugin(BasePlugin):
    def on_plugin_load(self):
        self.closed = False
        self.worker = create_worker()
        self.worker.start()

    def on_plugin_unload(self):
        self.closed = True
        if self.worker:
            self.worker.stop()
            self.worker = None
```

Avoid starting permanent work at module import time — put init in `on_plugin_load`.

## Build a plain archive (no ElyxBuilder)

For source distributions, any ZIP tool works when it preserves paths. Archive project contents so `refmap.yml` is at the ZIP root, then rename: `my_plugin.zip → my_plugin.elyx`.

### Release checklist

- install from a clean archive, not only through live reload
- test the default locale and English fallback
- test with missing network access when dependencies are involved
- disable and re-enable the plugin
- update from the previous public version
- verify every declared asset and localization path
- inspect the archive root for accidental wrapper directories
- confirm id, version constraints, dependency links

Do **not** ship: `.git/`, `.elyx/cache/`, `builds/`, `__pycache__/`, desktop virtualenvs, secrets/API keys/signing material/local logs.

## Java Callback Proxies (from Elyx)

Elyx exports ready-to-instantiate proxy classes:

| Name | Java interface | Method |
|------|----------------|--------|
| `OnClickListener` | `android.view.View.OnClickListener` | `onClick` |
| `Runnable` | `java.lang.Runnable` | `run` |
| `Callback` / `Callback2` / `Callback3` | `Utilities.Callback[2/3]` | `run` |
| `CallbackReturn` | `CallbackUtilities.CallbackReturn` | `run` (returns value) |

```python
from elyx import OnClickListener, Runnable

button.setOnClickListener(OnClickListener(lambda view: self.log("Clicked")))
queue.postRunnable(Runnable(lambda: self.log("Running")))
```

Extra constructor arguments are appended to Java callback arguments:

```python
def on_click(view, item_id):
    self.log(f"Clicked {item_id}")
button.setOnClickListener(OnClickListener(on_click, "save"))
```

### `gen` / `gen2` — one-off proxies

```python
from android.content import DialogInterface
from elyx import gen

OnDismiss = gen(DialogInterface.OnDismissListener, "onDismiss")
dialog.setOnDismissListener(OnDismiss(lambda d: self.log("Dismissed")))

# Callback returning a value:
Predicate = gen(SomeJavaPredicate, "test", return_value=True, default_value=False)
predicate = Predicate(lambda value: value is not None)
```

`gen2` for multi-method interfaces:

```python
from elyx import gen2

Listener = gen2(
    SomeJavaListener,
    onStart=lambda v: log_start(v),
    onFinish=lambda v: log_finish(v),
)
instance = Listener()
```

### `mvel_execute(script, data, to_type=None, java_instance=None)`

Compile+cache an MVEL expression, convert a Python dict to `java.util.HashMap`, execute:

```python
from elyx import mvel_execute

visible = mvel_execute("enabled && count > 0", {"enabled": True, "count": 3})
```

## Troubleshooting

- **"Archive not recognized"** — check extension (`.elyx` / `.eaf` / `.elyx.zip` / `.eaf.zip`), file downloaded completely, plugin engine + Elyx engine available, valid ZIP.
- **"Metainfo not found"** — root must contain a discoverable metadata file or `refmap` must point to one.
- **Invalid plugin id** — 2–32 ASCII letters, digits, `_` (no hyphens, spaces, non-ASCII).
- **"Main file not found"** — check path and capitalization; paths are case-sensitive on Android.
- **No `BasePlugin` subclass** — entry module must expose one concrete subclass; keep one plugin class in the entry module.
- **Local import fails** — match filename capitalization, add `__init__.py`, don't use reserved roots, rebuild Python 3.11 bytecode if `.pyc` is rejected.
- **`from elyx import assets` fails** — `assets` is dynamic; declare `assets: ...` in refmap and verify the directory exists. For optional assets use `get_environment().get("assets")`.
- **`from elyx import strings` fails** — no translations loaded; check `strings` path, supported extensions, valid UTF-8, at least one public key/value.
- **A translation returns its key** — fallback behavior; add the key to the selected locale or English.
- **Settings don't update the screen** — use `reload_settings=True` only when row visibility/structure depends on the value.
- **PIP dependency fails** — check spelling/constraints, Python 3.11 compatibility, Android/ABI support for native extensions, network availability.
- **Bundled wheel doesn't update** — Elyx identifies wheels by filename stem; rebuild with a new version/filename.
- **Live reload says plugin not found** — verify local metadata id matches installed id, archive was installed, engine completed startup, plugin appears in `get_elyx_plugins`, ADB forward on 42690.
- **Reload succeeds but old behavior remains** — background threads not stopped, listeners/observers outside plugin APIs, monkey patches to shared modules, cached values in third-party modules. Move setup into `on_plugin_load` and cleanup into `on_plugin_unload`. Final diagnostic: restart the app.
