# Maniaplanet Web Agent – automatic playlist change (08:00 UTC, lunar calendar)

This agent logs into Maniaplanet and selects a playlist based on the **lunar month day (0–29)**.

## How to run (step by step)

1. **Create a repository** on GitHub and upload files:
   - `agent.py`
   - `requirements.txt`
   - `.github/workflows/playlist-agent.yml`
   - `README.md`

2. **Add repository secrets** (Settings → Secrets and variables → Actions → *New repository secret*):
   - `MANIAPLANET_LOGIN` – Your Maniaplanet login/email
   - `MANIAPLANET_PASSWORD` – Your password

3. (Optional) **Add repository variables** (Settings → Secrets and variables → *Variables*):
   - `TARGET_URL` – if different from default `https://www.maniaplanet.com/programs/manager/106/episodes/106/playlist`
   - `LOGIN_URL` – if different from default `https://www.maniaplanet.com/login`
   - `PLAYLIST_IDS` – e.g. `3045,3029,9999`

4. **Enable Actions tab** (may require confirmation).

5. **Wait for schedule** – workflow will run daily at **08:00 UTC**. You can also use **Run workflow** button (workflow_dispatch) for testing.

## How it works
- Script calculates current **lunar day** (0–29) relative to previous new moon and selects index in `PLAYLIST_IDS`.
- Uses **Selenium (headless Chrome)**, logs in and sets `<select>` to value `value=<playlist_id>`.
- Tries to click save button (`button[type=submit]` or buttons with text: `Save`, `Zapisz`, `Set`, `Apply`, `Update`).

## Selector customization
If login or save don't hit the selectors:
- Change selector lists in `smart_fill_login()` and `change_playlist()` – enter correct `name/id/xpath` from DevTools.

## CAPTCHA
If the site adds CAPTCHA on login, the agent will stop – in this case GitHub Actions will end the job with an error.

## Debugging
- Go to **Actions → Job → Run agent** tab and check `print()` logs.
- You can temporarily add HTML dumps to artifacts, e.g. save `driver.page_source` and attach file (advanced, optional).

## Security
- Keep login/password only in **Secrets**.

## Time zones
- CRON in GitHub Actions works in UTC. Schedule `0 8 * * *` = 08:00 UTC.
