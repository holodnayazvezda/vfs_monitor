from __future__ import annotations

import argparse
import json
import os
import time

from .capture import capture_headers, load_session_headers
from .cdp import CdpClient, DEFAULT_CDP_URL, DEFAULT_CHROME, DEFAULT_PROFILE, find_vfs_tab, is_cdp_up, launch_chrome, open_vfs_tab
from .config import CATEGORIES, LIFT_API, TARGET, load_env_file, slot_payload
from .login_assist import assist_login, submit_login_after_wait
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


def needs_browser_login(results: list[dict]) -> bool:
    if not results:
        return True
    for result in results:
        body = result.get("body")
        code = str(body.get("code") or "") if isinstance(body, dict) else ""
        if code == "NO_BROWSER_SESSION":
            return True
        if result.get("status") in (401, 403):
            return True
        if code in {"401101", "403201"}:
            return True
    return False


def ensure_chrome(args):
    if is_cdp_up(args.cdp_url):
        if find_vfs_tab(args.cdp_url):
            return
        log("Chrome/CDP is available, but no VFS tab is open. Opening VFS tab.")
        try:
            open_vfs_tab(args.cdp_url)
            deadline = time.time() + 20
            while time.time() < deadline:
                if find_vfs_tab(args.cdp_url):
                    return
                time.sleep(0.5)
        except Exception as exc:
            log(f"Opening VFS tab via CDP failed: {type(exc).__name__}: {exc}")
        log("VFS tab is still unavailable; launching Chrome.")
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
    if args.login_assist:
        if args.password:
            broadcast(
                "VFS monitor: preparing VFS login form. "
                "I will fill email/password, then you complete CAPTCHA and submit manually."
            )
            filled = assist_login(args.cdp_url, args.login_user, args.password, timeout=args.login_assist_timeout)
            if filled:
                broadcast(
                    "VFS monitor: login form filled. "
                    "Please complete CAPTCHA and press the login/continue button manually."
                )
            else:
                broadcast(
                    "VFS monitor: could not fill login form automatically. "
                    "Please log in manually, then trigger one appointment/category check."
                )
        else:
            broadcast(
                "VFS monitor: VFS_PASSWORD is empty, so login assist is skipped. "
                "Please log in manually and trigger one appointment/category check."
            )
    broadcast(
        "VFS monitor needs a fresh browser session.\n"
        "Open Chrome, complete CAPTCHA/login if needed, "
        "then trigger one appointment/category check. I will capture fresh headers."
    )
    authorize, client_source = capture_headers(args.cdp_url, args.login_user, timeout=args.capture_timeout)
    broadcast("VFS monitor: fresh VFS headers captured; monitoring resumes.")
    return authorize, client_source


def assisted_browser_login(args) -> None:
    ensure_chrome(args)
    if not args.login_assist:
        return
    if not args.password:
        broadcast(
            "VFS monitor: VFS_PASSWORD is empty, so login assist is skipped. "
            "Please log in manually."
        )
        return
    broadcast(
        "VFS monitor: browser session is not ready. "
        "I will open/fill VFS login, then wait for manual CAPTCHA."
    )
    filled = assist_login(args.cdp_url, args.login_user, args.password, timeout=args.login_assist_timeout)
    if not filled:
        broadcast("VFS monitor: login form was not filled automatically. Please check Chrome.")
        return
    broadcast(
        f"VFS monitor: login form filled. You have {args.login_submit_wait} seconds "
        "to complete CAPTCHA; then I will press the login button."
    )
    submit_result = submit_login_after_wait(args.cdp_url, wait_seconds=args.login_submit_wait)
    broadcast(f"VFS monitor: login submit step finished: {submit_result.get('stage') or submit_result}")


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


