"""
This script automates updating a playlist on the ManiaPlanet website based on the lunar calendar.

It uses Selenium to perform the following actions:
1.  Logs into the website using credentials from environment variables.
2.  Calculates the current lunar day.
3.  Selects a playlist ID based on the lunar day or specific moon phases.
4.  Navigates to the playlist management page and updates the playlist.

The script is designed to be run in a containerized environment (e.g., GitHub Actions)
and includes debugging features to save screenshots and HTML source for troubleshooting.

Required Environment Variables:
-   `LOGIN` or `MANIAPLANET_LOGIN`: The username for ManiaPlanet.
-   `PASSWORD` or `MANIAPLANET_PASSWORD`: The password for ManiaPlanet.
-   `PLAYLIST_IDS`: A comma-separated list of playlist IDs to cycle through (e.g., "3045, 3029").
-   `SPECIAL_PLAYLIST`: (Optional) A playlist ID for special moon phase dates.
-   `DEFAULT_PLAYLIST`: (Optional) The default playlist ID to use when it's not a special day.

Optional Environment Variables:
-   `LOGIN_URL`: The URL for the login page (defaults to maniaplanet.com).
-   `TARGET_URL`: The URL for the playlist management page.
-   `TEST_DATE`: A date in ISO format (YYYY-MM-DD) to override the current date for testing.
-   `DRY_RUN`: If set to "1", "true", or "yes", the script will only print the selected playlist and exit.
-   `WAIT_TIMEOUT`: The timeout in seconds for Selenium waits (defaults to 30).
"""
import os
import re
import time
import math
import logging
import datetime as dt
from astral import moon as astral_moon
from typing import List, Optional, Tuple

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    # Type-only imports for linters/typecheckers (not imported at runtime)
    from selenium import webdriver  # pragma: no cover
    from selenium.webdriver.common.by import By  # pragma: no cover
    from selenium.webdriver.support.ui import WebDriverWait  # pragma: no cover
    from selenium.webdriver.support import expected_conditions as EC  # pragma: no cover
    from selenium.webdriver.support.ui import Select  # pragma: no cover
    from selenium.webdriver.chrome.options import Options  # pragma: no cover
    from selenium.webdriver.chrome.service import Service as ChromeService  # pragma: no cover


# --- Configuration from Environment Variables ---

# Credentials for ManiaPlanet login
LOGIN = os.getenv("LOGIN") or os.getenv("MANIAPLANET_LOGIN")
PASSWORD = os.getenv("PASSWORD") or os.getenv("MANIAPLANET_PASSWORD")

# URLs for login and the target playlist page
LOGIN_URL = os.getenv("LOGIN_URL", "https://www.maniaplanet.com/login")
TARGET_URL = os.getenv(
    "TARGET_URL",
    "https://www.maniaplanet.com/programs/manager/106/episodes/106/playlist",
)

# Comma-separated playlist IDs from environment, converted to a list
PLAYLIST_IDS_ENV = os.getenv("PLAYLIST_IDS", "3045, 3029")
PLAYLIST_IDS: List[str] = [x.strip() for x in PLAYLIST_IDS_ENV.split(",") if x.strip()]

# --- Optional Settings ---

# For testing: allows running the script for a specific date (YYYY-MM-DD)
TEST_DATE = os.getenv("TEST_DATE")

# If "true", "1", or "yes", the script will calculate the playlist but not perform any web actions
DRY_RUN = os.getenv("DRY_RUN", "").strip().lower() in ("1", "true", "yes")
SAVE_DEBUG = os.getenv("SAVE_DEBUG", "").strip().lower() in ("1", "true", "yes")

# Playlist IDs for special logic (e.g., moon phases)
SPECIAL_PLAYLIST = os.getenv("SPECIAL_PLAYLIST", "3045")
DEFAULT_PLAYLIST = os.getenv("DEFAULT_PLAYLIST", "3029")

# A list of common texts for save/submit buttons to improve robustness
SAVE_BUTTON_TEXTS = [
    "Submit", "Save", "Zapisz", "Set", "Apply", "Update", "Confirm", "OK",
]

# Timeout for Selenium explicit waits (in seconds)
WAIT_TIMEOUT = int(os.getenv("WAIT_TIMEOUT", "30"))

