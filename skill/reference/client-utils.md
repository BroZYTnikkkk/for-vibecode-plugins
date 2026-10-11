# Client Utilities (client_utils)

Source: `from client_utils import run_on_queue, send_request, send_text, send_photo, send_document, send_video, send_audio, send_message, edit_message, get_last_fragment, get_messages_controller, NotificationCenterDelegate, ...`

Higher-level helpers for queues, requests, controllers, fragments, and sending/editing messages and media.

## Queues (Background Threads)

Use `run_on_queue(...)` for work that must not block the UI thread: network, file I/O, heavy parsing, long compute.

```python
import time
from android_utils import log
from client_utils import run_on_queue

def my_long_task(parameter):
    log(f"Task started: {parameter}")
    time.sleep(5)
    log(f"Task finished: {parameter}")

run_on_queue(lambda: my_long_task("some_data"))
```

Target a specific queue with a delay (ms):

```python
from client_utils import GLOBAL_QUEUE, run_on_queue
run_on_queue(lambda: my_long_task("other"), GLOBAL_QUEUE, 2500)
```

### Queue name constants

```python
STAGE_QUEUE         = "stageQueue"
GLOBAL_QUEUE        = "globalQueue"
CACHE_CLEAR_QUEUE   = "cacheClearQueue"
SEARCH_QUEUE        = "searchQueue"
PHONE_BOOK_QUEUE    = "phoneBookQueue"
THEME_QUEUE         = "themeQueue"
EXTERNAL_NETWORK_QUEUE = "externalNetworkQueue"
PLUGINS_QUEUE       = "pluginsQueue"   # default
```

Raw Java `DispatchQueue`:

```python
from client_utils import PLUGINS_QUEUE, get_queue_by_name
q = get_queue_by_name(PLUGINS_QUEUE)
if q:
    pass  # call DispatchQueue methods directly
```

## Sending Telegram API Requests

`send_request(request, fn)` sends a raw `TLObject` through the ConnectionsManager of the **selected account**, or `account=` when passed. Your callback runs with that account in scope.

```python
from java.lang import Integer
from org.telegram.tgnet import TLRPC
from android_utils import log
from client_utils import send_request

def handle_read_contents_response(response, error):
    if error:
        log(f"Error: {error.text}")
        return
    if response and isinstance(response, TLRPC.TL_messages_affectedMessages):
        log(f"Read. PTS: {response.pts}, Count: {response.pts_count}")

req = TLRPC.TL_messages_readMessageContents()
req.id.add(Integer(12345))
request_id = send_request(req, handle_read_contents_response)
log(f"Sent, request ID: {request_id}")
```

You usually do not need `RequestCallback` manually unless you want the proxy class itself.

## Sending Messages and Media

`send_*` helpers build `SendMessageParams`, prepare media, and send on the correct thread. All `send_*` accept optional `parse_mode="HTML"` or `parse_mode="Markdown"` (case-insensitive).

### `send_text`

```python
from client_utils import send_text

peer_id = 123456789
send_text(peer_id, "Hello from my plugin!")
send_text(peer_id, "This is a reply.", replyToMsg=9876)
send_text(peer_id, "**Hello** from my *plugin*!", parse_mode="Markdown")
```

### `send_photo`

```python
from client_utils import send_photo

send_photo(peer_id, "/path/to/image.jpg", caption="Here is a photo!")
send_photo(
    peer_id, "/path/to/image.jpg",
    caption="<b>High quality</b> photo.",
    high_quality=True,
    parse_mode="HTML",
)
```

### `send_document`

```python
from client_utils import send_document
send_document(peer_id, "/path/to/file.zip", caption="Here is the zip.")
```

### `send_video`

```python
from client_utils import send_video
# SDK fills common video attributes (size, duration) when possible.
send_video(peer_id, "/path/to/video.mp4", caption="Check out this video!")
```

### `send_audio`

```python
from client_utils import send_audio
# SDK fills common audio metadata when possible.
send_audio(peer_id, "/path/to/song.mp3", caption="Listen to this!")
```

### Low-level `send_message`

`send_message(params, parse_mode=None)` accepts a dict mapping to `SendMessagesHelper.SendMessageParams`:

```python
from client_utils import send_message

send_message({
    "peer": 123456789,
    "message": "Scheduled message from plugin",
    "scheduleDate": 1735689600,
    "notify": False,
})
```

Common keys: `peer`, `message`, `caption`, `photo`, `document`, `path`, `replyToMsg`, `replyMarkup`, `params`, `notify`, `scheduleDate`, `ttl`, `hasMediaSpoilers`, `sendingHighQuality`.

## Editing Messages

`edit_message(message_obj, ...)` edits an existing `MessageObject`.

```python
from client_utils import edit_message

edit_message(message_obj, text="New edited text.")
edit_message(message_obj, text="This is <b>bold</b>.", parse_mode="HTML")

# Replace media and update text:
edit_message(message_obj, file_path="/path/to/another.jpg", text="New photo.")
edit_message(message_obj, file_path="/path/to/another.jpg", with_spoiler=True)
```

Notes:
- `message_obj` must be a real `org.telegram.messenger.MessageObject`.
- Pass `text=` to replace message/caption text.
- Pass `file_path=` to replace attached media.
- Unsupported `parse_mode` raises `ValueError`.

## Fragments, Controllers, Account Helpers

All helpers return components for the **selected account** unless `account=` is passed. See [multi-account.md](multi-account.md).

```python
from client_utils import (
    get_last_fragment,
    get_account_instance,
    get_messages_controller,
    get_contacts_controller,
    get_media_data_controller,
    get_connections_manager,
    get_location_controller,
    get_notifications_controller,
    get_messages_storage,
    get_send_messages_helper,
    get_file_loader,
    get_secret_chat_helper,
    get_download_controller,
    get_notifications_settings,
    get_notification_center,
    get_media_controller,   # NOTE: global, no account param
    get_user_config,
)

fragment = get_last_fragment()
mc = get_messages_controller()
mc1 = get_messages_controller(1)  # explicit account
user_cfg = get_user_config()
if user_cfg.getCurrentUser():
    current_user = user_cfg.getCurrentUser()
```

`get_media_controller()` is the one exception with no account parameter — `MediaController` is a single global instance.

## NotificationCenterDelegate

Ready-made Python base class for `NotificationCenter.NotificationCenterDelegate`.

```python
from java.lang import Object
from java import jarray
from client_utils import NotificationCenterDelegate, get_notification_center
from org.telegram.messenger import NotificationCenter

class MyDelegate(NotificationCenterDelegate):
    def didReceivedNotification(self, id: int, account: int, args: jarray(Object)):
        if id == NotificationCenter.didUpdateConnectionState:
            print("Connection state changed:", args)

delegate = MyDelegate()
nc = get_notification_center()
nc.addObserver(delegate, NotificationCenter.didUpdateConnectionState)
# Later:
# nc.removeObserver(delegate, NotificationCenter.didUpdateConnectionState)
```

You don't need `dynamic_proxy(...)` yourself — subclassing `NotificationCenterDelegate` is enough. `didReceivedNotification` receives `account` too — take a client from it (see [multi-account.md](multi-account.md)).

## Displaying Bulletins

```python
from ui.bulletin import BulletinHelper
BulletinHelper.show_info("Informational message.")
```

See [ui-helpers.md](ui-helpers.md) for the full bulletin and dialog API.
