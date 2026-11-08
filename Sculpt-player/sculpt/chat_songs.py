# Sculpt Player for exteraGram. Copyright 2026 BroNik (@BroZYTnikkkk).

"""Songs that are Telegram messages, kept across restarts as references: enough to show them at once and to ask
Telegram for the messages again when they are needed. A deleted message simply does not come back."""

import threading

from android_utils import run_on_ui_thread
from java import dynamic_proxy, jclass
from java.lang import Integer as JInteger

from .common import _log

TLRPC = "org.telegram.tgnet.TLRPC$"
BATCH = 100  # message ids in one request


class Reply(dynamic_proxy(jclass("org.telegram.tgnet.RequestDelegate"))):
    def __init__(self, action):
        super().__init__()
        self.action = action

    def run(self, response, error):
        self.action(response, error)


def ref_of(message):
    """What is kept of a song from a chat."""
    title, author = message.getMusicTitle(), message.getMusicAuthor()
    account = int(message.currentAccount)
    ref = {"account": account, "dialog": int(message.getDialogId()), "id": int(message.getId()), "title": str(title) if title else "",
           "artist": str(author) if author else "", "duration": int(float(message.getDuration() or 0)), "channel": 0, "hash": 0}
    peer = message.messageOwner.peer_id
    channel = int(peer.channel_id) if peer is not None else 0
    if channel:
        chat = jclass("org.telegram.messenger.MessagesController").getInstance(account).getChat(jclass("java.lang.Long")(channel))
        ref["channel"] = channel
        ref["hash"] = int(chat.access_hash) if chat is not None else 0
    return ref


def key_of(ref):
    return ref["dialog"], ref["id"]


def _request(batch):
    if batch[0]["channel"]:
        request = jclass(TLRPC + "TL_channels_getMessages")()
        channel = jclass(TLRPC + "TL_inputChannel")()
        channel.channel_id = batch[0]["channel"]
        channel.access_hash = batch[0]["hash"]
        request.channel = channel
    else:
        request = jclass(TLRPC + "TL_messages_getMessages")()
    for ref in batch:
        request.id.add(JInteger(ref["id"]))
    return request


def load(refs, done):
    """done({(dialog, id): MessageObject}) on the UI thread, once every part has answered."""
    groups = {}
    for ref in refs:
        groups.setdefault((ref["account"], ref["channel"]), []).append(ref)
    batches = [(account, chunk[i:i + BATCH]) for (account, _), chunk in groups.items() for i in range(0, len(chunk), BATCH)]
    if not batches:
        run_on_ui_thread(lambda: done({}))
        return
    lock = threading.Lock()
    found = {}
    left = [len(batches)]

    def part_done():
        with lock:
            left[0] -= 1
            finished = left[0] == 0
        if finished:
            run_on_ui_thread(lambda: done(found))

    def send(account, batch):
        by_id = {ref["id"]: ref for ref in batch}

        def answered(response, error):
            try:
                if response is not None:
                    controller = jclass("org.telegram.messenger.MessagesController").getInstance(account)
                    users, chats = response.users, response.chats
                    run_on_ui_thread(lambda: (controller.putUsers(users, False), controller.putChats(chats, False)))
                    MessageObject = jclass("org.telegram.messenger.MessageObject")
                    messages = response.messages
                    for i in range(messages.size()):
                        message = messages.get(i)
                        ref = by_id.get(int(message.id))
                        if ref is not None and message.media is not None:
                            with lock:
                                found[key_of(ref)] = MessageObject(account, message, False, True)
                elif error is not None:
                    _log("chat songs: %s" % error.text)
            except Exception as e:
                _log("chat songs: %s" % type(e).__name__)
            part_done()

        jclass("org.telegram.tgnet.ConnectionsManager").getInstance(account).sendRequest(_request(batch), Reply(answered))

    for account, batch in batches:
        send(account, batch)
