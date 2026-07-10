from __future__ import annotations

import json
import time

from .cdp import CdpClient, DEFAULT_CDP_URL
from .config import VFS_HOME


def _js_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def assist_login(cdp_url: str = DEFAULT_CDP_URL, login_user: str = "", password: str = "", timeout: int = 180) -> bool:
    if not login_user or not password:
        print("Login assist skipped: VFS_LOGIN_USER or VFS_PASSWORD is empty.", flush=True)
        return False

    deadline = time.time() + timeout
    last_result = None
    print("Login assist: opening VFS home and trying to reach login form...", flush=True)
    while time.time() < deadline:
        client = CdpClient.connect(cdp_url)
        try:
            try:
                result = client.evaluate(_assist_expression(login_user, password), await_promise=True, timeout=45)
            except RuntimeError as exc:
                if "navigated or closed" not in str(exc):
                    raise
                result = {"stage": "navigation_in_progress", "filled": False}
            last_result = result
            print(f"Login assist step: {result}", flush=True)
            if isinstance(result, dict) and result.get("filled"):
                return True
        finally:
            client.close()
        time.sleep(3)
    print(f"Login assist timed out. Last result: {last_result}", flush=True)
    return False


def submit_login_after_wait(cdp_url: str = DEFAULT_CDP_URL, wait_seconds: int = 30) -> dict:
    print(f"Waiting {wait_seconds} seconds before pressing VFS login button...", flush=True)
    time.sleep(wait_seconds)
    client = CdpClient.connect(cdp_url)
    try:
        result = client.evaluate(_submit_login_expression(), await_promise=True, timeout=45)
        print(f"Login submit step: {result}", flush=True)
        return result if isinstance(result, dict) else {"clicked": False, "result": result}
    except RuntimeError as exc:
        if "navigated or closed" not in str(exc):
            raise
        return {"clicked": True, "stage": "navigation_in_progress"}
    finally:
        client.close()


def _submit_login_expression() -> str:
    return r"""
        (async () => {
          const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
          const visible = el => {
            if (!el) return false;
            const style = getComputedStyle(el);
            const rect = el.getBoundingClientRect();
            return style.visibility !== "hidden" && style.display !== "none" && rect.width > 1 && rect.height > 1;
          };
          const textOf = el => ((el.innerText || el.textContent || el.value || el.ariaLabel || "") + "").trim();
          const button = Array.from(document.querySelectorAll("button, input[type='submit']"))
            .filter(visible)
            .find(el => /войти|sign in|login/i.test(textOf(el)));
          if (!button) {
            if (!location.pathname.endsWith("/login")) {
              return {clicked: false, stage: "already_left_login_page", url: location.href, title: document.title};
            }
            return {clicked: false, stage: "login_button_not_found", url: location.href, title: document.title};
          }
          button.scrollIntoView({block: "center", inline: "center"});
          button.dispatchEvent(new MouseEvent("mouseover", {bubbles: true}));
          button.dispatchEvent(new MouseEvent("mousedown", {bubbles: true}));
          button.dispatchEvent(new MouseEvent("mouseup", {bubbles: true}));
          button.click();
          await sleep(12000);
          return {
            clicked: true,
            stage: "login_clicked",
            url: location.href,
            title: document.title,
            body: document.body.innerText.slice(0, 1200)
          };
        })()
    """


