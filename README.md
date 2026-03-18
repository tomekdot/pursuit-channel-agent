# 🌙 ManiaPlanet Playlist Agent

Automated agent that logs into ManiaPlanet and sets a playlist based on lunar calendar. Uses `skyfield` for precise moon phase calculations and `Selenium` for web automation.

Runs daily at 08:00 UTC via GitHub Actions.

## ✨ Features

- 🌗 Playlist selection based on lunar phases (New Moon, Full Moon, Quarters)
- 🖥️ Headless Chrome via Selenium
- ⚙️ Configurable via environment variables
- 🔒 Automatic credential redaction in logs

## 🚀 Quick Start

1. Fork this repository
2. Add secrets (Settings → Secrets → Actions):
   - `MANIAPLANET_LOGIN` – your login
   - `MANIAPLANET_PASSWORD` – your password

3. (Optional) Configure variables:
   - `TARGET_URL` – playlist page URL
   - `LOGIN_URL` – login page URL  
   - `PLAYLIST_IDS` – comma-separated IDs (e.g. `3045, 3029`)
   - `SPECIAL_PLAYLIST` / `DEFAULT_PLAYLIST`

4. Run workflow manually or wait for scheduled run

## 🧰 Local Development

**Requirements:** Python 3.14+

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

**Dry run (no browser):**
```powershell
$env:DRY_RUN="1"
python agent.py
```

**Full run:**
```powershell
$env:MANIAPLANET_LOGIN="your_login"
$env:MANIAPLANET_PASSWORD="your_password"
python agent.py
```

## ⚙️ Configuration

| Variable | Description |
|----------|-------------|
| `PLAYLIST_IDS` | Comma-separated playlist IDs |
| `TARGET_URL` | Playlist management page |
| `LOGIN_URL` | Login page URL |
| `WAIT_TIMEOUT` | Selenium wait timeout (default: 30s) |
| `TEST_DATE` | Override date for testing (YYYY-MM-DD) |

## 🔧 Chromedriver Provisioning

Manual workflow (`.github/workflows/chromedriver-provision.yml`) to download and cache Chromedriver.

**Variables:**
- `CHROMEDRIVER_URL` – download URL for chromedriver archive
- `CHROMEDRIVER_SHA256` – (optional) checksum for verification

## 🔒 Security

Credentials stored in GitHub Secrets only. Logs are automatically redacted.

## 👤 Contact

- **Author:** `tomekdot`
- **Team:** `vitalism-creative`
- **Discord:** `@tomekdot`

## 📝 License

MIT License. See [LICENSE](LICENSE) for details.
