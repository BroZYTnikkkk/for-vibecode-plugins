# Multi-Account Scoping

exteraGram keeps every logged-in account connected at the same time. Accounts that are not on screen still receive updates, still send requests, and **still fire your hooks**.

The account helpers in `client_utils` default to the account selected in the UI — that's global state unrelated to the account your callback was invoked for. Reply from inside a hook without thinking about it and the message can go out from the wrong account.

## The Rule

Every hook already tells you which account it is for — use that account for anything you do in response:

```python
def on_update_hook(self, update_name, account, update) -> HookResult:
    ...
```

## Targeting an Account

Every account-scoped helper takes an optional `account=`:

```python
from client_utils import get_messages_controller, get_user_config, send_text

get_messages_controller(account)
get_user_config(account)
send_text(peer, "hello", account=account)
```

When you do more than one thing, take a client instead of repeating yourself. `self.client(...)` returns an `AccountClient` with the same method names, bound to one account:

```python
from base_plugin import BasePlugin, HookResult

class ReplyPlugin(BasePlugin):
    def on_plugin_load(self):
        self.add_hook("TL_updateNewMessage")

    def on_update_hook(self, update_name, account, update) -> HookResult:
        if update_name != "TL_updateNewMessage":
            return HookResult()

        client = self.client(account)
        me = client.get_user_config().getCurrentUser()
        client.send_text(update.message.dialog_id, f"replying as {me.first_name}")
        return HookResult()
```

Outside a plugin class, use `get_client(account)` from `client_utils`.

## What Happens If You Forget

Nothing changes silently. A helper called without an account still uses the selected account — but if it runs while handling a different account, the SDK logs a warning **once per helper**:

```
get_messages_controller() is using account 0 because it is the one selected in the UI,
but it was called while handling account 1. Pass account=1, or use get_client(1),
if you meant that account. Logged once per helper.
```

Seeing that log means the plugin is reading or writing the wrong account.

## Scope Follows Your Work

The scope is set around every hook callback, around `run_on_queue` work scheduled from one, and around `send_request` callbacks.

- `get_hook_account()` returns it, or `None` outside a callback.
- `self.client()` with no argument follows it.

## Deliberately Using the Selected Account

Sometimes the selected account is genuinely what you want (e.g. writing to Saved Messages of whoever is looking at the screen). Say so explicitly and the warning goes away:

```python
from client_utils import get_selected_account, send_text

send_text(peer, "note to self", account=get_selected_account())
```

## Notification Delegates

`NotificationCenterDelegate.didReceivedNotification` receives `account` and it is **not** scoped automatically. Take a client from it:

```python
class MyDelegate(NotificationCenterDelegate):
    def didReceivedNotification(self, id: int, account: int, args):
        get_client(account).get_messages_controller()
```

## Requirements

`account=` parameters, `AccountClient`, `get_client()`, `get_hook_account()`, and `get_selected_account()` need **SDK 1.4.5.0** or newer. Declare it so older installs fail with a clear message:

```python
__sdk_version__ = ">=1.4.5.0"
```