def run_browser_fetch(login_user: str, cdp_url: str) -> list[dict]:
    client = CdpClient.connect(cdp_url)
    try:
        cfg = {
            "api": LIFT_API,
            "route": TARGET["route"],
            "acceptLanguage": TARGET["accept_language"],
            "categories": CATEGORIES,
            "payloads": {code: slot_payload(login_user, code) for code in CATEGORIES},
        }
        expression = f"""
            (async () => {{
              const cfg = {json.dumps(cfg, ensure_ascii=False)};
              const readMaybeJson = value => {{
                if (!value) return value;
                try {{ return JSON.parse(value); }} catch {{ return value; }}
              }};
              const cleanHeader = value => String(value || "").replace(/[\\u0000-\\u001f\\u007f]/g, "");
              const authorize = cleanHeader(sessionStorage.getItem("JWT") || "");
              const clientSource = cleanHeader(readMaybeJson(sessionStorage.getItem("csk_str") || ""));
              const loginUser = sessionStorage.getItem("logged_email") || Object.values(cfg.payloads)[0]?.loginUser || "";
              if (!authorize || !clientSource) {{
                return [{{categoryCode: "session", categoryName: "Browser session", status: 401, body: {{code: "NO_BROWSER_SESSION", description: "JWT/clientSource not found in browser sessionStorage"}}}}];
              }}
              const results = [];
              for (const [code, name] of Object.entries(cfg.categories)) {{
                const payload = {{...cfg.payloads[code], loginUser}};
                const response = await fetch(`${{cfg.api}}/appointment/CheckIsSlotAvailable`, {{
                  method: "POST",
                  credentials: "include",
                  headers: {{
                    accept: "application/json, text/plain, */*",
                    "accept-language": cfg.acceptLanguage,
                    authorize,
                    clientSource,
                    "content-type": "application/json;charset=utf-8",
                    route: cfg.route,
                  }},
                  body: JSON.stringify(payload),
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
    parser.add_argument("--password", default=os.getenv("VFS_PASSWORD", ""))
    parser.add_argument("--interval", type=int, default=120)
    parser.add_argument("--capture-timeout", type=int, default=900)
    parser.add_argument("--login-assist", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--login-assist-timeout", type=int, default=180)
    parser.add_argument("--login-submit-wait", type=int, default=30)
    parser.add_argument("--direct-browser", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--telegram-all", action=argparse.BooleanOptionalAction, default=True)
    args = parser.parse_args()

    if not args.login_user:
        raise SystemExit("--login-user is required")

    log("VFS CDP monitor service starting")
    log(f"Categories: {', '.join(CATEGORIES)}")
    ensure_chrome(args)
    authorize, client_source = None, None
    if not args.direct_browser:
        authorize, client_source = load_session_headers()
    if not args.direct_browser and not (authorize and client_source):
        authorize, client_source = recapture(args)

    while True:
        try:
            ensure_chrome(args)
            if args.direct_browser:
                results = run_browser_fetch(args.login_user, args.cdp_url)
            else:
                results = run_fetch(authorize, client_source, args.login_user, args.cdp_url)
            report = human_report(results)
            log(report)
            if args.telegram_all or any(has_slot(result) for result in results):
                broadcast(report)
            if args.direct_browser and needs_browser_login(results):
                broadcast("VFS monitor: browser session seems invalid. Please complete login/CAPTCHA; I will retry direct browser requests.")
                assisted_browser_login(args)
            elif not args.direct_browser and needs_recapture(results):
                broadcast("VFS monitor: session seems invalid/rate-limited. Please refresh/login and trigger one category check.")
                authorize, client_source = recapture(args)
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            message = f"VFS monitor error: {type(exc).__name__}: {exc}"
            log(message)
            if args.direct_browser:
                broadcast(message + "\nPlease check Chrome/VFS login. I will retry direct browser requests.")
                try:
                    assisted_browser_login(args)
                except Exception as login_exc:
                    log(f"Login assist failed: {type(login_exc).__name__}: {login_exc}")
            else:
                broadcast(message + "\nPlease check Chrome/VFS login. I will wait for fresh headers.")
                try:
                    authorize, client_source = recapture(args)
                except Exception as recapture_exc:
                    log(f"Recapture failed: {type(recapture_exc).__name__}: {recapture_exc}")
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
