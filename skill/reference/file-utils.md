# File Utilities (file_utils)

Source: `from file_utils import get_plugins_dir, get_cache_dir, read_file, write_file, read_file_bytes, write_file_bytes, list_dir, ensure_dir_exists, delete_file, FilesController`

Two responsibilities: filesystem helpers for common plugin tasks, and `FilesController` for intercepting file opening by extension.

## Standard Directories

```python
from file_utils import (
    get_plugins_dir,
    get_cache_dir,
    get_files_dir,
    get_images_dir,
    get_videos_dir,
    get_audios_dir,
    get_documents_dir,
)

plugins_path = get_plugins_dir()
cache_path = get_cache_dir()
files_path = get_files_dir()
images_path = get_images_dir()
videos_path = get_videos_dir()
audios_path = get_audios_dir()
documents_path = get_documents_dir()
```

## Directory Operations

### `ensure_dir_exists(path)`

Creates the directory (and missing parents) if it doesn't exist.

```python
import os
from file_utils import ensure_dir_exists, get_plugins_dir

data_dir = os.path.join(get_plugins_dir(), "my_plugin_data")
ensure_dir_exists(data_dir)
```

### `list_dir(...)`

Lists files and/or directories, with optional recursion and extension filtering.

```python
from file_utils import get_cache_dir, get_images_dir, list_dir

image_files = list_dir(
    path=get_images_dir(),
    extensions=[".jpg", ".png"],
)

cache_dirs = list_dir(
    path=get_cache_dir(),
    recursive=True,
    include_files=False,
    include_dirs=True,
)
```

Parameters:
- `recursive=False` — walk child directories
- `include_files=True`
- `include_dirs=False`
- `extensions=None` — optional suffix filter like `[".json", ".txt"]`

## File Operations

### `write_file(path, content: str)` — text

```python
write_file(os.path.join(data_dir, "config.txt"), "enabled=true")
```

### `read_file(path) -> Optional[str]`

Reads the whole file as text. Returns `None` and logs on failure.

```python
config_text = read_file(os.path.join(get_plugins_dir(), "my_plugin_data", "config.txt"))
if config_text is not None:
    print(config_text)
```

### `write_file_bytes(path, content: bytes)`

```python
from file_utils import ensure_dir_exists, get_plugins_dir, write_file_bytes

data_dir = os.path.join(get_plugins_dir(), "my_plugin_data")
ensure_dir_exists(data_dir)
write_file_bytes(os.path.join(data_dir, "payload.bin"), b"\x01\x02\x03")
```

### `read_file_bytes(path) -> Optional[bytes]`

Reads the whole file as bytes. Returns `None` and logs on failure.

```python
payload = read_file_bytes(os.path.join(get_plugins_dir(), "my_plugin_data", "payload.bin"))
if payload is not None:
    print(len(payload))
```

### `delete_file(path) -> bool`

Returns `True` if deleted, `False` if it didn't exist or deletion failed.

```python
was_deleted = delete_file("/path/to/temp.txt")
```

## FilesController

Register handlers for specific file extensions. When a user opens a registered type, your callback runs instead of the default open flow.

Typical uses: open custom file types, handle plugin-specific archives, launch a custom viewer, provide a custom icon.

> **`register(...)` returns a secret string.** Keep it safe to call `unregister(...)` later.

### `FilesController.SUPPORT_ICONS`

`True` when the current client version supports custom file icons.

```python
from file_utils import FilesController

if FilesController.SUPPORT_ICONS:
    print("Custom file icons are available.")
```

### `FilesController.Place`

Where the file open request came from: `UNKNOWN`, `ChatActivity`, `FilteredSearchView`, `SharedMediaLayout`, `SearchDownloadsContainer`, `ChannelAdminLogActivity`.

### `FilesController.FileInfo`

Fields: `ext`, `on_click`, `whitelist_places=[]`, `blacklist_places=[]`, `get_icon=None`.

Rules:
- You cannot use `whitelist_places` and `blacklist_places` together.
- `get_icon` requires `FilesController.SUPPORT_ICONS == True`.

### `FilesController.OnClickArgs`

Passed to your `on_click`: `place`, `file`, `file_name`, `message`, `activity`, `parent_fragment`.

### Register a file handler

```python
from file_utils import FilesController

def on_zip_click(args: FilesController.OnClickArgs):
    print("Opened:", args.file_name)
    print("From:", args.place)
    print("Path:", args.file.getAbsolutePath())

secret = FilesController.register(
    FilesController.FileInfo(
        ext="zip",
        on_click=on_zip_click,
    )
)
```

### Restrict to certain places

```python
secret = FilesController.register(
    FilesController.FileInfo(
        ext="txt",
        on_click=on_txt_click,
        whitelist_places=[FilesController.Place.ChatActivity],
    )
)

secret = FilesController.register(
    FilesController.FileInfo(
        ext="pdf",
        on_click=on_pdf_click,
        blacklist_places=[FilesController.Place.SearchDownloadsContainer],
    )
)
```

### Register a custom icon

```python
def make_zip_icon():
    return my_drawable  # Android Drawable instance

def on_zip_click(args):
    print("ZIP opened:", args.file_name)

if FilesController.SUPPORT_ICONS:
    secret = FilesController.register(
        FilesController.FileInfo(
            ext="zip",
            on_click=on_zip_click,
            get_icon=make_zip_icon,
        )
    )
```

### Unregister

Use the extension and the secret from `register(...)`:

```python
FilesController.unregister("zip", secret)
```

### Exceptions

- `FilesController.ExtensionAlreadyRegistered`
- `FilesController.ExtensionNotRegistered`
- `FilesController.SecretInvalid`

```python
try:
    FilesController.register(FilesController.FileInfo(ext="zip", on_click=lambda args: None))
    FilesController.register(FilesController.FileInfo(ext="zip", on_click=lambda args: None))
except FilesController.ExtensionAlreadyRegistered as error:
    print(error)
```
