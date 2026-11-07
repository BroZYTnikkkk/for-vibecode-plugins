# SPDX-License-Identifier: LGPL-3.0-only
# Mornye Player for exteraGram. Copyright 2026 BroNik (@BroZYTnikkkk).
# Based on Mornye by zarzet (https://github.com/mornyeapp/Mornye), LGPL-3.0-only.

"""Signed sessions (port of Mornye extensions/src/signed_session)."""

import email.utils
import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from urllib.parse import urljoin, urlsplit
from .ext_runtime import (
    CallContext,
    ExtError,
    _b64url,
    _ci,
    _go_query_parse,
    _parse_rfc3339_ns,
    _with_query,
)


# -- signed sessions (port of extensions/src/signed_session) --------------------


class _Scope:
    def __init__(self):
        self.lock = threading.RLock()
        self.clear_generation = 0
        self.completed_grant = ""
        self.blocked_generation = ""
        self.challenge = None


class SignedSessions:
    def __init__(self, root):
        self.root = os.path.join(root, "signed_sessions")
        self.scopes = {}
        self.lock = threading.Lock()
        self.grants = {}
        self.pending = {}
        self.verification_urls = {}

    def client(self, manifest, api):
        config = SignedSessionClient.defaults(manifest.signed_session or {})
        name = SignedSessionClient.filename(config)
        with self.lock:
            scope = self.scopes.setdefault(name, _Scope())
        return SignedSessionClient(self, manifest, api, config, os.path.join(self.root, name), scope)

    def register_pending(self, ext, auth_url, callback, state):
        self.pending[ext] = {"auth_url": auth_url, "callback": callback, "state": state, "created": time.time()}

    def pending_fresh(self, ext):
        pending = self.pending.get(ext)
        return bool(pending) and time.time() - pending["created"] < 180

    def take_verification_url(self, ext):
        return self.verification_urls.pop(ext, "")

    def set_grant(self, ext, grant):
        if ext.strip() and grant.strip():
            self.grants[ext.strip()] = grant.strip()


