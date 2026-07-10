from __future__ import annotations

import argparse
import os

from .cdp import DEFAULT_CDP_URL
from .config import load_env_file
from .login_assist import assist_login


def main():
    load_env_file()
    parser = argparse.ArgumentParser(description="Open VFS and fill login form in an already visible Chrome window")
    parser.add_argument("--cdp-url", default=DEFAULT_CDP_URL)
    parser.add_argument("--login-user", default=os.getenv("VFS_LOGIN_USER", ""))
    parser.add_argument("--password", default=os.getenv("VFS_PASSWORD", ""))
    parser.add_argument("--timeout", type=int, default=180)
    args = parser.parse_args()
    if not args.login_user:
        raise SystemExit("--login-user or VFS_LOGIN_USER is required")
    if not args.password:
        raise SystemExit("--password or VFS_PASSWORD is required")
    ok = assist_login(args.cdp_url, args.login_user, args.password, timeout=args.timeout)
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
