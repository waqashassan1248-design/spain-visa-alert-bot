import json
import os
import sys
import urllib.error
import urllib.request


def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

    if not token or not chat_id:
        raise RuntimeError(
            "Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID GitHub Actions secret."
        )

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": "✅ Telegram bot test successful. Your GitHub Actions connection is working.",
        "disable_web_page_preview": True,
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        # Do not print the request URL because it contains the bot token.
        raise RuntimeError(f"Telegram API returned HTTP {exc.code}. Check the bot token and chat ID secrets.") from None
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Could not reach Telegram API: {exc.reason}") from None

    if not result.get("ok"):
        raise RuntimeError("Telegram API did not accept the test message. Check TELEGRAM_CHAT_ID and bot access.")

    print("Telegram test message sent successfully.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Telegram test failed: {exc}", file=sys.stderr)
        sys.exit(1)
