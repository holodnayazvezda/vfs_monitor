from __future__ import annotations

import argparse
import json
import os
import time

from .capture import capture_headers, load_session_headers
from .cdp import CdpClient, DEFAULT_CDP_URL, DEFAULT_CHROME, DEFAULT_PROFILE, is_cdp_up, launch_chrome
from .config import CATEGORIES, LIFT_API, TARGET, load_env_file, slot_payload
from .telegram import broadcast


def log(message: str):
    print(message, flush=True)


def summarize(result: dict) -> str:
    body = result.get("body")
    label = f"{result.get('categoryCode')} {result.get('categoryName')}"
    if result.get("status") != 200:
        code = body.get("code") if isinstance(body, dict) else ""
        desc = body.get("description") if isinstance(body, dict) else ""
        return f"{label}: HTTP {result.get('status')} {code} {desc}".strip()
    if isinstance(body, dict) and body.get("earliestDate"):
        slots = body.get("earliestSlotLists") or []
        dates = ", ".join(str(slot.get("date")) for slot in slots if isinstance(slot, dict) and slot.get("date"))
        return f"{label}: slot {body.get('earliestDate')} ({len(slots)}); {dates}"
    err = body.get("error") if isinstance(body, dict) else None
    if isinstance(err, dict):
        return f"{label}: no slots ({err.get('code')} {err.get('description')})"
    return f"{label}: {str(body)[:300]}"


def human_report(results: list[dict]) -> str:
    lines = ["VFS Hungary SPB check", time.strftime("%Y-%m-%d %H:%M:%S")]
    lines.extend(summarize(result) for result in results)
    return "\n".join(lines)


def has_slot(result: dict) -> bool:
    body = result.get("body")
    return result.get("status") == 200 and isinstance(body, dict) and bool(body.get("earliestDate") or body.get("earliestSlotLists"))


def needs_recapture(results: list[dict]) -> bool:
    if not results:
        return True
    if any(result.get("status") == 200 for result in results):
        return False
    bad_codes = {"401101", "403201", "429201", "429001"}
    for result in results:
        body = result.get("body")
        if result.get("status") in (401, 403):
            return True
        if isinstance(body, dict) and str(body.get("code") or "") in bad_codes:
            return True
    return False


def ensure_chrome(args):
    if is_cdp_up(args.cdp_url):
        return
    broadcast(
        "VFS monitor: Chrome/CDP is not available. Opening Chrome now. "
        "Please log in manually and trigger one appointment check in VFS."
    )
    launch_chrome(args.cdp_port, args.profile_dir, args.chrome_path)
    deadline = time.time() + 20
    while time.time() < deadline:
        if is_cdp_up(args.cdp_url):
            return
        time.sleep(0.5)


def recapture(args) -> tuple[str, str]:
    ensure_chrome(args)
    broadcast(
        "VFS monitor needs a fresh browser session.\n"
        "Open Chrome, log in to VFS manually, complete CAPTCHA if needed, "
        "then trigger one appointment/category check. I will capture fresh headers."
    )
    authorize, client_source = capture_headers(args.cdp_url, args.login_user, timeout=args.capture_timeout)
    broadcast("VFS monitor: fresh VFS headers captured; monitoring resumes.")
    return authorize, client_source


def run_fetch(authorize: str, client_source: str, login_user: str, cdp_url: str) -> list[dict]:
    client = CdpClient.connect(cdp_url)
    try:
        cfg = {
            "api": LIFT_API,
            "route": TARGET["route"],
            "acceptLanguage": TARGET["accept_language"],
            "authorize": authorize,
            "clientSource": client_source,
            "categories": CATEGORIES,
            "payloads": {code: slot_payload(login_user, code) for code in CATEGORIES},
        }
        expression = f"""
            (async () => {{
              const cfg = {json.dumps(cfg, ensure_ascii=False)};
              const results = [];
              for (const [code, name] of Object.entries(cfg.categories)) {{
                const response = await fetch(`${{cfg.api}}/appointment/CheckIsSlotAvailable`, {{
                  method: "POST",
                  credentials: "include",
                  headers: {{
                    accept: "application/json, text/plain, */*",
                    "accept-language": cfg.acceptLanguage,
                    authorize: cfg.authorize,
                    clientSource: cfg.clientSource,
                    "content-type": "application/json;charset=utf-8",
                    route: cfg.route,
                  }},
                  body: JSON.stringify(cfg.payloads[code]),
                }});
                const text = await response.text();
                let body;
                try {{ body = JSON.parse(text); }} catch {{ body = text; }}
                results.push({{categoryCode: code, categoryName: name, status: response.status, body}});
              }}
              return results;
            }})()
        """
        return client.evaluate(expression, await_promise=True, timeout=60)
    finally:
        client.close()


def main():
    load_env_file()
    parser = argparse.ArgumentParser(description="VFS CDP monitor service")
    parser.add_argument("--cdp-url", default=DEFAULT_CDP_URL)
    parser.add_argument("--cdp-port", type=int, default=9222)
    parser.add_argument("--profile-dir", default=DEFAULT_PROFILE)
    parser.add_argument("--chrome-path", default=DEFAULT_CHROME)
    parser.add_argument("--login-user", default=os.getenv("VFS_LOGIN_USER", ""))
    parser.add_argument("--interval", type=int, default=120)
    parser.add_argument("--capture-timeout", type=int, default=900)
    parser.add_argument("--telegram-all", action=argparse.BooleanOptionalAction, default=True)
    args = parser.parse_args()

    if not args.login_user:
        raise SystemExit("--login-user is required")

    log("VFS CDP monitor service starting")
    log(f"Categories: {', '.join(CATEGORIES)}")
    ensure_chrome(args)
    authorize, client_source = load_session_headers()
    if not (authorize and client_source):
        authorize, client_source = recapture(args)

    while True:
        try:
            ensure_chrome(args)
            results = run_fetch(authorize, client_source, args.login_user, args.cdp_url)
            report = human_report(results)
            log(report)
            if args.telegram_all or any(has_slot(result) for result in results):
                broadcast(report)
            if needs_recapture(results):
                broadcast("VFS monitor: session seems invalid/rate-limited. Please refresh/login and trigger one category check.")
                authorize, client_source = recapture(args)
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            message = f"VFS monitor error: {type(exc).__name__}: {exc}"
            log(message)
            broadcast(message + "\nPlease check Chrome/VFS login. I will wait for fresh headers.")
            try:
                authorize, client_source = recapture(args)
            except Exception as recapture_exc:
                log(f"Recapture failed: {type(recapture_exc).__name__}: {recapture_exc}")
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