class SignedSessionClient:
    def __init__(self, registry, manifest, api, config, path, scope):
        self.registry = registry
        self.manifest = manifest
        self.api = api
        self.config = config
        self.path = path
        self.scope = scope
        self.id = manifest.name

    @staticmethod
    def defaults(raw):
        endpoints = _ci(raw, "endpoints", {}) or {}
        config = {
            "namespace": str(_ci(raw, "namespace", "")), "base_url": str(_ci(raw, "baseUrl", "")),
            "app_version": str(_ci(raw, "appVersion", "")) or "ext-1.0",
            "platform": str(_ci(raw, "platform", "")) or "extension",
            "callback_url": str(_ci(raw, "callbackUrl", "")) or "mornye://session-grant",
            "scheme_label": str(_ci(raw, "schemeLabel", "")) or "SPOTIFLAC-HMAC-V1",
            "header_prefix": str(_ci(raw, "headerPrefix", "")) or "X-Sig-",
            "time_window": int(_ci(raw, "timeWindowSeconds", 0) or 0) or 300,
            "bootstrap": str(_ci(endpoints, "bootstrap", "")) or "/bootstrap",
            "challenge": str(_ci(endpoints, "challenge", "")) or "/challenge",
            "exchange": str(_ci(endpoints, "exchange", "")) or "/session/exchange",
            "refresh": str(_ci(endpoints, "refresh", "")),
        }
        return config

    @staticmethod
    def namespace(value):
        value = "".join(ch for ch in value.strip().lower() if ch.isascii() and (ch.isalnum() or ch in ".-_"))
        return value.strip(".-_")

    @classmethod
    def filename(cls, config):
        ns = cls.namespace(config["namespace"])
        if not ns:
            raise ExtError("signed session namespace is empty")
        scope = "\n".join([ns, config["base_url"].strip().lower(), config["app_version"].strip().lower(),
                           config["platform"].strip().lower()])
        return "%s-%s.json" % (ns, hashlib.sha256(scope.encode("utf-8")).hexdigest()[:16])

    # -- record store

    def load(self):
        record = {}
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            record = {k.lower(): v for k, v in data.items() if isinstance(v, str)} if isinstance(data, dict) else {}
        except FileNotFoundError:
            pass
        except Exception as e:
            raise ExtError("invalid signed session record: %s" % e)
        changed = False
        if not record.get("install_id", "").strip():
            record["install_id"] = secrets.token_hex(16)
            changed = True
        scope = {"namespace": self.namespace(self.config["namespace"]), "base_url": self.config["base_url"].strip(),
                 "app_version": self.config["app_version"].strip(), "platform": self.config["platform"].strip()}
        if any(record.get(k, "") != v for k, v in scope.items()):
            if any(record.get(k) for k in scope):
                self._clear(record)
            record.update(scope)
            changed = True
        if changed:
            self.save(record)
        return record

    def save(self, record):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({k: v for k, v in record.items() if v or k == "install_id"}, f, indent=2)
        os.replace(tmp, self.path)

    @staticmethod
    def _clear(record):
        for key in ("session_id", "session_secret", "expires_at"):
            record[key] = ""

    @staticmethod
    def usable(record):
        expires = _parse_rfc3339_ns(record.get("expires_at", ""))
        return bool(record.get("session_id", "").strip()) and bool(record.get("session_secret", "").strip()) and (
            expires is None or time.time_ns() < expires)

    @staticmethod
    def same(a, b):
        return bool(a.get("session_id")) and a.get("session_id") == b.get("session_id") and a.get("session_secret") == b.get("session_secret")

    @staticmethod
    def generation(record):
        if not record.get("session_id") or not record.get("session_secret"):
            return ""
        return hashlib.sha256(("%s\n%s" % (record["session_id"], record["session_secret"])).encode("utf-8")).hexdigest()

    def blocked(self, record):
        gen = self.generation(record)
        return bool(gen) and self.scope.blocked_generation == gen

    def refresh_due(self, record):
        expires = _parse_rfc3339_ns(record.get("expires_at", ""))
        now = time.time_ns()
        return bool(self.config["refresh"]) and self.usable(record) and expires is not None and now < expires and expires - now <= 3_600_000_000_000

    # -- protocol

    def endpoint(self, path):
        base = self.config["base_url"].rstrip("/") + "/"
        if not base.startswith("https://"):
            raise ExtError("invalid signed session baseUrl")
        path = path.strip()
        if not path:
            raise ExtError("signed session endpoint is empty")
        if path.startswith("https://"):
            return path
        return urljoin(base, path.lstrip("/"))

    def request(self, method, url, body="", headers=None, ctx=None):
        headers = {k.lower(): v for k, v in (headers or {}).items()}
        headers.setdefault("accept", "application/json")
        headers.setdefault("user-agent", "Mornye/%s" % self.config["app_version"])
        r, final = self.api.open(self.manifest, ctx or CallContext(), method, url, body.encode("utf-8") if body else None, headers)
        try:
            content = self.api._read_all(ctx or CallContext(), r, 8 << 20)
        finally:
            r.close()
        return r.status_code, dict(r.headers), content, final

    def signed_headers(self, record, method, url, body):
        now = time.time_ns()
        seconds = now // 1_000_000_000
        stamp = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(seconds)) + ".%03dZ" % ((now // 1_000_000) % 1000)
        digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
        window = seconds // self.config["time_window"]
        rolling = _b64url(hmac.new(record["session_secret"].encode("utf-8"),
                                   ("%d:%s" % (window, record["session_id"])).encode("utf-8"), hashlib.sha256).digest())
        nonce = secrets.token_hex(12)
        signing = "\n".join([self.config["scheme_label"], method, urlsplit(url).path, "", digest, stamp, nonce,
                             record["session_id"], self.config["app_version"], self.config["platform"]])
        signature = _b64url(hmac.new(rolling.encode("ascii"), signing.encode("utf-8"), hashlib.sha256).digest())
        prefix = self.config["header_prefix"]
        return {(prefix + k).lower(): v for k, v in (
            ("Session", record["session_id"]), ("Timestamp", stamp), ("Nonce", nonce), ("Body-SHA256", digest),
            ("Signature", signature), ("App-Version", self.config["app_version"]), ("Platform", self.config["platform"]))}

    def signed_request(self, record, method, path, body, extras, ctx):
        url = self.endpoint(path)
        headers = self.signed_headers(record, method, url, body)
        if body:
            headers["content-type"] = "application/json"
        for k, v in (extras or {}).items():
            headers[str(k).lower()] = str(v)
        return self.request(method, url, body, headers, ctx)

    @staticmethod
    def contract(content):
        try:
            data = json.loads(content.decode("utf-8", "replace") or "null")
        except Exception:
            data = None
        data = {k.lower(): v for k, v in data.items()} if isinstance(data, dict) else {}
        text = lambda k: str(data.get(k) or "").strip()
        try:
            retry = max(0, int(data.get("retry_after_seconds") or 0))
        except Exception:
            retry = 0
        return {"error": text("error"), "code": text("code").upper(), "origin": text("origin").lower(),
                "action": text("action").lower(), "retryable": data.get("retryable") is True,
                "retry_mode": text("retry_mode").lower(), "retry_after_seconds": retry}

    @staticmethod
    def _retry_after(headers):
        value = str(headers.get("Retry-After") or "").strip()
        if value.isdigit():
            return int(value)
        try:
            return max(0, int(email.utils.parsedate_to_datetime(value).timestamp() - time.time()))
        except Exception:
            return 0

    def response_value(self, status, headers, content, final):
        contract = self.contract(content)
        retry = self._retry_after(headers)
        value = {"statusCode": status, "status": status, "ok": 200 <= status < 300, "url": final,
                 "body": content.decode("utf-8", "replace"), "headers": headers,
                 "retryAfterSeconds": retry if retry > 0 else contract["retry_after_seconds"]}
        if contract["code"] or contract["origin"] or contract["action"]:
            value.update({"error": contract["error"], "code": contract["code"], "origin": contract["origin"],
                          "action": contract["action"], "retryable": contract["retryable"], "retryMode": contract["retry_mode"]})
        return value

    def verification_required(self, url):
        if url:
            self.registry.verification_urls[self.id] = url
        return {"ok": False, "needsVerification": True, "error": "VERIFY_REQUIRED", "open_auth_url": url, "auth_url": url}

    # -- operations

    def status(self):
        with self.scope.lock:
            record = self.load()
            blocked = self.blocked(record)
            return {"authenticated": self.usable(record) and not blocked, "verification_required": blocked,
                    "expires_at": record.get("expires_at", ""), "install_id": record.get("install_id", ""),
                    "session_id": record.get("session_id", ""), "app_version": self.config["app_version"],
                    "platform": self.config["platform"]}

    def clear(self):
        with self.scope.lock:
            record = self.load()
            self._clear(record)
            self.save(record)
            self.scope.clear_generation += 1
            self.scope.completed_grant = ""
            self.scope.blocked_generation = ""
            self.scope.challenge = None
            self.registry.pending.pop(self.id, None)

    def preflight(self, ctx):
        with self.scope.lock:
            record = self.load()
            if self.usable(record) and not self.blocked(record):
                return False
        url = self.bootstrap(ctx)
        if url:
            return True
        with self.scope.lock:
            if self.usable(self.load()):
                return False
        raise ExtError("signed-session bootstrap did not return a session or verification challenge")

    def bootstrap(self, ctx):
        with self.scope.lock:
            challenge = self.scope.challenge
            if challenge and challenge["auth_url"].strip() and time.time() - challenge["created"] < 180:
                self.registry.register_pending(self.id, challenge["auth_url"], challenge["callback"], challenge["state"])
                return challenge["auth_url"]
            self.scope.challenge = None
            pending = self.registry.pending.get(self.id)
            if pending and pending["auth_url"].strip() and time.time() - pending["created"] < 180:
                self.scope.challenge = dict(pending)
                return pending["auth_url"]
            record = self.load()
            if self.usable(record) and not self.blocked(record):
                return ""
            url = _with_query(self.endpoint(self.config["bootstrap"]),
                              [("app_version", self.config["app_version"]), ("install_id", record["install_id"])])
            try:
                status, headers, content, _ = self.request("GET", url, "", {}, ctx)
            except Exception:
                status, headers, content, _ = self.request("GET", url, "", {}, ctx)
            if not 200 <= status < 300:
                retry = self._retry_after(headers)
                raise ExtError("signed-session bootstrap %sreturned HTTP %d%s" % (
                    "network request " if status >= 500 else "", status, "; retry-after seconds: %d" % retry if retry else ""))
            data = json.loads(content.decode("utf-8") or "{}")
            data = {k.lower(): v for k, v in data.items()} if isinstance(data, dict) else {}
            if data.get("session_id") and data.get("session_secret") and data.get("expires_at"):
                for key in ("session_id", "session_secret", "expires_at"):
                    record[key] = str(data[key])
                self.save(record)
                self.scope.blocked_generation = ""
                self.scope.challenge = None
                self.registry.pending.pop(self.id, None)
                return ""
            auth_url = str(data.get("auth_url") or data.get("challenge_url") or "")
            state = _b64url(os.urandom(32))
            if auth_url:
                server_state = (_go_query_parse(urlsplit(auth_url).query).get("state") or [""])[0].strip()
                if server_state:
                    state = server_state
                else:
                    auth_url = _with_query(auth_url, [("state", state)])
            callback = _with_query(self.config["callback_url"], [("state", state)])
            if not auth_url and data.get("challenge_id"):
                cb = _with_query(self.config["callback_url"], [("cb_version", "v2grant"), ("state", state)])
                auth_url = _with_query(self.endpoint(self.config["challenge"]), [("id", str(data["challenge_id"])), ("cb", cb)])
            if not auth_url:
                raise ExtError("signed-session bootstrap did not return a session or verification challenge")
            self.scope.challenge = {"auth_url": auth_url, "callback": callback, "state": state, "created": time.time()}
            self.registry.register_pending(self.id, auth_url, callback, state)
            return auth_url

    def complete_grant(self, grant, ctx):
        self.registry.set_grant(self.id, grant)
        grant = self.registry.grants.get(self.id, "")
        if not grant:
            raise ExtError("no pending grant")
        grant_hash = hashlib.sha256(grant.encode("utf-8")).hexdigest()
        with self.scope.lock:
            record = self.load()
            if self.scope.completed_grant == grant_hash and self.usable(record):
                self.scope.blocked_generation = ""
                self.scope.challenge = None
                return
            body = json.dumps({"grant": grant, "install_id": record["install_id"], "app_version": self.config["app_version"],
                               "platform": self.config["platform"]})
            url = self.endpoint(self.config["exchange"])
            data = None
            for attempt in range(3):
                status, headers, content, _ = self.request("POST", url, body, {"content-type": "application/json"}, ctx)
                retry = self._retry_after(headers)
                if status == 429 and attempt < 2:
                    time.sleep(max(1, min(retry or 1, 30)))
                    continue
                if not 200 <= status < 300:
                    raise ExtError("session exchange failed: HTTP %d%s" % (status, "; retry-after seconds: %d" % retry if retry else ""))
                data = json.loads(content.decode("utf-8") or "{}")
                data = {k.lower(): v for k, v in data.items()} if isinstance(data, dict) else {}
                break
            if not data or not (data.get("session_id") and data.get("session_secret") and data.get("expires_at")):
                raise ExtError("session exchange response missing session fields")
            for key in ("session_id", "session_secret", "expires_at"):
                record[key] = str(data[key])
            self.save(record)
            self.scope.completed_grant = grant_hash
            self.scope.blocked_generation = ""
            self.scope.challenge = None
        if self.registry.grants.get(self.id) == grant:
            self.registry.grants.pop(self.id, None)
        self.registry.pending.pop(self.id, None)

    def refresh(self, ctx):
        with self.scope.lock:
            record = self.load()
            if not self.refresh_due(record):
                return
            status, _, content, _ = self.signed_request(record, "POST", self.config["refresh"],
                                                        json.dumps({"install_id": record["install_id"]}), {}, ctx)
            if not 200 <= status < 300:
                raise ExtError("session refresh failed: HTTP %d" % status)
            data = json.loads(content.decode("utf-8") or "{}")
            data = {k.lower(): v for k, v in data.items()} if isinstance(data, dict) else {}
            changed = False
            for key in ("session_id", "session_secret", "expires_at"):
                if data.get(key) and record.get(key) != data[key]:
                    record[key] = str(data[key])
                    changed = True
            if changed:
                self.save(record)

    def signed_fetch(self, method, path, body, headers, ctx):
        method = method.strip().upper()
        with self.scope.lock:
            record = self.load()
            error = None
            if not record.get("session_id") or not record.get("session_secret"):
                error = "signed session is not authenticated"
            else:
                expires = _parse_rfc3339_ns(record.get("expires_at", ""))
                if expires is not None and time.time_ns() > expires:
                    self._clear(record)
                    self.save(record)
                    error = "signed session expired"
            blocked = error is None and self.blocked(record)
        if error or blocked:
            try:
                url = self.bootstrap(ctx)
            except Exception:
                return self.verification_required("")
            if url:
                return self.verification_required(url)
            if error:
                raise ExtError(error)
            with self.scope.lock:
                record = self.load()
                if not self.usable(record) or self.blocked(record):
                    return self.verification_required("")
        if self.refresh_due(record):
            try:
                self.refresh(ctx)
            except Exception:
                pass
            with self.scope.lock:
                latest = self.load()
            if not self.usable(latest) or self.blocked(latest):
                url = self.bootstrap(ctx)
                if url:
                    return self.verification_required(url)
                raise ExtError("signed session is not authenticated")
            record = latest
        session_retries = provider_retries = 0
        auth_retry = False
        while True:
            status, resp_headers, content, final = self.signed_request(record, method, path, body, headers, ctx)
            contract = self.contract(content)
            if (status == 503 and contract["origin"] == "provider" and contract["code"] == "PROVIDER_UNAVAILABLE"
                    and contract["retryable"] and contract["retry_mode"] == "same_operation"):
                if provider_retries >= 2:
                    return self.response_value(status, resp_headers, content, final)
                provider_retries += 1
                delay = self._retry_after(resp_headers) or contract["retry_after_seconds"] or 1
                time.sleep(min(delay, 120))
                continue
            if status == 403 and contract["origin"] == "gateway" and contract["code"] == "REQUEST_AUTH_INVALID" and not contract["action"]:
                with self.scope.lock:
                    latest = self.load()
                if not auth_retry and self.usable(latest) and not self.same(latest, record):
                    auth_retry = True
                    record = latest
                    continue
                return self.response_value(status, resp_headers, content, final)
            action = ""
            if status == 401 and contract["origin"] == "gateway" and contract["code"] == "SESSION_INVALID" and contract["action"] == "bootstrap_session":
                action = "bootstrap_session"
            elif status == 428 and contract["origin"] == "gateway" and contract["code"] == "VERIFY_REQUIRED" and contract["action"] == "verify":
                action = "verify"
            if not action:
                return self.response_value(status, resp_headers, content, final)
            with self.scope.lock:
                latest = self.load()
                if self.usable(latest) and not self.same(latest, record):
                    if session_retries >= 1:
                        raise ExtError("signed-session retry limit reached")
                    session_retries += 1
                    record = latest
                    continue
                if action == "bootstrap_session" and self.same(latest, record):
                    self.scope.blocked_generation = ""
                    self._clear(latest)
                    self.save(latest)
                elif action == "verify" and self.same(latest, record):
                    self.scope.blocked_generation = self.generation(record)
            url = self.bootstrap(ctx)
            if url:
                return self.verification_required(url)
            with self.scope.lock:
                fresh = self.load()
            if self.usable(fresh) and not self.same(fresh, record) and session_retries < 1:
                session_retries += 1
                record = fresh
                continue
            return self.response_value(status, resp_headers, content, final)
