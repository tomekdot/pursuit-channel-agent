# 🌙 Maniaplanet Playlist Agent

Automatic agent that logs into Maniaplanet and sets a playlist on a schedule. The agent selects playlists using a lunar-calendar rule (lunar day 0–29) and automates the web UI using Selenium. The project now uses the `astral` library for lunar calculations (replacing `ephem`) so it doesn't require compiling C extensions.

This repository contains a small, self-contained Python agent and a GitHub Actions workflow to run it on a schedule (default: daily 08:00 UTC). The code is structured so it can be imported for testing without installing Selenium (Selenium imports are performed at runtime inside functions).

## ✨ Features
 - 🌗 Choose a playlist based on lunar day (0–29) using `astral.moon.phase`.
 - 🖥️ Headless Chrome via Selenium (works on GitHub Actions runner).
 - ⚙️ Configurable playlist IDs and target/login URLs via environment variables.
 - 🐞 Debug artifacts (sanitized HTML + screenshots) are saved on failure to help tune selectors.

## 🚀 Quick start

1. Fork or create a repository and push these files (`agent.py`, `requirements.txt`, `.github/workflows/playlist-agent.yml`, `README.md`).
2. 🔐 Add repository secrets (Settings → Secrets and variables → Actions → *New repository secret*):
   - `MANIAPLANET_LOGIN` – your Maniaplanet login or email
   - `MANIAPLANET_PASSWORD` – your password

3. (Optional) Add repository variables or override via Actions/environment:
   - `TARGET_URL` (default: `https://www.maniaplanet.com/programs/manager/106/episodes/106/playlist`)
   - `LOGIN_URL` (default: `https://www.maniaplanet.com/login`)
   - `PLAYLIST_IDS` (comma-separated, e.g. `3029,3045`)
   - `SPECIAL_PLAYLIST` / `DEFAULT_PLAYLIST` (alternate override values)

4. Use the workflow `Run workflow` in Actions to test, or wait for the scheduled run (default: 08:00 UTC daily).

## 🧰 Running locally

Recommended Python: 3.11 (the GitHub Actions workflow uses 3.11 and prebuilt wheels are available for dependencies).

Create and activate a virtual environment and install dependencies:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Dry-run (no browser):

```powershell
$env:DRY_RUN="1"
$env:TEST_DATE="2025-08-31"   # optional, forces a given date to test selection
python .\agent.py
```

Full run (will open headless Chrome):

```powershell
$env:MANIAPLANET_LOGIN="your_login"
$env:MANIAPLANET_PASSWORD="your_password"
Remove-Item Env:DRY_RUN -ErrorAction SilentlyContinue
python .\agent.py
```

Notes:
- The agent performs Selenium imports at runtime inside the functions that need them. This makes the module importable for tests even when Selenium isn't installed.
- You still need Chrome (or Chromium) available for full runs; the workflow installs Chrome in CI. Locally you can install Chrome and ensure the chromedriver matches your browser version, or set the `CHROMEDRIVER` environment variable to a driver binary.
- Debug HTML is sanitized before saving; logs are redacted of configured secrets.

## ⚙️ Configuration
- `PLAYLIST_IDS` — comma-separated playlist ids (order used by lunar mapping). Example: `3045,3029`.
- `TARGET_URL` — playlist management page (default in repo). Change if your manager uses a different URL.
- `LOGIN_URL` — login page URL.
- `WAIT_TIMEOUT` — seconds to wait for elements (defaults in workflow to 60).
- `SAVE_DEBUG` — set to `1` to enable sanitized HTML/screenshot capture locally; ignored on CI by default.

Secrets are used for credentials only; never commit them.

## How it works (brief)
 - Computes lunar day (0–29) using `astral.moon.phase`.
- Chooses a playlist id and starts a Selenium WebDriver (headless Chrome).
- Logs in (robust selectors) and navigates to `TARGET_URL`, selects the playlist `<select>` and submits the form.

If the site requires extra confirmation steps or introduces CAPTCHA, the run will fail and debug artifacts will be produced to help fix selectors.

## 🐛 Debugging
- 🔍 After a workflow run, check `Actions` → job logs. The action uploads `agent.log` and debug files (`*.html`, `*.png`) when available.
- 🗂️ Local debug: the agent can save `login_page.html`, `target_page.html`, `after_change.html` and screenshots in the working directory when issues occur.

## 🤝 Contributing
- 🐞 Open issues for selector updates, schedule changes, or feature requests.
- 📦 Pull requests welcome; keep changes small and include tests if possible.

## 🔒 Security & Privacy
- Store credentials in GitHub Secrets only. Do not expose your password or saved HTML screenshots containing sensitive tokens.
 - Store credentials in GitHub Secrets only. Do not expose your password or saved HTML screenshots containing sensitive tokens. The agent redacts configured secrets from logs and sanitizes saved HTML, but sanitization is best-effort; avoid storing long-lived credentials in places that may be publicly accessible.

## 📝 License
- MIT
