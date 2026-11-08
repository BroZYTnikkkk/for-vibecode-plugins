# SPDX-License-Identifier: LGPL-3.0-only
# Sculpt Player for exteraGram. Copyright 2026 BroNik (@BroZYTnikkkk).
# Speaks Mornye Link, the protocol of Mornye by zarzet (https://github.com/mornyeapp/Mornye), LGPL-3.0-only.

"""Mornye Link, the phone's side, without any Android in it: a computer running Mornye is the server.

It serves HTTPS with a self-signed certificate, so the certificate's SHA-256 is what is trusted: the phone reads it
from the connection itself, proves with the PIN that it saw the same one, and accepts no other from then on.
"""

import base64
import hashlib
import hmac
import json
import os
import random
import re
import socket
import ssl
import string
import struct
import threading
import time
import urllib.parse

import requests
from requests.adapters import HTTPAdapter

PORT = 47710
SERVICE_TYPE = "_mornye._tcp"
PAIR_CONTEXT = "mornye-link-pair-v1:"
TIMEOUT = 6
UNREACHABLE = "Компьютер не отвечает. Проверь, что Mornye на нём открыт и он в той же сети, что и телефон."
CHANGED = "Сертификат компьютера изменился. Забудь компьютер и подключись заново."


class LinkError(Exception):
    """Something to show as it is."""


class Forgotten(LinkError):
    """The computer no longer knows this phone's key."""


class Pinned(HTTPAdapter):
    """Accepts only the certificate with this fingerprint, whatever name it carries."""

    def __init__(self, fingerprint):
        self.fingerprint = fingerprint
        super().__init__()

    def init_poolmanager(self, connections, maxsize, block=False, **kwargs):
        kwargs.update(assert_fingerprint=self.fingerprint, assert_hostname=False, cert_reqs="CERT_NONE")
        super().init_poolmanager(connections, maxsize, block, **kwargs)


def parse_address(text):
    """(host, port) from "192.168.0.10" or "192.168.0.10:47710"."""
    found = re.fullmatch(r"([^\s:/]+)(?::(\d{1,5}))?", (text or "").strip())
    port = int(found.group(2) or PORT) if found else 0
    if not found or not 0 < port < 65536:
        raise LinkError("Адрес пишется так: 192.168.0.10 или 192.168.0.10:47710.")
    return found.group(1), port


def observed_fingerprint(host, port, timeout=TIMEOUT):
    """The SHA-256 of the certificate this connection really presents, in lowercase hex."""
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    try:
        with socket.create_connection((host, port), timeout=timeout) as raw:
            with context.wrap_socket(raw) as tls:
                return hashlib.sha256(tls.getpeercert(binary_form=True)).hexdigest()
    except (OSError, ssl.SSLError) as e:
        raise LinkError(UNREACHABLE) from e


def _session(fingerprint):
    session = requests.Session()
    session.verify = False  # the fingerprint below is the check
    session.mount("https://", Pinned(fingerprint))
    return session


def _request(fingerprint, method, url, timeout=TIMEOUT, **kwargs):
    """No URL in anything raised from here: a Subsonic one carries the key's token."""
    try:
        with _session(fingerprint) as session:
            return session.request(method, url, timeout=timeout, **kwargs)
    except requests.exceptions.SSLError:
        problem = CHANGED
    except requests.exceptions.RequestException:
        problem = UNREACHABLE
    raise LinkError(problem) from None


def probe(host, port, timeout=TIMEOUT):
    """What a computer says about itself, once its certificate has been read from the connection."""
    fingerprint = observed_fingerprint(host, port, timeout)
    answer = _request(fingerprint, "GET", "https://%s:%d/mornye/v1/info" % (host, port), timeout)
    try:
        info = answer.json()
        said = str(info["fingerprint"]).lower()
        server_id = str(info["serverId"])
    except (ValueError, KeyError, TypeError):
        raise LinkError("По этому адресу отвечает не Mornye.") from None
    if said != fingerprint:
        raise LinkError("Компьютер назвал не тот сертификат, который показал. Подключаться к нему небезопасно.")
    return {"host": host, "port": port, "name": str(info.get("name") or host), "serverId": server_id,
            "fingerprint": fingerprint, "pairing": bool(info.get("pairing"))}


def proof(pin, fingerprint, device_id):
    message = "%s%s:%s" % (PAIR_CONTEXT, fingerprint.lower(), device_id)
    return hmac.new(pin.encode(), message.encode(), hashlib.sha256).hexdigest()


