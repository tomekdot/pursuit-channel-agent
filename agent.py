import os
import time
import datetime as dt
from typing import List, Optional, Tuple

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.service import Service as ChromeService
import ephem
import traceback


LOGIN = os.getenv("LOGIN") or os.getenv("MANIAPLANET_LOGIN")
PASSWORD = os.getenv("PASSWORD") or os.getenv("MANIAPLANET_PASSWORD")
LOGIN_URL = os.getenv("LOGIN_URL", "https://www.maniaplanet.com/login")
TARGET_URL = os.getenv(
    "TARGET_URL",
    "https://www.maniaplanet.com/programs/manager/106/episodes/106/playlist",
)
PLAYLIST_IDS_ENV = os.getenv("PLAYLIST_IDS", "3045, 3029")
PLAYLIST_IDS: List[str] = [x.strip() for x in PLAYLIST_IDS_ENV.split(",") if x.strip()]

TEST_DATE = os.getenv("TEST_DATE")  
DRY_RUN = os.getenv("DRY_RUN", "").strip().lower() in ("1", "true", "yes")
SPECIAL_PLAYLIST = os.getenv("SPECIAL_PLAYLIST", "3045")
DEFAULT_PLAYLIST = os.getenv("DEFAULT_PLAYLIST", "3029")

SAVE_BUTTON_TEXTS = [
    "Submit"
    "Save", "Zapisz", "Set", "Apply", "Update", "Confirm", "OK",
]

# wait timeout for Selenium explicit waits (seconds)
WAIT_TIMEOUT = int(os.getenv("WAIT_TIMEOUT", "30"))


def lunar_day(today_utc: Optional[dt.datetime] = None) -> int:
    if today_utc is None:
        today_utc = dt.datetime.utcnow()
    prev_new_moon = ephem.previous_new_moon(today_utc)
    prev_dt = prev_new_moon.datetime()  # UTC
    age = today_utc - prev_dt
    day = int(age.total_seconds() // 86400)  
    return day % 30


def pick_playlist_id(ids: List[str]) -> str:
    if not ids:
        raise RuntimeError("PLAYLIST_IDS is empty – set environment variable or update code.")

    day = lunar_day()

    if len(ids) >= 3:
        bucket = min(2, day // 10)
        return ids[bucket]

    index = day % len(ids)
    return ids[index]


def _is_phase_date(date_dt: dt.datetime) -> bool:
    """Return True if date_dt (UTC) matches any main moon phase moment (new, full, first/third quarter).
    We try ephem.previous_* and ephem.next_* variants for each phase name and compare dates.
    """
    funcs = []
    funcs += [ephem.previous_new_moon, ephem.next_new_moon, ephem.previous_full_moon, ephem.next_full_moon]
    if hasattr(ephem, 'previous_first_quarter_moon'):
        funcs += [ephem.previous_first_quarter_moon, ephem.next_first_quarter_moon]
    if hasattr(ephem, 'previous_last_quarter_moon'):
        funcs += [ephem.previous_last_quarter_moon, ephem.next_last_quarter_moon]

    for fn in funcs:
        try:
            t = fn(date_dt)
            if not t:
                continue
            try:
                t_dt = t.datetime()
            except Exception:
                t_dt = t
            if t_dt.date() == date_dt.date():
                return True
        except Exception:
            continue
    return False


def select_playlist_for_day(ids: List[str], day: int, date_dt: dt.datetime) -> Tuple[str, int]:
    """Return (playlist_id, bucket_index) for a given lunar day.
    bucket_index: 0/1/2 for three-bucket mode, or selection index for fallback.
    """
    if not ids:
        raise RuntimeError("PLAYLIST_IDS is empty – set environment variable or update code.")

    if SPECIAL_PLAYLIST in ids and DEFAULT_PLAYLIST in ids:
        if _is_phase_date(date_dt):
            return SPECIAL_PLAYLIST, ids.index(SPECIAL_PLAYLIST)
        else:
            return DEFAULT_PLAYLIST, ids.index(DEFAULT_PLAYLIST)

    if len(ids) >= 3:
        bucket = min(2, day // 10)
        return ids[bucket], bucket

    index = day % len(ids)
    return ids[index], index


def build_driver() -> webdriver.Chrome:
    print("[DEBUG] Starting Chrome driver build...", flush=True)
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1200,900")
    service = ChromeService(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    print("[DEBUG] Chrome driver started.", flush=True)
    return driver


def save_debug(driver: webdriver.Chrome, name: str):
    """Save page source and screenshot to working directory for debugging in Actions."""
    try:
        html = driver.page_source
        with open(f"{name}.html", "w", encoding="utf-8") as f:
            f.write(html)
        print(f"[DEBUG] Saved {name}.html", flush=True)
    except Exception as e:
        print(f"[DEBUG] Failed to save {name}.html: {e}", flush=True)
    try:
        driver.save_screenshot(f"{name}.png")
        print(f"[DEBUG] Saved {name}.png", flush=True)
    except Exception as e:
        print(f"[DEBUG] Failed to save {name}.png: {e}", flush=True)


def smart_fill_login(driver: webdriver.Chrome, login: str, password: str):
    wait = WebDriverWait(driver, WAIT_TIMEOUT)
    driver.get(LOGIN_URL)

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

    submit = None
    try:
        submit = driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
    except Exception:
        pass
    if not submit:
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

    # wait up to WAIT_TIMEOUT for redirect or URL change
    wait.until(lambda d: d.current_url != LOGIN_URL)


def change_playlist(driver: webdriver.Chrome, playlist_id: str):
    wait = WebDriverWait(driver, WAIT_TIMEOUT)
    driver.get(TARGET_URL)

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

    save_clicked = False
    try:
        btn = driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
        if btn.is_enabled():
            btn.click(); save_clicked = True
    except Exception:
        pass

    if not save_clicked:
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

    time.sleep(3)


def main():
    if not DRY_RUN and (not LOGIN or not PASSWORD):
        raise RuntimeError("LOGIN/PASSWORD missing from environment variables.")

    if TEST_DATE:
        try:
            if 'T' in TEST_DATE:
                dtobj = dt.datetime.fromisoformat(TEST_DATE)
            else:
                dtobj = dt.datetime.fromisoformat(TEST_DATE + 'T00:00:00')
            day = lunar_day(dtobj)
            print(f"[DEBUG] Using TEST_DATE={TEST_DATE} -> lunar day={day}")
        except Exception as e:
            raise RuntimeError(f"Invalid TEST_DATE format: {e}")
    else:
        day = lunar_day()

    if TEST_DATE:
        date_dt = dtobj
    else:
        date_dt = dt.datetime.utcnow()

    playlist_id, bucket = select_playlist_for_day(PLAYLIST_IDS, day, date_dt)
    print(f"[INFO] Selected playlist_id (lunar calendar): {playlist_id} (bucket={bucket}, day={day})")

    if DRY_RUN:
        print("[DRY RUN] Exiting without running Selenium.")
        return

    driver = build_driver()
    try:
        print("[INFO] Logging in…")
        smart_fill_login(driver, LOGIN, PASSWORD)
        print("[INFO] Changing playlist…")
        change_playlist(driver, playlist_id)
        print("[OK] Done.")
    finally:
        try:
            driver.quit()
        except Exception:
            pass


if __name__ == "__main__":
    main()
