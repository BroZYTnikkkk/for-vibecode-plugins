# SPDX-License-Identifier: LGPL-3.0-only
# Sculpt Player for exteraGram. Copyright 2026 BroNik (@BroZYTnikkkk).
# Speaks Mornye Link, the protocol of Mornye by zarzet (https://github.com/mornyeapp/Mornye), LGPL-3.0-only.

"""Mornye Link, the phone's side, without any Android in it: a computer running Mornye is the server.

It serves HTTPS with a self-signed certificate, so the certificate's SHA-256 is what is trusted: the phone reads it
from the connection itself, proves with the PIN that it saw the same one, and accepts no other from then on.
"""

import hashlib
import hmac
import random
import re
import socket
import ssl
import string

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