def pair(server, pin, device_id, name):
    """The saved form of a computer after the PIN was accepted, with this phone's key in it."""
    fingerprint = server["fingerprint"]
    body = {"deviceId": device_id, "name": name, "platform": "android", "proof": proof(pin, fingerprint, device_id)}
    answer = _request(fingerprint, "POST", "https://%s:%d/mornye/v1/pair" % (server["host"], server["port"]), json=body)
    try:
        data = answer.json()
    except ValueError:
        data = {}
    if answer.status_code == 200 and data.get("apiKey"):
        return {"host": server["host"], "port": server["port"], "name": str(data.get("name") or server["name"]),
                "serverId": str(data.get("serverId") or server["serverId"]), "fingerprint": fingerprint,
                "apiKey": str(data["apiKey"])}
    error = data.get("error")
    if error == "bad_proof":
        raise LinkError("Код не подходит. Проверь цифры на экране компьютера.")
    if error == "pairing_closed":
        raise LinkError("На компьютере не открыто окно подключения или код устарел. Нажми там «Pair a phone» ещё раз.")
    if error == "rate_limited":
        raise LinkError("Слишком часто. Подожди несколько секунд и попробуй снова.")
    raise LinkError("Компьютер не принял подключение. Попробуй ещё раз.")


def subsonic_auth(api_key):
    """The key as a salted token, so that it never travels in a URL itself."""
    salt = "".join(random.choices(string.ascii_lowercase + string.digits, k=12))
    return {"u": "sculpt", "t": hashlib.md5((api_key + salt).encode()).hexdigest(), "s": salt, "v": "1.16.1",
            "c": "SculptPlayer", "f": "json"}


def ping(saved):
    """True when the computer answers and still knows this phone; a LinkError says why not otherwise."""
    url = "https://%s:%d/rest/ping.view" % (saved["host"], saved["port"])
    answer = _request(saved["fingerprint"], "GET", url, params=subsonic_auth(saved["apiKey"]))
    try:
        body = answer.json()["subsonic-response"]
    except (ValueError, KeyError, TypeError):
        raise LinkError("Компьютер ответил непонятно. Попробуй ещё раз.") from None
    if body.get("status") == "ok":
        return True
    if (body.get("error") or {}).get("code") in (40, 44):
        raise Forgotten("Компьютер больше не знает этот телефон. Забудь его и подключись заново.")
    raise LinkError("Компьютер не ответил на проверку. Попробуй ещё раз.")


def stream_query(api_key):
    """The credentials of a stream address, as a query string."""
    auth = subsonic_auth(api_key)
    auth.pop("f")
    return urllib.parse.urlencode(auth)


def songs(saved, offset=0, count=500):
    """One page of the computer's songs; Subsonic has no list of them, and an empty search returns them all."""
    url = "https://%s:%d/rest/search3.view" % (saved["host"], saved["port"])
    params = dict(subsonic_auth(saved["apiKey"]), query="", artistCount=0, albumCount=0, songCount=count, songOffset=offset)
    answer = _request(saved["fingerprint"], "GET", url, timeout=20, params=params)
    try:
        body = answer.json()["subsonic-response"]
    except (ValueError, KeyError, TypeError):
        raise LinkError("Компьютер ответил непонятно. Попробуй ещё раз.") from None
    if body.get("status") != "ok":
        raise LinkError("Компьютер не отдал список песен. Попробуй ещё раз.")
    return (body.get("searchResult3") or {}).get("song") or []


# -- the phone's songs on the computer ------------------------------------------------------------------------------


def _api(saved, op):
    return "https://%s:%d/mornye/v1/%s" % (saved["host"], saved["port"], op)


def _bearer(saved):
    return {"Authorization": "Bearer %s" % saved["apiKey"]}


def _answer(response):
    try:
        data = response.json()
    except ValueError:
        data = None
    if response.status_code == 401:
        raise Forgotten("Компьютер больше не знает этот телефон. Забудь его и подключись заново.")
    if response.status_code >= 400:
        code = data.get("error") if isinstance(data, dict) else None
        raise LinkError("Компьютер отказал: %s." % (code or response.status_code))
    return data


def api_get(saved, op):
    return _answer(_request(saved["fingerprint"], "GET", _api(saved, op), timeout=20, headers=_bearer(saved)))


def api_post(saved, op, body):
    return _answer(_request(saved["fingerprint"], "POST", _api(saved, op), timeout=60, headers=_bearer(saved), json=body))


def upload(saved, name, path):
    """A song to the computer: it starts playing while the file is still arriving."""
    headers = dict(_bearer(saved))
    headers["Content-Type"] = "application/octet-stream"
    with open(path, "rb") as body:
        return _answer(_request(saved["fingerprint"], "PUT", _api(saved, "files/%s" % name), timeout=(8, 120), headers=headers, data=body))


