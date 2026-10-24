from collections import Counter
import json
import os
from pathlib import Path
import re
import sys
import time
import urllib.error
import urllib.request

# Computer Vision & OCR libraries for Captcha
import cv2
import easyocr
import numpy as np
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

MAX_PAGE_BYTES = 2_000_000
STATE_PATH = Path(os.environ.get("MONITOR_STATE_FILE", ".monitor-state/state.json"))

# Initialize EasyOCR reader (optimized for digits)
print("[*] Initializing EasyOCR reader...")
ocr_reader = easyocr.Reader(["en"], gpu=False)


def send_telegram_message(message):
  token = os.environ.get("TELEGRAM_BOT_TOKEN")
  chat_id = os.environ.get("TELEGRAM_CHAT_ID")
  if not token or not chat_id:
    raise RuntimeError(
        "Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID GitHub Secret."
    )

  url = f"https://api.telegram.org/bot{token}/sendMessage"
  body = json.dumps({
      "chat_id": chat_id,
      "text": message,
      "disable_web_page_preview": True,
  }).encode("utf-8")
  request = urllib.request.Request(
      url, data=body, headers={"Content-Type": "application/json"}, method="POST"
  )
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


def solve_numeric_captcha(captcha_element):
  """Captcha element se screenshot bytes leta hai, OCR se numbers read karta hai,

  aur check karta hai ke koi number minimum 3 baar repeat ho raha hai ya nahi.
  """
  try:
    # 1. Capture screenshot bytes of the captcha image
    captcha_bytes = captcha_element.screenshot_as_png

    # 2. Convert bytes to OpenCV image format
    nparr = np.frombuffer(captcha_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # 3. Read text using EasyOCR (allowlist restricted to digits)
    results = ocr_reader.readtext(gray, allowlist="0123456789")
    extracted_text = "".join([res[1] for res in results])
    print(f"[+] Extracted Captcha Digits: {extracted_text}")

    # 4. Logic: Minimum 3 numbers same match hone chahiye
    counts = Counter(extracted_text)
    matched_numbers = [digit for digit, count in counts.items() if count >= 3]

    if matched_numbers:
      print(f"[✔] Match Found! Numbers appearing 3+ times: {matched_numbers}")
      # Jo number repeat ho raha hai, usko return karein
      return matched_numbers[0]
    else:
      print("[✖] No number found repeating 3 or more times.")
      return None
  except Exception as e:
    print(f"[!] Error in captcha solver: {e}")
    return None


def main():
  url = os.environ.get("PUBLIC_STATUS_URL", "").strip()
  available_text = os.environ.get("APPOINTMENT_AVAILABLE_TEXT", "").strip()
  no_slots_text = os.environ.get(
      "NO_APPOINTMENTS_TEXT", "No appointments available"
  ).strip()

  if not url:
    raise RuntimeError("Add PUBLIC_STATUS_URL as a GitHub Actions Secret.")
  if not available_text:
    raise RuntimeError("Add APPOINTMENT_AVAILABLE_TEXT as a GitHub Secret.")
  if not url.startswith("https://"):
    raise RuntimeError("PUBLIC_STATUS_URL must use HTTPS.")

  # Setup Headless Chrome for GitHub Actions
  print("[*] Launching headless browser...")
  chrome_options = Options()
  chrome_options.add_argument("--headless")
  chrome_options.add_argument("--no-sandbox")
  chrome_options.add_argument("--disable-dev-shm-usage")
  chrome_options.add_argument("--disable-gpu")
  chrome_options.add_argument("--window-size=1920,1080")

  driver = webdriver.Chrome(options=chrome_options)

  try:
    driver.get(url)
    time.sleep(5)  # Page load hone ka wait

    # --- CAPTCHA SOLVER INTEGRATION ---
    try:
      # BLS captcha image aur input ke flexible XPaths
      captcha_img = WebDriverWait(driver, 10).until(
          EC.presence_of_element_located(
              (By.XPATH, "//img[contains(@id, 'Captcha') or contains(@src, 'Captcha')]")
          )
      )

      solution = solve_numeric_captcha(captcha_img)

      if solution:
        # Captcha input field mein solution enter karein
        captcha_input = driver.find_element(
            By.XPATH, "//input[contains(@id, 'Captcha') or contains(@name, 'Captcha')]"
        )
        captcha_input.clear()
        captcha_input.send_keys(solution)
        print(f"[✔] Successfully entered captcha solution: {solution}")
        
        # Thoda wait taake form process ho sake
        time.sleep(3)
    except Exception as captcha_err:
      print(f"[!] Captcha element not found or skipped: {captcha_err}")

    # Page ka final source code read karein availability check karne ke liye
    page_source = driver.page_source
    if len(page_source.encode("utf-8")) > MAX_PAGE_BYTES:
      raise RuntimeError("Status page exceeded the 2 MB safety limit.")

    text = re.sub(r"<script\b[^>]*>.*?</script\s*>", " ", page_source, flags=I | S if 'I' in globals() else re.I | re.S)
    text = re.sub(r"<style\b[^>]*>.*?</style\s*>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    lowered = text.casefold()

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
          "⚠️ Spain visa appointment status may have changed. The configured"
          " availability text was found on the page. Please open the official"
          " website and confirm:\n"
          + url
      )
      print("Availability phrase detected; Telegram alert sent.")
    elif status == "not_available":
      print("Official no-appointments text detected. No alert sent.")
    elif status == "unknown":
      print("Configured availability phrase was not found.")
    else:
      print("Availability status unchanged.")

    write_state({"status": status})

  finally:
    driver.quit()


if __name__ == "__main__":
  try:
    main()
  except Exception as exc:
    print(f"Monitor failed: {exc}", file=sys.stderr)
    sys.exit(1)
