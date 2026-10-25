import json
import os
from pathlib import Path
import re
import sys
import time
import urllib.error
import urllib.request

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

MAX_PAGE_BYTES = 2_000_000
STATE_PATH = Path(os.environ.get("MONITOR_STATE_FILE", ".monitor-state/state.json"))

CAPTCHA_PHRASES = (
    "select correct number boxes",
    "captcha",
    "verify you are human",
    "human verification",
    "security verification",
    "prove you are not a robot",
    "unusual activity",
)
LOGIN_PHRASES = (
    "sign in",
    "log in",
    "login",
    "password",
    "not registered yet",
)
HUMAN_CHECK_PATHS = ("/captcha", "/account/bot", "/userverification")


def send_telegram_message(message):
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        raise RuntimeError(
            "Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID GitHub Actions secret."
        )

    # Never print or log this URL: it contains the Telegram bot token.
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    body = json.dumps({
        "chat_id": chat_id,
        "text": message,
        "disable_web_page_preview": True,
    }).encode("utf-8")
    request = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Telegram API returned HTTP {exc.code}. Check the Telegram secrets.") from None
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Could not reach Telegram API: {exc.reason}") from None

    if not result.get("ok"):
        raise RuntimeError("Telegram did not accept the message. Check the bot and chat ID.")
    print("Telegram notification sent.")


def read_state():
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def write_state(state):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state), encoding="utf-8")


def page_text(driver):
    source = driver.page_source
    if len(source.encode("utf-8")) > MAX_PAGE_BYTES:
        raise RuntimeError("Status page exceeded the 2 MB safety limit.")
    # Remove scripts/styles before looking for visible page wording.
    source = re.sub(r"<script\b[^>]*>.*?</script\s*>", " ", source, flags=re.I | re.S)
    source = re.sub(r"<style\b[^>]*>.*?</style\s*>", " ", source, flags=re.I | re.S)
    source = re.sub(r"<[^>]+>", " ", source)
    return re.sub(r"\s+", " ", source).strip().casefold()


def classify_page(driver, text, available_text, no_slots_text):
    current_url = driver.current_url.casefold()

    # Detect a visible CAPTCHA/human check and stop. Never attempt to solve or bypass it.
    captcha_visible = False
    try:
        captcha_visible = any(
            element.is_displayed()
            for element in driver.find_elements(
                By.XPATH,
                "//*[contains(translate(@id,'CAPTCHA','captcha'),'captcha') "
                "or contains(translate(@src,'CAPTCHA','captcha'),'captcha') "
                "or contains(translate(@class,'CAPTCHA','captcha'),'captcha')]",
            )
        )
    except Exception:
        pass

    if captcha_visible or any(phrase in text for phrase in CAPTCHA_PHRASES):
        return "captcha_or_human_verification"
    if any(path in current_url for path in HUMAN_CHECK_PATHS):
        return "captcha_or_human_verification"

    # A login page is not treated as appointment availability.
    password_fields = driver.find_elements(By.CSS_SELECTOR, "input[type='password']")
    if password_fields or (
        any(word in current_url for word in ("/login", "/log-in", "/signin"))
        and any(phrase in text for phrase in LOGIN_PHRASES)
    ):
        return "login_required"

    if no_slots_text and no_slots_text.casefold() in text:
        return "not_available"
    if available_text and available_text.casefold() in text:
        return "available"
    return "unknown"


def notification_for(status, url):
    if status == "captcha_or_human_verification":
        return (
            "🛑 BLS monitoring paused: CAPTCHA or human verification was detected. "
            "Please open the official page and complete verification manually.\n" + url
        )
    if status == "login_required":
        return (
            "🔐 BLS monitoring needs your attention: the page requires login. "
            "Please sign in manually in your browser; the monitor will not bypass verification.\n" + url
        )
    if status == "available":
        return (
            "📢 Spain visa appointment status: the configured availability text was found. "
            "Please open the official website and confirm the result.\n" + url
        )
    if status == "unknown":
        return (
            "⚠️ BLS monitor could not identify the appointment status. The page may have changed "
            "or may require manual review.\n" + url
        )
    return None


def main():
    # A protected BLS login page is sufficient for login/CAPTCHA detection.
    # A public appointment-status page and availability phrase are optional.
    url = (
        os.environ.get("PUBLIC_STATUS_URL", "").strip()
        or os.environ.get("BLS_LOGIN_URL", "").strip()
        or "https://saudi.blsspainglobal.com/Global/Account/LogIn?ReturnUrl=%2Fglobal%2Fappointment%2Fnewappointment"
    )
    available_text = os.environ.get("APPOINTMENT_AVAILABLE_TEXT", "").strip()
    no_slots_text = os.environ.get("NO_APPOINTMENTS_TEXT", "No appointments available").strip()

    if not url.startswith("https://"):
        raise RuntimeError("The configured BLS URL must use HTTPS.")

    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-notifications")

    driver = webdriver.Chrome(options=options)
    try:
        driver.set_page_load_timeout(45)
        print("Opening configured BLS status page...")
        try:
            driver.get(url)
        except Exception as page_error:
            # A slow/blocked page can still have useful login/CAPTCHA content.
            print(f"Page navigation warning: {type(page_error).__name__}")
        try:
            WebDriverWait(driver, 20).until(
                lambda browser: browser.execute_script("return document.readyState") in ("interactive", "complete")
            )
        except Exception:
            print("Page readiness wait ended; checking whatever page content loaded.")
        time.sleep(2)

        text = page_text(driver)
        status = classify_page(driver, text, available_text, no_slots_text)
        old_state = read_state()
        previous = old_state.get("status")

        # Notify on first observation of a state or when it changes, avoiding repeat alerts every run.
        if status != previous:
            message = notification_for(status, url)
            if message:
                send_telegram_message(message)
            else:
                print("No-slots phrase detected; no Telegram alert sent.")
        else:
            print(f"Status unchanged: {status}")

        write_state({"status": status, "checked_at": int(time.time())})
        print(f"Monitor result: {status}")
    finally:
        driver.quit()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Monitor failed: {exc}", file=sys.stderr)
        # Best-effort alert for operational errors; don't mask the original failure.
        try:
            send_telegram_message(
                "❌ Spain visa monitor failed to run. Check the latest GitHub Actions log. "
                "No credentials or session data are included in this alert."
            )
        except Exception as notify_exc:
            print(f"Failure alert could not be sent: {notify_exc}", file=sys.stderr)
        sys.exit(1)
