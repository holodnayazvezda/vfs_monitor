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
            result = client.evaluate(_assist_expression(login_user, password), await_promise=True, timeout=45)
            last_result = result
            print(f"Login assist step: {result}", flush=True)
            if isinstance(result, dict) and result.get("filled"):
                return True
        finally:
            client.close()
        time.sleep(3)
    print(f"Login assist timed out. Last result: {last_result}", flush=True)
    return False


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

          for (const pattern of [/accept all/i, /accept/i, /соглас/i, /принять/i, /разреш/i]) {{
            const cookieButton = findByText([pattern]);
            if (cookieButton) {{
              click(cookieButton);
              await sleep(1200);
              break;
            }}
          }}

          const inputs = all("input");
          const emailInput = inputs.find(el => {{
            const attrs = `${{el.type}} ${{el.name}} ${{el.id}} ${{el.placeholder}} ${{el.autocomplete}}`.toLowerCase();
            return attrs.includes("email") || attrs.includes("login") || attrs.includes("username") || attrs.includes("user");
          }});
          const passInput = inputs.find(el => {{
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

          const appointmentButton = findByText([
            /записаться\\s+на\\s+при[её]м/i,
            /book\\s+an\\s+appointment/i,
            /schedule\\s+appointment/i
          ]);
          if (appointmentButton) {{
            click(appointmentButton);
            await sleep(3000);
            return {{stage: "clicked_appointment", filled: false, url: location.href}};
          }}

          window.scrollBy(0, Math.max(350, window.innerHeight * 0.8));
          await sleep(1200);
          return {{stage: "scrolling", filled: false, url: location.href, y: window.scrollY}};
        }})()
    """
