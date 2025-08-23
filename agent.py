import os
import time
import datetime as dt
from typing import List

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.service import Service as ChromeService
import ephem

# -----------------------------
# Configuration from ENV
# -----------------------------
LOGIN = os.getenv("LOGIN") or os.getenv("MANIAPLANET_LOGIN")
PASSWORD = os.getenv("PASSWORD") or os.getenv("MANIAPLANET_PASSWORD")
LOGIN_URL = os.getenv("LOGIN_URL", "https://www.maniaplanet.com/login")
TARGET_URL = os.getenv(
    "TARGET_URL",
    "https://www.maniaplanet.com/programs/manager/106/episodes/106/playlist",
)
# List of playlist IDs as CSV in ENV or fallback to example
PLAYLIST_IDS_ENV = os.getenv("PLAYLIST_IDS", "3045,3029")
PLAYLIST_IDS: List[str] = [x.strip() for x in PLAYLIST_IDS_ENV.split(",") if x.strip()]

SAVE_BUTTON_TEXTS = [
    "Save", "Zapisz", "Set", "Apply", "Update", "Confirm", "OK",
]

# -----------------------------
# Helper: calculate "lunar day" (0–29)
# -----------------------------

def lunar_day(today_utc: dt.datetime | None = None) -> int:
    if today_utc is None:
        today_utc = dt.datetime.utcnow()
    # find previous new moon and count how many days have passed
    prev_new_moon = ephem.previous_new_moon(today_utc)
    prev_dt = prev_new_moon.datetime()  # UTC
    age = today_utc - prev_dt
    day = int(age.total_seconds() // 86400)  # full days since new moon
    return day % 30


def pick_playlist_id(ids: List[str]) -> str:
    if not ids:
        raise RuntimeError("PLAYLIST_IDS is empty – set environment variable or update code.")
    day = lunar_day()
    index = day % len(ids)
    return ids[index]


# -----------------------------
# Selenium: login and playlist change
# -----------------------------

def build_driver() -> webdriver.Chrome:
    options = Options()
    # Headless "new" for stability on GitHub Actions
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1200,900")
    # Use installed Chrome (setup in workflow) + webdriver-manager
    service = ChromeService(ChromeDriverManager().install())
    return webdriver.Chrome(service=service, options=options)


def smart_fill_login(driver: webdriver.Chrome, login: str, password: str):
    wait = WebDriverWait(driver, 20)
    driver.get(LOGIN_URL)

    # potential login fields
    login_locators = [
        (By.NAME, "username"), (By.NAME, "login"), (By.NAME, "email"),
        (By.ID, "username"), (By.ID, "login"), (By.ID, "email"),
        (By.CSS_SELECTOR, "input[type='email']"),
        (By.CSS_SELECTOR, "input[type='text']"),
    ]
    pwd_locators = [
        (By.NAME, "password"), (By.ID, "password"),
        (By.CSS_SELECTOR, "input[type='password']"),
    ]

    # Find login field
    login_input = None
    for by, sel in login_locators:
        try:
            login_input = wait.until(EC.presence_of_element_located((by, sel)))
            if login_input.is_displayed():
                break
        except Exception:
            continue
    if not login_input:
        raise RuntimeError("Login field not found – update selectors in agent.py")
    login_input.clear(); login_input.send_keys(login)

    # Find password field
    pwd_input = None
    for by, sel in pwd_locators:
        try:
            pwd_input = wait.until(EC.presence_of_element_located((by, sel)))
            if pwd_input.is_displayed():
                break
        except Exception:
            continue
    if not pwd_input:
        raise RuntimeError("Password field not found – update selectors in agent.py")
    pwd_input.clear(); pwd_input.send_keys(password)

    # "Login" button
    # first try <button type=submit>
    submit = None
    try:
        submit = driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
    except Exception:
        pass
    if not submit:
        # or button by text
        for text in ["Zaloguj", "Log in", "Sign in", "Login"]:
            try:
                submit = driver.find_element(By.XPATH, f"//button[contains(normalize-space(.), '{text}')]|\n                                                    //input[@type='submit' and contains(@value, '{text}')]")
                if submit:
                    break
            except Exception:
                continue
    if not submit:
        raise RuntimeError("Login button not found – update selectors in agent.py")

    submit.click()

    # Wait until login succeeds (presence of link/profile or redirect)
    wait.until(lambda d: d.current_url != LOGIN_URL)


def change_playlist(driver: webdriver.Chrome, playlist_id: str):
    wait = WebDriverWait(driver, 20)
    driver.get(TARGET_URL)

    # Find <select> that contains our option value=playlist_id
    selects = driver.find_elements(By.TAG_NAME, "select")
    target_select = None
    for s in selects:
        try:
            if s.get_attribute("disabled"):
                continue
            options = s.find_elements(By.TAG_NAME, "option")
            if any(o.get_attribute("value") == playlist_id for o in options):
                target_select = s
                break
        except Exception:
            continue

    if not target_select:
        raise RuntimeError(f"<select> with option value={playlist_id} not found. Update selectors.")

    Select(target_select).select_by_value(playlist_id)

    # Try to click save/accept button
    # first button[type=submit]
    save_clicked = False
    try:
        btn = driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
        if btn.is_enabled():
            btn.click(); save_clicked = True
    except Exception:
        pass

    if not save_clicked:
        # by text
        for text in SAVE_BUTTON_TEXTS:
            try:
                xpath = f"//button[contains(normalize-space(.), '{text}')] | //input[@type='submit' and contains(@value,'{text}')]"
                btns = driver.find_elements(By.XPATH, xpath)
                for b in btns:
                    if b.is_displayed() and b.is_enabled():
                        b.click(); save_clicked = True; break
                if save_clicked:
                    break
            except Exception:
                continue

    # Give the page time to save
    time.sleep(3)


def main():
    if not LOGIN or not PASSWORD:
        raise RuntimeError("LOGIN/PASSWORD missing from environment variables.")

    playlist_id = pick_playlist_id(PLAYLIST_IDS)
    print(f"[INFO] Selected playlist_id (lunar calendar): {playlist_id}")

    driver = build_driver()
    try:
        print("[INFO] Logging in…")
        smart_fill_login(driver, LOGIN, PASSWORD)
        print("[INFO] Changing playlist…")
        change_playlist(driver, playlist_id)
        print("[OK] Done.")
    finally:
        driver.quit()


if __name__ == "__main__":
    main()
