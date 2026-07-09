from __future__ import annotations

import argparse
import os

from .capture import capture_headers
from .cdp import DEFAULT_CDP_URL
from .config import load_env_file


def main():
    load_env_file()
    parser = argparse.ArgumentParser(description="Capture VFS headers from Chrome CDP")
    parser.add_argument("--cdp-url", default=DEFAULT_CDP_URL)
    parser.add_argument("--login-user", default=os.getenv("VFS_LOGIN_USER", ""))
    parser.add_argument("--timeout", type=int, default=900)
    args = parser.parse_args()
    if not args.login_user:
        raise SystemExit("--login-user or VFS_LOGIN_USER is required")
    capture_headers(args.cdp_url, args.login_user, timeout=args.timeout)


if __name__ == "__main__":
    main()
