
import os
import json
import urllib.request
import urllib.error

def send_telegram_message(message):
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = json.dumps({
        "chat_id": chat_id,
        "text": message
    }).encode("utf-8")

    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST"
    )

    with urllib.request.urlopen(request, timeout=20) as response:
        result = json.loads(response.read().decode("utf-8"))

    if not result.get("ok"):
        raise RuntimeError("Telegram rejected the message")

    print("Telegram test message sent successfully.")

if __name__ == "__main__":
    send_telegram_message(
        "SpainVisaPulseBot is connected! Python test successful."
    )

