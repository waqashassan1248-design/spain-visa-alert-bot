# Spain Visa Pulse — public status alert bot

This repository contains:
- `main.py`: manually triggered Telegram connectivity test.
- `monitor.py`: checks a **public HTTPS status page** for an exact, user-configured availability phrase and sends a Telegram alert when the status changes to that phrase.
- `.github/workflows/appointment-monitor.yml`: scheduled GitHub Actions workflow (every 30 minutes) and manual trigger.

## Required GitHub Actions Secrets

Open **Settings → Secrets and variables → Actions → New repository secret** and add:

| Secret | Value |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Telegram bot token from BotFather |
| `TELEGRAM_CHAT_ID` | Your private Telegram chat ID |
| `PUBLIC_STATUS_URL` | Official public HTTPS page that can be checked without signing in or passing a CAPTCHA |
| `APPOINTMENT_AVAILABLE_TEXT` | Exact text on that public page that reliably means appointments are available |
| `NO_APPOINTMENTS_TEXT` | Optional; exact no-slots text. Defaults to `No appointments available` |

Do not put tokens in source code, commit messages, screenshots, or chat messages. If a bot token was exposed, revoke it with BotFather and replace the GitHub Secret.

## Start and test

1. Add the required secrets above. Do not configure the checker against a guessed URL: use the official public page you have verified.
2. Open **Actions → Test Telegram Bot → Run workflow** to test Telegram delivery.
3. Open **Actions → Public Appointment Status Monitor → Run workflow** to test the public-page checker.
4. The monitor then runs every 30 minutes. GitHub scheduled jobs can be delayed and are not guaranteed to run exactly on time.

## Important limits

- This checks only text returned by a publicly accessible HTTPS page. It does not sign in, submit forms, solve/bypass CAPTCHA, evade rate limits, or access protected appointment steps.
- The availability phrase must be configured accurately. A phrase appearing on a page is only a signal; always verify appointment details on the official BLS website.
- If BLS requires JavaScript, a login, CAPTCHA, or a protected interactive flow, this monitor reports/ends without bypassing it. A public HTML page may not expose the actual live appointment status.
- GitHub Actions cache is used to suppress repeat alerts while the same availability state remains present. Cache retention/availability is not guaranteed; duplicate alerts are possible.
