from __future__ import annotations

import os
from pathlib import Path

import yaml


ROOT = Path(os.getenv("VFS_MONITOR_ROOT", Path(__file__).resolve().parents[1]))
CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"
CONFIG_DIR.mkdir(parents=True, exist_ok=True)
DATA_DIR.mkdir(parents=True, exist_ok=True)

LIFT_API = "https://lift-api.vfsglobal.com"
VFS_HOME = "https://visa.vfsglobal.com/rus/ru/hun/"
SESSION_FILE = CONFIG_DIR / "browser_session.local.json"

DEFAULT_TARGET = {
    "route": "rus/ru/hun",
    "country_code": "rus",
    "mission_code": "hun",
    "center_code": "HUNRUS38",
    "accept_language": "ru,en-US;q=0.9,en;q=0.8",
    "categories": {
        "VS_1_2": "Other (Not a Tourism) / Иные цели",
        "VS_1_1": "Tourism / Туризм",
    },
}


def load_target() -> dict:
    path = CONFIG_DIR / "vfs_target.yaml"
    if not path.exists():
        return DEFAULT_TARGET.copy()
    loaded = yaml.safe_load(path.read_text()) or {}
    target = DEFAULT_TARGET.copy()
    target.update(loaded)
    target["categories"] = loaded.get("categories") or DEFAULT_TARGET["categories"]
    return target


TARGET = load_target()
CATEGORIES = TARGET["categories"]


def load_env_file() -> None:
    path = CONFIG_DIR / ".env"
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def slot_payload(login_user: str, category_code: str) -> dict:
    return {
        "countryCode": TARGET["country_code"],
        "missionCode": TARGET["mission_code"],
        "vacCode": TARGET["center_code"],
        "visaCategoryCode": category_code,
        "roleName": "Individual",
        "loginUser": login_user,
        "payCode": "",
    }