def _assist_expression(login_user: str, password: str) -> str:
    return f"""
        (async () => {{
          const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
          const home = {_js_string(VFS_HOME)};
          const loginUser = {_js_string(login_user)};
          const password = {_js_string(password)};

          const visible = el => {{
            if (!el) return false;
            const style = getComputedStyle(el);
            const rect = el.getBoundingClientRect();
            return style.visibility !== "hidden" && style.display !== "none" && rect.width > 1 && rect.height > 1;
          }};

          const textOf = el => ((el.innerText || el.textContent || el.value || el.ariaLabel || "") + "").trim();
          const click = el => {{
            el.scrollIntoView({{block: "center", inline: "center"}});
            el.dispatchEvent(new MouseEvent("mouseover", {{bubbles: true}}));
            el.dispatchEvent(new MouseEvent("mousedown", {{bubbles: true}}));
            el.dispatchEvent(new MouseEvent("mouseup", {{bubbles: true}}));
            el.click();
          }};

          const setValue = (el, value) => {{
            const proto = el instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
            const setter = Object.getOwnPropertyDescriptor(proto, "value")?.set;
            if (setter) setter.call(el, value);
            else el.value = value;
            el.dispatchEvent(new Event("input", {{bubbles: true}}));
            el.dispatchEvent(new Event("change", {{bubbles: true}}));
            el.dispatchEvent(new KeyboardEvent("keyup", {{bubbles: true}}));
          }};

          const all = selector => Array.from(document.querySelectorAll(selector)).filter(visible);
          const clickable = () => all("button, a, [role='button'], input[type='button'], input[type='submit']");
          const findByText = patterns => clickable().find(el => patterns.some(pattern => pattern.test(textOf(el))));

          if (!location.href.includes("visa.vfsglobal.com/rus/ru/hun")) {{
            location.href = home;
            await sleep(2000);
            return {{stage: "navigate_home", filled: false, url: location.href}};
          }}

          const cookieButton =
            document.querySelector("#onetrust-accept-btn-handler") ||
            findByText([/accept all/i, /согласиться\\s+с\\s+использованием\\s+всех/i, /принять/i]);
          if (cookieButton && visible(cookieButton)) {{
            click(cookieButton);
            await sleep(1200);
          }}

          const inputs = all("input");
          const emailInput = document.querySelector("#email") || inputs.find(el => {{
            const attrs = `${{el.type}} ${{el.name}} ${{el.id}} ${{el.placeholder}} ${{el.autocomplete}}`.toLowerCase();
            return (attrs.includes("email") || attrs.includes("login") || attrs.includes("username") || attrs.includes("user")) &&
              el.type !== "hidden" &&
              el.type !== "checkbox";
          }});
          const passInput = document.querySelector("#password") || inputs.find(el => {{
            const attrs = `${{el.type}} ${{el.name}} ${{el.id}} ${{el.placeholder}} ${{el.autocomplete}}`.toLowerCase();
            return el.type === "password" || attrs.includes("password") || attrs.includes("парол");
          }});

          if (emailInput && passInput) {{
            setValue(emailInput, loginUser);
            setValue(passInput, password);
            emailInput.blur();
            passInput.focus();
            return {{
              stage: "filled_login_form",
              filled: true,
              url: location.href,
              emailSelector: emailInput.name || emailInput.id || emailInput.placeholder || "input",
              passwordSelector: passInput.name || passInput.id || passInput.placeholder || "input[type=password]"
            }};
          }}

          if (location.pathname.endsWith("/book-an-appointment")) {{
            const loginLink =
              document.querySelector("a.lets-get-started[href$='/login']") ||
              Array.from(document.querySelectorAll("a")).find(a => a.href.endsWith("/login") && /записаться/i.test(textOf(a)));
            if (loginLink) {{
              const loginHref = loginLink.href;
              click(loginLink);
              await sleep(2500);
              if (!location.pathname.endsWith("/login")) {{
                location.assign(loginHref);
                await sleep(4000);
              }}
              return {{stage: "opened_login", filled: false, url: location.href}};
            }}
          }}

          const appointmentButton =
            document.querySelector("#action-link-2[href$='/book-an-appointment']") ||
            Array.from(document.querySelectorAll("a")).find(a => a.href.endsWith("/book-an-appointment") && /записаться|запись\\s+в\\s+визовый\\s+центр/i.test(textOf(a))) ||
            findByText([
              /записаться\\s+на\\s+при[её]м/i,
              /запись\\s+в\\s+визовый\\s+центр/i,
              /book\\s+an\\s+appointment/i,
              /schedule\\s+appointment/i
            ]);
          if (appointmentButton) {{
            const appointmentHref = appointmentButton.href || `${{home.replace(/\\/$/, "")}}/book-an-appointment`;
            click(appointmentButton);
            await sleep(3000);
            if (!location.pathname.endsWith("/book-an-appointment")) {{
              location.assign(appointmentHref);
              await sleep(3500);
            }}
            return {{stage: "opened_appointment", filled: false, url: location.href}};
          }}

          window.scrollBy(0, Math.max(350, window.innerHeight * 0.8));
          await sleep(1200);
          return {{stage: "scrolling", filled: false, url: location.href, y: window.scrollY}};
        }})()
    """
