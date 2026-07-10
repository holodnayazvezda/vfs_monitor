from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.parse
import urllib.request
from pathlib import Path

import websocket

from .config import ROOT, VFS_HOME


DEFAULT_CDP_URL = "http://127.0.0.1:9222"
DEFAULT_CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
DEFAULT_PROFILE = str(ROOT / ".chrome-profile")


def http_json(url: str, timeout: int = 5):
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def http_json_put(url: str, timeout: int = 5):
    request = urllib.request.Request(url, method="PUT")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def is_cdp_up(cdp_url: str = DEFAULT_CDP_URL) -> bool:
    try:
        http_json(cdp_url.rstrip("/") + "/json/version", timeout=2)
        return True
    except Exception:
        return False


def launch_chrome(cdp_port: int = 9222, profile_dir: str = DEFAULT_PROFILE, chrome_path: str = DEFAULT_CHROME):
    Path(profile_dir).mkdir(parents=True, exist_ok=True)
    cdp_address = os.getenv("CDP_ADDRESS", "127.0.0.1")
    allow_origins = os.getenv("CDP_ALLOW_ORIGINS", f"http://127.0.0.1:{cdp_port}")
    command = [
        chrome_path,
        f"--remote-debugging-port={cdp_port}",
        f"--remote-debugging-address={cdp_address}",
        f"--remote-allow-origins={allow_origins}",
        f"--user-data-dir={profile_dir}",
        "--lang=ru-RU",
        "--new-window",
        VFS_HOME,
    ]
    print("Launching Chrome with CDP...", flush=True)
    return subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def find_vfs_tab(cdp_url: str = DEFAULT_CDP_URL) -> dict | None:
    tabs = http_json(cdp_url.rstrip("/") + "/json", timeout=5)
    pages = [tab for tab in tabs if tab.get("type") == "page"]
    for part in (
        "/book-an-appointment",
        "/application-detail",
        "visa.vfsglobal.com/rus/ru/hun",
        "visa.vfsglobal.com",
    ):
        for tab in pages:
            url = tab.get("url", "")
            if part in url and "/login" not in url:
                return tab
    for tab in pages:
        if "visa.vfsglobal.com" in (tab.get("url") or ""):
            return tab
    return pages[0] if pages else None


def open_vfs_tab(cdp_url: str = DEFAULT_CDP_URL) -> dict:
    url = cdp_url.rstrip("/") + "/json/new?" + urllib.parse.quote(VFS_HOME, safe=":/")
    return http_json_put(url, timeout=5)


def wait_for_vfs_tab(cdp_url: str = DEFAULT_CDP_URL, timeout: int = 180) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        tab = find_vfs_tab(cdp_url)
        if tab:
            return tab
        time.sleep(1)
    raise RuntimeError(f"No VFS tab found via {cdp_url}")


class CdpClient:
    def __init__(self, websocket_url: str):
        self.ws = websocket.create_connection(websocket_url, timeout=30)
        self._id = 0

    @classmethod
    def connect(cls, cdp_url: str = DEFAULT_CDP_URL) -> "CdpClient":
        tab = wait_for_vfs_tab(cdp_url)
        print(f"Connected tab: {tab.get('title')} | {tab.get('url')}", flush=True)
        return cls(tab["webSocketDebuggerUrl"])

    def close(self):
        self.ws.close()

    def call(self, method: str, params: dict | None = None) -> dict:
        self._id += 1
        current_id = self._id
        self.ws.send(json.dumps({"id": current_id, "method": method, "params": params or {}}))
        while True:
            message = json.loads(self.ws.recv())
            if message.get("id") != current_id:
                continue
            if "error" in message:
                raise RuntimeError(f"CDP {method} error: {message['error']}")
            return message.get("result", {})

    def evaluate(self, expression: str, await_promise: bool = False, timeout: int = 60):
        self.call("Runtime.enable")
        old_timeout = self.ws.gettimeout()
        self.ws.settimeout(timeout)
        try:
            result = self.call(
                "Runtime.evaluate",
                {
                    "expression": expression,
                    "awaitPromise": await_promise,
                    "returnByValue": True,
                    "userGesture": True,
                },
            )
        finally:
            self.ws.settimeout(old_timeout)
        if result.get("exceptionDetails"):
            raise RuntimeError(json.dumps(result["exceptionDetails"], ensure_ascii=False))
        return (result.get("result") or {}).get("value")
