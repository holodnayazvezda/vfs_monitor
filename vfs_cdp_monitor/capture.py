from __future__ import annotations

import json
import queue
import threading
import time

import websocket

from .cdp import http_json
from .config import SESSION_FILE


def normalize_headers(headers: dict) -> dict:
    return {str(key).lower(): value for key, value in (headers or {}).items()}


def save_session_headers(login_user: str, authorize: str, client_source: str) -> None:
    existing = {}
    if SESSION_FILE.exists():
        try:
            existing = json.loads(SESSION_FILE.read_text())
        except Exception:
            existing = {}
    existing.update(
        {
            "loginUser": login_user,
            "authorize": authorize,
            "clientSource": client_source,
            "capturedAt": int(time.time()),
        }
    )
    SESSION_FILE.write_text(json.dumps(existing, indent=2, ensure_ascii=False))


def load_session_headers() -> tuple[str | None, str | None]:
    if not SESSION_FILE.exists():
        return None, None
    try:
        data = json.loads(SESSION_FILE.read_text())
    except Exception:
        return None, None
    authorize = data.get("authorize")
    client_source = data.get("clientSource")
    if not isinstance(authorize, str) or not authorize.startswith("EAAAA"):
        authorize = None
    if not isinstance(client_source, str) or not client_source:
        client_source = None
    return authorize, client_source


class TargetWatcher(threading.Thread):
    def __init__(self, target: dict, out: queue.Queue):
        super().__init__(daemon=True)
        self.target = target
        self.out = out
        self._id = 0
        self.pending: dict[str, dict] = {}

    def call(self, ws, method: str, params: dict | None = None):
        self._id += 1
        ws.send(json.dumps({"id": self._id, "method": method, "params": params or {}}))

    def run(self):
        ws_url = self.target.get("webSocketDebuggerUrl")
        if not ws_url:
            return
        title = self.target.get("title", "")
        url = self.target.get("url", "")
        try:
            ws = websocket.create_connection(ws_url, timeout=10)
            ws.settimeout(1)
            self.call(ws, "Network.enable")
            self.call(ws, "Runtime.enable")
            print(f"LISTENING {self.target.get('type')} {title[:80]} {url[:120]}", flush=True)
            while True:
                try:
                    message = json.loads(ws.recv())
                except websocket.WebSocketTimeoutException:
                    continue
                except Exception:
                    return
                method = message.get("method")
                params = message.get("params") or {}
                if method == "Network.requestWillBeSent":
                    request = params.get("request") or {}
                    request_url = request.get("url") or ""
                    if "/appointment/CheckIsSlotAvailable" not in request_url:
                        continue
                    request_id = params.get("requestId")
                    record = self.pending.setdefault(request_id, {})
                    record.update(
                        {
                            "url": request_url,
                            "headers": request.get("headers") or {},
                            "postData": request.get("postData"),
                            "targetUrl": url,
                        }
                    )
                    self.try_emit(request_id)
                elif method == "Network.requestWillBeSentExtraInfo":
                    request_id = params.get("requestId")
                    record = self.pending.setdefault(request_id, {})
                    record["extraHeaders"] = params.get("headers") or {}
                    self.try_emit(request_id)
        except Exception as exc:
            print(f"TARGET_LISTEN_FAIL {url[:100]} {type(exc).__name__}: {exc}", flush=True)

    def try_emit(self, request_id: str):
        record = self.pending.get(request_id) or {}
        headers = {}
        headers.update(record.get("headers") or {})
        headers.update(record.get("extraHeaders") or {})
        normalized = normalize_headers(headers)
        authorize = normalized.get("authorize")
        client_source = normalized.get("clientsource")
        if not (record.get("url") and authorize and client_source):
            return
        self.out.put(
            {
                "url": record.get("url"),
                "targetUrl": record.get("targetUrl"),
                "authorize": authorize,
                "clientSource": client_source,
                "postData": record.get("postData"),
            }
        )
        self.pending.pop(request_id, None)


def list_targets(cdp_url: str) -> list[dict]:
    targets = http_json(cdp_url.rstrip("/") + "/json", timeout=5)
    return [
        target
        for target in targets
        if target.get("webSocketDebuggerUrl")
        and target.get("type") in {"page", "iframe"}
        and (
            "vfsglobal.com" in (target.get("url") or "")
            or "cloudflare.com" in (target.get("url") or "")
            or "about:blank" in (target.get("url") or "")
        )
    ]


def capture_headers(cdp_url: str, login_user: str, timeout: int = 900) -> tuple[str, str]:
    out: queue.Queue = queue.Queue()
    seen_targets = set()
    deadline = time.time() + timeout
    print("Waiting for a real CheckIsSlotAvailable request from Chrome...", flush=True)
    while time.time() < deadline:
        for target in list_targets(cdp_url):
            target_id = target.get("id")
            if target_id in seen_targets:
                continue
            seen_targets.add(target_id)
            TargetWatcher(target, out).start()
        try:
            captured = out.get(timeout=2)
        except queue.Empty:
            continue
        save_session_headers(login_user, captured["authorize"], captured["clientSource"])
        print("CAPTURED CheckIsSlotAvailable", flush=True)
        print(f"targetUrl={captured.get('targetUrl')}", flush=True)
        print(f"authorize_len={len(captured['authorize'])} clientSource_len={len(captured['clientSource'])}", flush=True)
        if captured.get("postData"):
            print(f"postData={captured['postData']}", flush=True)
        return captured["authorize"], captured["clientSource"]
    raise TimeoutError("Timed out waiting for CheckIsSlotAvailable.")