# Configure logging
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("playlist_agent")
_SENSITIVE_VALUES = [value for value in (LOGIN, PASSWORD) if value]


class RedactingFilter(logging.Filter):
    """Logging filter that redacts sensitive values from log messages and exception text.

    It replaces any literal occurrences of configured sensitive values with "[REDACTED]".
    This is best-effort: it runs on the LogRecord before formatting.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            # Get the formatted message (may use msg and args) and redact secrets
            try:
                original = record.getMessage()
            except Exception:
                # Fallback to raw msg
                original = str(record.msg)

            redacted = original
            for secret in _SENSITIVE_VALUES:
                if secret:
                    redacted = redacted.replace(secret, "[REDACTED]")

            # Overwrite the record message and clear args to avoid reformatting secrets
            record.msg = redacted
            record.args = ()

            # If exc_text exists (pre-formatted exception), redact it too
            if getattr(record, "exc_text", None):
                exc = str(record.exc_text)
                for secret in _SENSITIVE_VALUES:
                    if secret:
                        exc = exc.replace(secret, "[REDACTED]")
                record.exc_text = exc
        except Exception:
            # Do not block logging on filter errors
            pass
        return True


# Install the redacting filter on the agent logger and all existing handlers so
# redaction happens regardless of how logging is configured elsewhere.
redacting_filter = RedactingFilter()
logger.addFilter(redacting_filter)
for h in logging.root.handlers:
    h.addFilter(redacting_filter)


def _redact(message: str) -> str:
    """Redacts sensitive values from a log message.

    Args:
        message: The original log message.
    Returns:
        The redacted message.
    """
    sanitized = str(message)
    for secret in _SENSITIVE_VALUES:
        sanitized = sanitized.replace(secret, "[REDACTED]")
    return sanitized


def _log(level: int, message: str):
    """Logs a message at the specified level with redaction.

    Args:
        level: The logging level (e.g., logging.INFO).
        message: The log message.
    """
    logger.log(level, _redact(message))


def lunar_day(today_utc: Optional[dt.datetime] = None) -> int:
    """
    Calculates the day of the current lunar month (approximately 0-29).

    Args:
        today_utc: An optional datetime object to use instead of the current time.

    Returns:
        The day of the lunar month (0-29).
    """
    if today_utc is None:
        today_utc = dt.datetime.now(dt.timezone.utc)

    # astral.moon.phase returns the moon age in days (float, ~0-29.5)
    try:
        phase = astral_moon.phase(today_utc)
        day = int(math.floor(phase))
        return day % 30
    except Exception:
        # Fallback: use day of month modulo 30 if astral fails
        return today_utc.day % 30


def _is_phase_date(date_dt: dt.datetime) -> bool:
    """
    Checks if a given UTC date corresponds to a major moon phase.

    This function checks for new moon, full moon, first quarter, and last quarter.

    Args:
        date_dt: The UTC datetime to check.

    Returns:
        True if the date is a major moon phase, False otherwise.
    """
    # Use astral.moon.phase to get moon age (days). We'll treat dates close
    # to canonical phase ages (new=0, first~7, full~14, last~21) as phase dates.
    try:
        phase = astral_moon.phase(date_dt)
        # Round to nearest integer day
        rounded = int(round(phase)) % 30
        # canonical major phases
        major = {0, 7, 14, 21}
        # Tolerance (days) around the canonical value
        tol = 0.8
        if rounded in major and abs(phase - rounded) <= tol:
            return True
    except Exception:
        pass
    return False


def select_playlist_for_day(ids: List[str], day: int, date_dt: dt.datetime) -> Tuple[str, int]:
    """
    Selects a playlist ID based on the lunar day and special date rules.

    Args:
        ids: A list of available playlist IDs.
        day: The current lunar day (0-29).
        date_dt: The current UTC datetime.

    Returns:
        A tuple containing the selected playlist ID and its index or bucket.
    """
    if not ids:
        raise RuntimeError("PLAYLIST_IDS is empty. Please set the environment variable.")

    # Special logic for moon phase dates
    if SPECIAL_PLAYLIST in ids and DEFAULT_PLAYLIST in ids:
        if _is_phase_date(date_dt):
            return SPECIAL_PLAYLIST, ids.index(SPECIAL_PLAYLIST)
        else:
            return DEFAULT_PLAYLIST, ids.index(DEFAULT_PLAYLIST)

    # If there are 3 or more playlists, divide the month into three 10-day buckets
    if len(ids) >= 3:
        bucket = min(2, day // 10)
        return ids[bucket], bucket

    # Fallback for 1 or 2 playlists: cycle through them
    index = day % len(ids)
    return ids[index], index


def build_driver():
    """
    Builds and configures the Selenium Chrome WebDriver.

    Returns:
        A configured instance of the Chrome WebDriver.
    """
    _log(logging.DEBUG, "Starting Chrome driver build...")
    # Import selenium at runtime to avoid import-time dependency errors
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service as ChromeService

    options = Options()
    options.add_argument("--headless=new")  # Run in headless mode
    options.add_argument("--no-sandbox")  # Required for running as root in Docker
    options.add_argument("--disable-dev-shm-usage")  # Overcome limited resource problems
    options.add_argument("--window-size=1200,900")  # Set a reasonable window size
    chromedriver_path = os.getenv("CHROMEDRIVER")
    if chromedriver_path:
        service = ChromeService(executable_path=chromedriver_path)
        driver = webdriver.Chrome(service=service, options=options)
    else:
        driver = webdriver.Chrome(options=options)
    _log(logging.DEBUG, "Chrome driver started.")
    return driver


def save_debug(driver, name: str):
    """
    Saves the current page's HTML and a screenshot for debugging purposes.
    
    Args:
        driver: The Selenium WebDriver instance.
        name: A base name for the saved files (without extension).
    """

    if not SAVE_DEBUG:
        _log(logging.DEBUG, f"Debug capture disabled; skipping {name}")
        return
    if os.getenv("CI") or os.getenv("GITHUB_ACTIONS"):
        _log(logging.DEBUG, f"CI detected; skipping debug capture for {name}")
        return
    try:
        html = driver.page_source
        # sanitize page HTML to avoid leaking credentials or tokens
        try:
            safe_html = sanitize_html(html)
        except Exception:
            safe_html = html
        # redact any literal occurrences of credentials from environment
        try:
            redacted_login = (LOGIN or "")
            redacted_password = (PASSWORD or "")
            if redacted_login:
                safe_html = safe_html.replace(redacted_login, "[REDACTED]")
            if redacted_password:
                safe_html = safe_html.replace(redacted_password, "[REDACTED]")
        except Exception:
            pass

        with open(f"{name}.html", "w", encoding="utf-8") as f:
            f.write(safe_html)
        _log(logging.DEBUG, f"Saved {name}.html (sanitized)")
    except Exception as e:
        _log(logging.WARNING, f"Failed to save {name}.html: {e}")
    try:
        driver.save_screenshot(f"{name}.png")
        _log(logging.DEBUG, f"Saved {name}.png")
    except Exception as e:
        _log(logging.WARNING, f"Failed to save {name}.png: {e}")


def sanitize_html(html: str) -> str:
    """Return a sanitized copy of HTML with input values and common tokens removed.

    This is defensive and best-effort. It removes value attributes from <input>
    elements, strips common CSRF/meta tags, and redacts likely token-like keys
    in scripts and attributes.
    """
    try:
        # remove value="..." or value='...' for input tags (simple removal)
        html = re.sub(r"(<input\b[^>]*?)\svalue=(\".*?\"|'.*?'|[^>\s>]+)", r"\1", html, flags=re.I|re.S)

        # Remove common meta tags that may contain CSRF tokens
        html = re.sub(r"<meta[^>]+(csrf|csrf-token|csrf_param|xsrf)[^>]*>", "", html, flags=re.I|re.S)

        # Redact JS object entries like 'csrf': '...'
        html = re.sub(r"([\'\"](?:csrf|csrfToken|csrf_token|auth_token|token|password|pwd)[\'\"]\s*:\s*)([\'\"]).*?([\'\"])",
                      lambda m: m.group(1) + m.group(2) + "[REDACTED]" + m.group(3),
                      html, flags=re.I|re.S)

        # Redact Authorization headers and Bearer tokens
        html = re.sub(r"(Authorization\s*:\s*)(Bearer|Basic)\s+[^\s\"'>]+", r"\1\2 [REDACTED]", html, flags=re.I)

        # Redact JWT-like tokens (three dot separated base64-ish parts)
        html = re.sub(r"\b[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b", "[REDACTED]", html)

        # Common cookie/session/token patterns (query params, cookie-like strings)
        html = re.sub(
            r"(([?&](?:token|access_token|auth_token|session|sid|sess)[^=]*=))([^&\s\"'>#]+)",
            lambda m: m.group(1) + "[REDACTED]",
            html,
            flags=re.I,
        )

        html = re.sub(
            r"((?:session|token|auth)[^=]{0,8}=)([^;&\s]+)",
            lambda m: m.group(1) + "[REDACTED]",
            html,
            flags=re.I,
        )

        # Redact specific data-* attributes that commonly hold tokens
        html = re.sub(r"(data-(?:token|auth|session)[^=]*=[\"']).*?([\"'])", lambda m: m.group(1) + "[REDACTED]" + m.group(2), html, flags=re.I|re.S)
        return html
    except Exception:
        return html


def smart_fill_login(driver, login: str, password: str):
    """
    Intelligently finds and fills the login form.

    It tries multiple common selectors for username and password fields.

    Args:
        driver: The Selenium WebDriver instance.
        login: The username.
        password: The password.
    """
    # Import required selenium symbols at runtime
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC

    wait = WebDriverWait(driver, WAIT_TIMEOUT)
    driver.get(LOGIN_URL)
    save_debug(driver, "login_page")

    # A list of common locators for the username/login field
    login_locators = [
        (By.NAME, "_username"), (By.NAME, "username"), (By.NAME, "login"), (By.NAME, "email"),
        (By.ID, "username"), (By.ID, "login"), (By.ID, "email"),
        (By.CSS_SELECTOR, "input[type='email']"),
        (By.CSS_SELECTOR, "input[type='text']"),
    ]

    # A list of common locators for the password field
    pwd_locators = [
        (By.NAME, "_password"), (By.NAME, "password"), (By.ID, "password"),
        (By.CSS_SELECTOR, "input[type='password']"),
    ]

    # Find and fill the login field
    login_input = None
    for by, sel in login_locators:
        try:
            login_input = wait.until(EC.presence_of_element_located((by, sel)))
            if login_input.is_displayed():
                break
        except Exception:
            continue

    if not login_input:
        save_debug(driver, "login_no_input")
        raise RuntimeError("Login field not found. Update selectors in agent.py")

    login_input.clear()
    login_input.send_keys(login)

    # Find and fill the password field
    pwd_input = None
    for by, sel in pwd_locators:
        try:
            pwd_input = wait.until(EC.presence_of_element_located((by, sel)))
            if pwd_input.is_displayed():
                break
        except Exception:
            continue

    if not pwd_input:
        save_debug(driver, "login_no_password")
        raise RuntimeError("Password field not found. Update selectors in agent.py")

    pwd_input.clear()
    pwd_input.send_keys(password)

    # Find and click the submit button
    submit_button = None
    try:
        submit_button = driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
    except Exception:
        pass

    if not submit_button:
        for text in ["Zaloguj", "Log in", "Sign in", "Login"]:
            try:
                xpath = f"//button[contains(normalize-space(.), '{text}')] | //input[@type='submit' and contains(@value, '{text}')]"
                submit_button = driver.find_element(By.XPATH, xpath)
                if submit_button:
                    break
            except Exception:
                continue

    if not submit_button:
        raise RuntimeError("Login button not found. Update selectors in agent.py")

    submit_button.click()

    # Wait for the URL to change after login
    try:
        wait.until(lambda d: d.current_url != LOGIN_URL)
    except Exception:
        # If the URL doesn't change, log a warning and continue
        save_debug(driver, "after_login_no_redirect")
        _log(logging.WARNING, "No redirect detected after login; continuing to TARGET_URL")


def change_playlist(driver, playlist_id: str):
    """
    Finds the playlist selector, changes its value, and saves the change.

    Args:
        driver: The Selenium WebDriver instance.
        playlist_id: The ID of the playlist to select.
    """
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support.ui import Select

    wait = WebDriverWait(driver, WAIT_TIMEOUT)
    driver.get(TARGET_URL)
    save_debug(driver, "target_page")

    # --- Find the Playlist <select> Element ---
    target_select = None
    # Try specific ID and name selectors first
    try:
        target_select = wait.until(EC.presence_of_element_located((By.ID, "playlist_0_playlist")))
    except Exception:
        try:
            target_select = wait.until(EC.presence_of_element_located((By.NAME, "playlist_0[playlist]")))
        except Exception:
            pass

    # Fallback: scan all <select> elements on the page
    if not target_select:
        selects = driver.find_elements(By.TAG_NAME, "select")
        for s in selects:
            try:
                if s.get_attribute("disabled"):
                    continue
                # Check if the select element contains the desired playlist ID as an option
                if s.find_elements(By.CSS_SELECTOR, f"option[value='{playlist_id}']"):
                    target_select = s
                    break
            except Exception:
                continue

    if not target_select:
        save_debug(driver, "no_select")
        raise RuntimeError(f"<select> with option value={playlist_id} not found. Update selectors.")

    # --- Change the Playlist Selection ---
    try:
        Select(target_select).select_by_value(playlist_id)
    except Exception:
        # If the standard Select helper fails, try using JavaScript
        try:
            driver.execute_script("arguments[0].value = arguments[1]; arguments[0].dispatchEvent(new Event('change'));", target_select, playlist_id)
        except Exception:
            save_debug(driver, "select_set_fail")
            raise

    # --- Find and Click the Save Button ---
    save_clicked = False
    # Try specific selectors first
    try:
        btn = driver.find_element(By.ID, "playlist_0_submit")
        if btn.is_enabled():
            btn.click()
            save_clicked = True
    except Exception:
        pass

    if not save_clicked:
        try:
            btn = driver.find_element(By.NAME, "playlist_0[submit]")
            if btn.is_enabled():
                btn.click()
                save_clicked = True
        except Exception:
            pass

    # Fallback: try a generic submit button
    if not save_clicked:
        try:
            btn = driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
            if btn.is_enabled():
                btn.click()
                save_clicked = True
        except Exception:
            pass

    # Final fallback: search for buttons by text content
    if not save_clicked:
        for text in SAVE_BUTTON_TEXTS:
            try:
                xpath = f"//button[contains(normalize-space(.), '{text}')] | //input[@type='submit' and contains(@value,'{text}')]"
                btns = driver.find_elements(By.XPATH, xpath)
                for b in btns:
                    if b.is_displayed() and b.is_enabled():
                        b.click()
                        save_clicked = True
                        break
                if save_clicked:
                    break
            except Exception:
                continue

    # Give the site a moment to process the change
    time.sleep(3)
    save_debug(driver, "after_change")


def main():
    """
    Main execution function for the script.
    """
    if not DRY_RUN and (not LOGIN or not PASSWORD):
        raise RuntimeError("LOGIN/PASSWORD missing from environment variables.")

    # Determine the date to use (either from TEST_DATE or current UTC time)
    if TEST_DATE:
        try:
            date_dt = dt.datetime.fromisoformat(TEST_DATE.replace('Z', '+00:00'))
        except ValueError:
            date_dt = dt.datetime.strptime(TEST_DATE, '%Y-%m-%d')
        day = lunar_day(date_dt)
        _log(logging.DEBUG, f"Using TEST_DATE={TEST_DATE} -> lunar day={day}")
    else:
        date_dt = dt.datetime.now(dt.timezone.utc)
        day = lunar_day(date_dt)

    # Select the playlist for the determined date
    playlist_id, bucket = select_playlist_for_day(PLAYLIST_IDS, day, date_dt)
    _log(logging.INFO, f"Selected playlist_id (lunar calendar): {playlist_id} (bucket={bucket}, day={day})")
    if DRY_RUN:
        _log(logging.INFO, "DRY RUN enabled, skipping Selenium.")
        return

    # --- Run Selenium Automation ---
    driver = None
    try:
        driver = build_driver()
        _log(logging.INFO, "Logging in…")
        smart_fill_login(driver, LOGIN, PASSWORD)
        _log(logging.INFO, "Changing playlist…")
        change_playlist(driver, playlist_id)
        _log(logging.INFO, "Done.")
    finally:
        if driver:
            driver.quit()


if __name__ == "__main__":
    main()
