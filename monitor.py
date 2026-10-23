import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

MAX_PAGE_BYTES = 2_000_000
STATE_PATH = Path(os.environ.get("MONITOR_STATE_FILE", ".monitor-state/state.json"))

def send_telegram_message(message):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        raise RuntimeError("Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID GitHub Secret.")

    # Telegram's Bot API token is required in the API path. Never print this URL.
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    body = json.dumps({"chat_id": chat_id, "text": message, "disable_web_page_preview": True}).encode("utf-8")
    request = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(request, timeout=20) as response:
        result = json.loads(response.read().decode("utf-8"))
    if not result.get("ok"):
        raise RuntimeError("Telegram rejected the message.")
    print("Telegram notification sent.")

def read_state():
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}

def write_state(state):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state), encoding="utf-8")

def main():
    url = os.environ.get("PUBLIC_STATUS_URL", "").strip()
    available_text = os.environ.get("APPOINTMENT_AVAILABLE_TEXT", "").strip()
    no_slots_text = os.environ.get("NO_APPOINTMENTS_TEXT", "No appointments available").strip()

    if not url:
        raise RuntimeError("Add PUBLIC_STATUS_URL as a GitHub Actions Secret using the official public status-page URL.")
    if not available_text:
        raise RuntimeError("Add APPOINTMENT_AVAILABLE_TEXT as a GitHub Actions Secret: the exact official-page text that confirms appointment slots are available.")

    if not url.startswith("https://"):
        raise RuntimeError("PUBLIC_STATUS_URL must use HTTPS.")

    request = urllib.request.Request(
        url,
        headers={"User-Agent": "SpainVisaPulseBot/1.0 (public status-page checker)", "Accept": "text/html, text/plain;q=0.9"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=25) as response:
                        if response.status != 200:
                raise RuntimeError(f"Public status page returned HTTP {response.status}.")
            raw = response.read(MAX_PAGE_BYTES + 1)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Public status page returned HTTP {exc.code}; no login/CAPTCHA bypass was attempted.") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Could not reach the public status page: {exc.reason}") from exc

    if len(raw) > MAX_PAGE_BYTES:
        raise RuntimeError("Status page exceeded the 2 MB safety limit.")

    text = raw.decode("utf-8", errors="replace")
    text = re.sub(r"<script\b[^>]*>.*?</script\s*>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<style\b[^>]*>.*?</style\s*>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    lowered = text.casefold()

    # Stop when the page requires an interactive or anti-bot challenge.
    protected_markers = (
        "captcha", "verify you are human", "checking your browser",
        "access denied", "security challenge", "enable javascript to continue",
    )
    if any(marker in lowered for marker in protected_markers):
        print("Status page appears protected or challenge-gated. No attempt was made to bypass it.")
        return

    old_state = read_state()
    if no_slots_text and no_slots_text.casefold() in lowered:
        status = "not_available"
    elif available_text.casefold() in lowered:
        status = "available"
    else:
        status = "unknown"

    previous = old_state.get("status")
    if status == "available" and previous != "available":
        send_telegram_message(
            "⚠️ Spain visa appointment status may have changed. The configured availability text was found on the public page. "
            "Please open the official BLS website and confirm the details manually:\n" + url
        )
        print("Availability phrase detected; Telegram alert sent.")
    elif status == "not_available":
        print("Official no-appointments text detected. No alert sent.")
    elif status == "unknown":
        print("Configured availability phrase was not found. No availability claim made.")
    else:
        print("Availability phrase remains present; duplicate alert suppressed.")

    # Keep only status, not the page content or any credentials.
    write_state({"status": status})

if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Monitor failed: {exc}", file=sys.stderr)
        sys.exit(1)