class Socket:
    """The WebSocket to the computer, over a connection whose certificate was checked before the key is sent."""

    MAGIC = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
    IDLE = 20  # the computer closes a silent connection after 60 s
    POLL = 0.5  # how long the reader holds the connection before letting a writer in
    LIMIT = 16 * 1024 * 1024

    def __init__(self, saved, timeout=TIMEOUT):
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        self.lock = threading.Lock()  # one TLS connection cannot be read and written at the same moment
        self.heard = time.monotonic()
        self.buffer = bytearray()
        self.parts = bytearray()
        self.tls = None
        try:
            raw = socket.create_connection((saved["host"], saved["port"]), timeout=timeout)
            self.tls = context.wrap_socket(raw)
            seen = hashlib.sha256(self.tls.getpeercert(binary_form=True)).hexdigest()
            if seen != saved["fingerprint"].lower():
                raise LinkError(CHANGED)
            self._upgrade(saved)
            self.tls.settimeout(self.POLL)
        except (OSError, ssl.SSLError) as e:
            self.close()
            raise LinkError(UNREACHABLE) from e
        except LinkError:
            self.close()
            raise

    def _upgrade(self, saved):
        key = base64.b64encode(os.urandom(16)).decode()
        request = ("GET /mornye/v1/ws HTTP/1.1\r\nHost: %s:%d\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                   "Sec-WebSocket-Key: %s\r\nSec-WebSocket-Version: 13\r\nAuthorization: Bearer %s\r\n\r\n"
                   % (saved["host"], saved["port"], key, saved["apiKey"]))
        self.tls.sendall(request.encode())
        while b"\r\n\r\n" not in self.buffer:
            chunk = self.tls.recv(4096)
            if not chunk or len(self.buffer) > 65536:
                raise LinkError(UNREACHABLE)
            self.buffer += chunk
        head, _, rest = bytes(self.buffer).partition(b"\r\n\r\n")
        self.buffer = bytearray(rest)
        lines = head.decode("latin-1").split("\r\n")
        status = lines[0].split(" ")
        if len(status) > 1 and status[1] == "401":
            raise Forgotten("Компьютер больше не знает этот телефон. Забудь его и подключись заново.")
        headers = {k.strip().lower(): v.strip() for k, _, v in (line.partition(":") for line in lines[1:])}
        accept = base64.b64encode(hashlib.sha1((key + self.MAGIC).encode()).digest()).decode()
        if len(status) < 2 or status[1] != "101" or headers.get("sec-websocket-accept") != accept:
            raise LinkError(UNREACHABLE)

    def _send(self, opcode, payload):
        length = len(payload)
        head = bytearray([0x80 | opcode])
        if length < 126:
            head.append(0x80 | length)
        elif length < 65536:
            head.append(0x80 | 126)
            head += struct.pack(">H", length)
        else:
            head.append(0x80 | 127)
            head += struct.pack(">Q", length)
        mask = os.urandom(4)
        head += mask
        masked = bytes(b ^ mask[i & 3] for i, b in enumerate(payload))
        with self.lock:
            self.tls.settimeout(TIMEOUT)
            try:
                self.tls.sendall(bytes(head) + masked)
            finally:
                self.tls.settimeout(self.POLL)

    def send(self, message):
        self._send(1, json.dumps(message, ensure_ascii=False).encode())

    def _frame(self):
        """One whole frame from the buffer, or None until more arrives."""
        data = self.buffer
        if len(data) < 2:
            return None
        size, at = data[1] & 127, 2
        if size == 126:
            if len(data) < 4:
                return None
            size, at = struct.unpack(">H", data[2:4])[0], 4
        elif size == 127:
            if len(data) < 10:
                return None
            size, at = struct.unpack(">Q", data[2:10])[0], 10
        if size > self.LIMIT:
            raise LinkError(UNREACHABLE)
        if len(data) < at + size:
            return None
        frame = (data[0] & 0x80 != 0, data[0] & 15, bytes(data[at:at + size]))
        del data[:at + size]
        return frame

    def receive(self):
        """The next message as a dict; None when the connection has ended."""
        try:
            while True:
                frame = self._frame()
                if frame is None:
                    try:
                        with self.lock:
                            chunk = self.tls.recv(65536)
                    except socket.timeout:
                        if time.monotonic() - self.heard > self.IDLE:
                            self.heard = time.monotonic()
                            self._send(9, b"")  # silence: a ping keeps the computer from closing
                        continue
                    except ssl.SSLWantReadError:
                        continue
                    self.heard = time.monotonic()
                    if not chunk:
                        return None
                    self.buffer += chunk
                    continue
                final, opcode, payload = frame
                if opcode == 8:
                    return None
                if opcode == 9:
                    self._send(10, payload)
                elif opcode in (0, 1):
                    self.parts += payload
                    if final:
                        text, self.parts = bytes(self.parts), bytearray()
                        try:
                            message = json.loads(text.decode())
                        except ValueError:
                            continue
                        if isinstance(message, dict):
                            return message
        except (OSError, ssl.SSLError):
            return None

    def close(self):
        if self.tls is not None:
            try:
                self.tls.close()
            except OSError:
                pass
