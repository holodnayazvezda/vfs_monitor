from __future__ import annotations

import json
import os
import time
import urllib.request

from .config import DATA_DIR, load_env_file


load_env_file()

SUBSCRIBERS_FILE = DATA_DIR / "tg_subscribers.json"


def _default_subscribers() -> list[dict]:
    chat_id = int(os.getenv("OWNER_CHAT_ID", "0") or "0")
    if not chat_id:
        return []
    return [{"chat_id": chat_id, "username": "owner", "added_at": int(time.time())}]


def load_subscribers() -> list[dict]:
    owner_id = int(os.getenv("OWNER_CHAT_ID", "0") or "0")
    subscribers: list[dict] = []
    if SUBSCRIBERS_FILE.exists():
        try:
            data = json.loads(SUBSCRIBERS_FILE.read_text())
            subscribers = [s for s in data.get("subscribers", []) if int(s.get("chat_id") or 0)]
        except Exception:
            subscribers = []
    if owner_id and not any(int(s.get("chat_id") or 0) == owner_id for s in subscribers):
        subscribers.append({"chat_id": owner_id, "username": "owner", "added_at": int(time.time())})
    if not subscribers:
        subscribers = _default_subscribers()
    save_subscribers(subscribers)
    return subscribers


def save_subscribers(subscribers: list[dict]) -> None:
    SUBSCRIBERS_FILE.write_text(json.dumps({"subscribers": subscribers}, indent=2, ensure_ascii=False))


def send_to(chat_id: int, text: str, silent: bool = False) -> bool:
    token = os.getenv("TG_TOKEN", "")
    if not token:
        print("[telegram] TG_TOKEN is not configured", flush=True)
        return False
    try:
        request = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data=json.dumps(
                {
                    "chat_id": chat_id,
                    "text": text,
                    "disable_notification": silent,
                }
            ).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=15) as response:
            return response.status == 200
    except Exception as exc:
        print(f"[telegram] send to {chat_id} failed: {exc}", flush=True)
        return False


def broadcast(text: str, silent: bool = False) -> int:
    count = 0
    for subscriber in load_subscribers():
        if send_to(int(subscriber["chat_id"]), text, silent=silent):
            count += 1
    return count
