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
-   `NAV_RETRY_ATTEMPTS`: Number of retries for transient page-load/navigation failures (default 3).
-   `NAV_RETRY_BASE_DELAY`: Base delay in seconds for navigation retry backoff (default 2).
-   `SANITIZE_STRIP_SCRIPTS`: If "1"/"true"/"yes" (default), strips <script> bodies from saved debug HTML.

Notes on login-attempt safety:
-   Credential submission (smart_fill_login) is intentionally NOT retried within a run.
    Repeatedly resubmitting a login form is what triggers account lockouts / rate limits
    on most sites. If login fails, the script logs a clear error and exits rather than
    hammering the login endpoint again. Only idempotent, read-only navigation (page loads,
    waiting for elements) is retried with exponential backoff + jitter.
"""

__version__ = "1.1.0"
__author__ = "tomekdot"
__description__ = "Automated ManiaPlanet playlist updater based on lunar phases."

import logging
import math
import os
import random
import re
import sys
import time
from typing import Callable, List, Optional, Tuple, TypeVar
from urllib.parse import urlparse

import datetime as dt
from astral import moon as astral_moon

# Lazy imports (imported at runtime only when needed)
# - selenium modules are imported in build_driver() and other functions
# - skyfield modules are imported in _get_moon_phase_dates_for_month()

T = TypeVar("T")

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

ALLOWED_HOST_SUFFIXES = tuple(
    suffix.strip().lower().lstrip(".")
    for suffix in os.getenv("ALLOWED_HOST_SUFFIXES", "maniaplanet.com").split(",")
    if suffix.strip()
)

# Comma-separated playlist IDs from environment, converted to a list.
PLAYLIST_IDS_ENV = os.getenv("PLAYLIST_IDS", "3045, 3029")
PLAYLIST_IDS: List[str] = [
    x.strip()
    for x in PLAYLIST_IDS_ENV.split(",")
    if x.strip()
]

# --- Optional Settings ---

# For testing: allows running the script for a specific date (YYYY-MM-DD)
TEST_DATE = os.getenv("TEST_DATE")

# If "true", "1", or "yes", the script will calculate the playlist but not perform any web actions
DRY_RUN = os.getenv("DRY_RUN", "").strip().lower() in ("1", "true", "yes")
SAVE_DEBUG = os.getenv("SAVE_DEBUG", "").strip().lower() in ("1", "true", "yes")

# Allow enabling debug explicitly only for local runs when explicitly allowed.
# This prevents accidentally enabling SAVE_DEBUG in CI and leaking artifacts.
ALLOW_LOCAL_DEBUG = os.getenv("ALLOW_LOCAL_DEBUG", "").strip().lower() in ("1", "true", "yes")

# Whether to strip <script>...</script> bodies from saved debug HTML (default: yes).
SANITIZE_STRIP_SCRIPTS = os.getenv("SANITIZE_STRIP_SCRIPTS", "1").strip().lower() in ("1", "true", "yes")

# Playlist IDs for special logic (e.g., moon phases)
SPECIAL_PLAYLIST = os.getenv("SPECIAL_PLAYLIST", "3045")
DEFAULT_PLAYLIST = os.getenv("DEFAULT_PLAYLIST", "3029")

# A list of common texts for save/submit buttons to improve robustness
SAVE_BUTTON_TEXTS = [
    "Submit", "Save", "Zapisz", "Set", "Apply", "Update", "Confirm", "OK",
]

# Timeout for Selenium explicit waits (in seconds)
WAIT_TIMEOUT = int(os.getenv("WAIT_TIMEOUT", "30"))

# Retry/backoff settings for transient, idempotent navigation operations only.
# NOTE: this must NEVER be applied to credential submission (see module docstring).
NAV_RETRY_ATTEMPTS = max(1, int(os.getenv("NAV_RETRY_ATTEMPTS", "3")))
NAV_RETRY_BASE_DELAY = float(os.getenv("NAV_RETRY_BASE_DELAY", "2"))

# Configure logging
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("playlist_agent")
_SENSITIVE_VALUES = [value for value in (LOGIN, PASSWORD) if value]

# Enforce safe defaults: do not allow SAVE_DEBUG in CI unless explicitly allowed
if (os.getenv("CI") or os.getenv("GITHUB_ACTIONS")) and SAVE_DEBUG and not ALLOW_LOCAL_DEBUG:
    # Fail fast to avoid accidentally saving debug artifacts in CI
    raise RuntimeError("SAVE_DEBUG is not allowed in CI environments. To override (not recommended), set ALLOW_LOCAL_DEBUG=1 locally.")


def _host_matches_allowed_suffix(hostname: str, suffix: str) -> bool:
    hostname = hostname.lower()
    suffix = suffix.lower().lstrip(".")
    return hostname == suffix or hostname.endswith("." + suffix)


def is_safe_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        return False
    return any(_host_matches_allowed_suffix(parsed.hostname, suffix) for suffix in ALLOWED_HOST_SUFFIXES)


def _require_safe_url(url: str, label: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise RuntimeError(f"{label} must use https://, got: {url}")
    if not parsed.hostname:
        raise RuntimeError(f"{label} must include a hostname, got: {url}")
    if not is_safe_url(url):
        allowed = ", ".join(ALLOWED_HOST_SUFFIXES) or "<none>"
        raise RuntimeError(f"{label} must point to an allowed host suffix ({allowed}), got: {url}")


def _is_login_page(url: str) -> bool:
    parsed = urlparse(url)
    path = (parsed.path or "").lower().rstrip("/")
    return path.endswith("/login") or path.endswith("/signin")


_require_safe_url(LOGIN_URL, "LOGIN_URL")
_require_safe_url(TARGET_URL, "TARGET_URL")


class RedactingFilter(logging.Filter):
    """
    Logging filter that redacts sensitive values from log messages and exception text.

    It replaces any literal occurrences of configured sensitive values with "[REDACTED]".
    This is best-effort: it runs on the LogRecord before formatting.
    """
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            try:
                original = record.getMessage()
            except Exception:
                original = str(record.msg)

            redacted = original
            for secret in _SENSITIVE_VALUES:
                if secret:
                    redacted = redacted.replace(secret, "[REDACTED]")

            record.msg = redacted
            record.args = ()

            if getattr(record, "exc_text", None):
                exc = str(record.exc_text)
                for secret in _SENSITIVE_VALUES:
                    if secret:
                        exc = exc.replace(secret, "[REDACTED]")
                record.exc_text = exc
        except Exception:
            pass
        return True


redacting_filter = RedactingFilter()
logger.addFilter(redacting_filter)
for h in logging.root.handlers:
    h.addFilter(redacting_filter)


class RedactingFormatter(logging.Formatter):
    """
    Formatter that redacts configured sensitive values from output.

    This overrides formatException to ensure tracebacks are also redacted.
    """
    def formatException(self, exc_info):
        try:
            text = super().formatException(exc_info)
        except Exception:
            text = logging.Formatter().formatException(exc_info)
        for secret in _SENSITIVE_VALUES:
            if secret:
                text = text.replace(secret, "[REDACTED]")
        return text

    def format(self, record: logging.LogRecord) -> str:
        s = super().format(record)
        for secret in _SENSITIVE_VALUES:
            if secret:
                s = s.replace(secret, "[REDACTED]")
        return s


for h in logging.root.handlers:
    try:
        fmt = h.formatter._fmt if getattr(h, "formatter", None) else "%(asctime)s %(levelname)s %(message)s"
        h.setFormatter(RedactingFormatter(fmt))
    except Exception:
        try:
            h.setFormatter(RedactingFormatter("%(asctime)s %(levelname)s %(message)s"))
        except Exception:
            pass


def _redact(message: str) -> str:
    sanitized = str(message)
    for secret in _SENSITIVE_VALUES:
        sanitized = sanitized.replace(secret, "[REDACTED]")
    return sanitized


def _log(level: int, message: str):
    logger.log(level, _redact(message))


def _retry_navigation(
    func: Callable[[], T],
    *,
    label: str,
    attempts: int = NAV_RETRY_ATTEMPTS,
    base_delay: float = NAV_RETRY_BASE_DELAY,
) -> T:
    """
    Retries an idempotent, read-only navigation/wait operation with exponential
    backoff and jitter, to smooth over transient issues (slow page loads, brief
    network hiccups, flaky element rendering).

    IMPORTANT: Only use this for operations that are safe to repeat (e.g. driver.get()
    on a GET page, waiting for an element to appear). Never wrap credential submission
    or any form POST in this — see module docstring for why.

    Args:
        func: A zero-argument callable to attempt.
        label: A short description used in log messages.
        attempts: Maximum number of attempts.
        base_delay: Base delay in seconds; actual delay grows exponentially with jitter.

    Returns:
        The return value of func() on success.

    Raises:
        The last exception encountered, if all attempts fail.
    """
    last_exc: Optional[BaseException] = None
    for attempt in range(1, attempts + 1):
        try:
            return func()
        except Exception as e:
            last_exc = e
            if attempt >= attempts:
                _log(logging.ERROR, f"{label}: failed after {attempt} attempt(s): {e}")
                break
            delay = base_delay * (2 ** (attempt - 1)) + random.uniform(0, base_delay)
            _log(
                logging.WARNING,
                f"{label}: attempt {attempt}/{attempts} failed ({e}); retrying in {delay:.1f}s",
            )
            time.sleep(delay)
    assert last_exc is not None
    raise last_exc


def lunar_day(today_utc: Optional[dt.datetime] = None) -> int:
    """
    Calculates the day of the current lunar month (approximately 0-29).
    """
    if today_utc is None:
        today_utc = dt.datetime.now(dt.timezone.utc)

    try:
        phase = astral_moon.phase(today_utc)
        day = int(math.floor(phase))
        return day % 30
    except Exception:
        return today_utc.day % 30


def _get_moon_phase_dates_for_month(year: int, month: int) -> List[Tuple[int, str]]:
    """
    Get exact moon phase dates for a given month using the skyfield library.
    """
    from skyfield import api, almanac

    results = []

    eph = api.load('de421.bsp')
    ts = api.load.timescale()

    if month == 12:
        t0 = ts.utc(year, month, 1)
        t1 = ts.utc(year + 1, 1, 1)
    else:
        t0 = ts.utc(year, month, 1)
        t1 = ts.utc(year, month + 1, 1)

    times, phases = almanac.find_discrete(t0, t1, almanac.moon_phases(eph))

    phase_names = {
        0: 'new',
        1: 'first_quarter',
        2: 'full',
        3: 'third_quarter'
    }

    for time_, phase in zip(times, phases):
        py_dt = time_.utc_datetime()
        results.append((py_dt.day, phase_names[phase]))

    return sorted(results, key=lambda x: x[0])


def _is_phase_date(date_dt: dt.datetime) -> bool:
    """
    Checks if a given UTC date corresponds to a major moon phase.
    """
    try:
        phases = _get_moon_phase_dates_for_month(date_dt.year, date_dt.month)
        for day, _ in phases:
            if day == date_dt.day:
                return True
    except Exception:
        pass
    return False


def select_playlist_for_day(ids: List[str], day: int, date_dt: dt.datetime) -> Tuple[str, int]:
    """
    Selects a playlist ID based on the lunar day and special date rules.
    """
    if not ids:
        raise RuntimeError("PLAYLIST_IDS is empty. Please set the environment variable.")

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


def build_driver():
    """
    Builds and configures the Selenium Chrome WebDriver.
    """
    _log(logging.DEBUG, "Starting Chrome driver build...")
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service as ChromeService

    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-default-apps")
    options.add_argument("--disable-popup-blocking")
    options.add_argument("--disable-background-networking")
    options.add_argument("--window-size=1200,900")
    options.add_experimental_option(
        "prefs",
        {
            "download.prompt_for_download": False,
            "download.directory_upgrade": True,
            "profile.default_content_setting_values.automatic_downloads": 2,
        },
    )
    chromedriver_path = os.getenv("CHROMEDRIVER")

    def _verify_chromedriver(path: str, expected_sha256: Optional[str] = None):
        if not expected_sha256 or not path or not os.path.exists(path):
            return
        try:
            import hashlib
            with open(path, "rb") as f:
                digest = hashlib.sha256(f.read()).hexdigest()
            if digest != expected_sha256:
                raise RuntimeError(f"Chromedriver hash mismatch: expected={expected_sha256[:12]}..., got={digest[:12]}...")
        except Exception:
            raise

    if chromedriver_path:
        _verify_chromedriver(chromedriver_path, os.getenv("CHROMEDRIVER_HASH"))
        service = ChromeService(executable_path=chromedriver_path)
        driver = webdriver.Chrome(service=service, options=options)
    else:
        driver = webdriver.Chrome(options=options)
    _log(logging.DEBUG, "Chrome driver started.")
    return driver


def save_debug(driver, name: str):
    """
    Saves the current page's HTML and a screenshot for debugging purposes.
    """
    if not SAVE_DEBUG:
        _log(logging.DEBUG, f"Debug capture disabled; skipping {name}")
        return
    if os.getenv("CI") or os.getenv("GITHUB_ACTIONS"):
        _log(logging.DEBUG, f"CI detected; skipping debug capture for {name}")
        return
    try:
        html = driver.page_source
        try:
            safe_html = sanitize_html(html)
        except Exception:
            safe_html = html
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
    """
    Return a sanitized copy of HTML with input values, tokens, and (optionally)
    inline script bodies removed. Best-effort, regex-based — not a substitute for
    not saving debug artifacts at all in shared/CI environments.
    """
    try:
        # Strip inline <script>...</script> contents entirely (config/state objects,
        # CSRF tokens, and API keys are commonly embedded here). Kept optional via
        # SANITIZE_STRIP_SCRIPTS in case script content is ever needed for debugging.
        if SANITIZE_STRIP_SCRIPTS:
            html = re.sub(
                r"(<script\b[^>]*>)(.*?)(</script\b[^>]*>)",
                r"\1/* [REDACTED: script body stripped for debug export] */\3",
                html,
                flags=re.I | re.S,
            )

        html = re.sub(r"(<input\b[^>]*?)\svalue=(\".*?\"|'.*?'|[^>\s>]+)", r"\1", html, flags=re.I | re.S)

        html = re.sub(r"<meta[^>]+(csrf|csrf-token|csrf_param|xsrf)[^>]*>", "", html, flags=re.I | re.S)

        html = re.sub(
            r"([\'\"](?:csrf|csrfToken|csrf_token|auth_token|token|password|pwd)[\'\"]\s*:\s*)([\'\"]).*?([\'\"])",
            lambda m: m.group(1) + m.group(2) + "[REDACTED]" + m.group(3),
            html, flags=re.I | re.S,
        )

        html = re.sub(r"(Authorization\s*:\s*)(Bearer|Basic)\s+[^\s\"'>]+", r"\1\2 [REDACTED]", html, flags=re.I)

        html = re.sub(r"\b[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b", "[REDACTED]", html)

        html = re.sub(r"fetch\s*\([^)]*(Authorization|Bearer|token)[^)]*\)", "[REDACTED]", html, flags=re.I)

        html = re.sub(r"localStorage\.setItem\s*\([^)]*(token|auth|session)[^)]*\)", "[REDACTED]", html, flags=re.I)
        html = re.sub(r"sessionStorage\.setItem\s*\([^)]*(token|auth|session)[^)]*\)", "[REDACTED]", html, flags=re.I)

        html = re.sub(r"([\s;](?:var|let|const))\s+(?:token|auth|session)\s*=\s*['\"][^'\"]+['\"]", "[REDACTED]", html, flags=re.I)

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

        html = re.sub(r"(data-(?:token|auth|session)[^=]*=[\"']).*?([\"'])", lambda m: m.group(1) + "[REDACTED]" + m.group(2), html, flags=re.I | re.S)
        return html
    except Exception:
        return html


def smart_fill_login(driver, login: str, password: str):
    """
    Intelligently finds and fills the login form, then submits it exactly once.

    Navigation to the login page is retried on transient failures, but the actual
    credential submission is NOT retried within this function — see module docstring.
    """
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC

    wait = WebDriverWait(driver, WAIT_TIMEOUT)
    _require_safe_url(LOGIN_URL, "LOGIN_URL")

    _retry_navigation(lambda: driver.get(LOGIN_URL), label="Load login page")

    if not is_safe_url(driver.current_url):
        raise RuntimeError(f"Unexpected login domain: {driver.current_url}")
    save_debug(driver, "login_page")

    login_locators = [
        (By.NAME, "_username"), (By.NAME, "username"), (By.NAME, "login"), (By.NAME, "email"),
        (By.ID, "username"), (By.ID, "login"), (By.ID, "email"),
        (By.CSS_SELECTOR, "input[type='email']"),
        (By.CSS_SELECTOR, "input[type='text']"),
    ]

    pwd_locators = [
        (By.NAME, "_password"), (By.NAME, "password"), (By.ID, "password"),
        (By.CSS_SELECTOR, "input[type='password']"),
    ]

    login_input = None
    for by, sel in login_locators:
        try:
            candidate = _retry_navigation(
                lambda by=by, sel=sel: wait.until(EC.presence_of_element_located((by, sel))),
                label=f"Locate login field ({sel})",
                attempts=1,  # element lookups already loop over locators; no need to also retry each one
            )
            if candidate.is_displayed():
                login_input = candidate
                break
        except Exception:
            continue

    if not login_input:
        save_debug(driver, "login_no_input")
        raise RuntimeError("Login field not found. Update selectors in agent.py")

    login_input.clear()
    login_input.send_keys(login)

    pwd_input = None
    for by, sel in pwd_locators:
        try:
            candidate = wait.until(EC.presence_of_element_located((by, sel)))
            if candidate.is_displayed():
                pwd_input = candidate
                break
        except Exception:
            continue

    if not pwd_input:
        save_debug(driver, "login_no_password")
        raise RuntimeError("Password field not found. Update selectors in agent.py")

    pwd_input.clear()
    pwd_input.send_keys(password)

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

    # Single, deliberate submission — never retried. If this fails downstream
    # (wrong redirect, still on login page), we surface a clear error instead
    # of resubmitting credentials, to avoid tripping login rate-limits/lockouts.
    submit_button.click()

    try:
        wait.until(lambda d: is_safe_url(d.current_url) and not _is_login_page(d.current_url))
    except Exception as e:
        logger.exception(f"Error while waiting for post-login redirect: {e}")
        try:
            save_debug(driver, "login_exception")
        except Exception:
            pass
        raise

    if not is_safe_url(driver.current_url):
        save_debug(driver, "unsafe_login_redirect")
        raise RuntimeError(f"Unexpected login redirect domain: {driver.current_url}")

    if _is_login_page(driver.current_url):
        save_debug(driver, "after_login_no_redirect")
        _log(
            logging.WARNING,
            "No redirect detected after login; this may indicate wrong credentials or a "
            "changed login flow. Not retrying submission to avoid rate limiting — investigate "
            "before the next scheduled run.",
        )


def change_playlist(driver, playlist_id: str):
    """
    Finds the playlist selector, changes its value, and saves the change.

    Page navigation is retried on transient failures; the final save/submit click
    is attempted once per matched button (not looped indefinitely) since it is a
    state-changing action.
    """
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait, Select
    from selenium.webdriver.support import expected_conditions as EC

    _log(logging.INFO, f"change_playlist called with playlist_id={playlist_id}")

    wait = WebDriverWait(driver, WAIT_TIMEOUT)
    _require_safe_url(TARGET_URL, "TARGET_URL")
    _log(logging.INFO, f"Navigating to TARGET_URL: {TARGET_URL}")

    _retry_navigation(lambda: driver.get(TARGET_URL), label="Load target playlist page")

    time.sleep(2)
    _log(logging.INFO, f"Current URL: {driver.current_url}")
    _log(logging.INFO, f"Page title: {driver.title}")

    if not is_safe_url(driver.current_url):
        save_debug(driver, "unsafe_target_domain")
        raise RuntimeError(f"Unexpected target domain: {driver.current_url}")

    if _is_login_page(driver.current_url):
        _log(logging.ERROR, "Session lost - redirected to login page. Check login flow.")
        save_debug(driver, "session_lost")
        raise RuntimeError("Session lost after login - redirected back to login page")

    save_debug(driver, "target_page")

    target_select = None
    _log(logging.INFO, "Looking for select#playlist_0_playlist...")
    try:
        target_select = _retry_navigation(
            lambda: wait.until(EC.presence_of_element_located((By.ID, "playlist_0_playlist"))),
            label="Locate playlist select by ID",
        )
        _log(logging.INFO, "Found select by ID")
    except Exception as e:
        _log(logging.DEBUG, f"Select by ID not found: {e}")
        try:
            target_select = wait.until(EC.presence_of_element_located((By.NAME, "playlist_0[playlist]")))
            _log(logging.DEBUG, "Found select by NAME")
        except Exception as e2:
            _log(logging.DEBUG, f"Select by NAME not found: {e2}")

    if not target_select:
        _log(logging.DEBUG, "Scanning all <select> elements...")
        selects = driver.find_elements(By.TAG_NAME, "select")
        _log(logging.DEBUG, f"Found {len(selects)} select elements")
        for s in selects:
            try:
                if s.get_attribute("disabled"):
                    continue
                if s.find_elements(By.CSS_SELECTOR, f"option[value='{playlist_id}']"):
                    target_select = s
                    _log(logging.DEBUG, f"Found select with option value={playlist_id}")
                    break
            except Exception:
                continue

    if not target_select:
        save_debug(driver, "no_select")
        raise RuntimeError(f"<select> with option value={playlist_id} not found. Update selectors.")

    _log(logging.INFO, f"Selecting value: {playlist_id}")
    try:
        Select(target_select).select_by_value(playlist_id)
        _log(logging.INFO, "Selection successful via Select helper")
    except Exception as e:
        _log(logging.DEBUG, f"Select helper failed: {e}, trying JavaScript...")
        try:
            driver.execute_script("arguments[0].value = arguments[1]; arguments[0].dispatchEvent(new Event('change'));", target_select, playlist_id)
            _log(logging.DEBUG, "Selection successful via JavaScript")
        except Exception:
            save_debug(driver, "select_set_fail")
            raise

    _log(logging.INFO, "Looking for save button...")
    save_clicked = False
    try:
        btn = driver.find_element(By.ID, "playlist_0_submit")
        if btn.is_enabled():
            btn.click()
            save_clicked = True
            _log(logging.INFO, "Clicked button by ID playlist_0_submit")
    except Exception:
        pass

    if not save_clicked:
        try:
            btn = driver.find_element(By.NAME, "playlist_0[submit]")
            if btn.is_enabled():
                btn.click()
                save_clicked = True
                _log(logging.DEBUG, "Clicked button by NAME playlist_0[submit]")
        except Exception:
            pass

    if not save_clicked:
        try:
            btn = driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
            if btn.is_enabled():
                btn.click()
                save_clicked = True
                _log(logging.DEBUG, "Clicked generic submit button")
        except Exception:
            pass

    if not save_clicked:
        for text in SAVE_BUTTON_TEXTS:
            try:
                xpath = f"//button[contains(normalize-space(.), '{text}')] | //input[@type='submit' and contains(@value,'{text}')]"
                btns = driver.find_elements(By.XPATH, xpath)
                for b in btns:
                    if b.is_displayed() and b.is_enabled():
                        b.click()
                        save_clicked = True
                        _log(logging.DEBUG, f"Clicked button with text: {text}")
                        break
                if save_clicked:
                    break
            except Exception:
                continue

    if not save_clicked:
        _log(logging.WARNING, "No save button was clicked!")
    else:
        _log(logging.INFO, "Playlist change submitted")

    time.sleep(3)
    save_debug(driver, "after_change")


def main():
    """
    Main execution function for the script.
    """
    try:
        logger.info(f"Running v{__version__}")
    except Exception:
        pass
    if not DRY_RUN and (not LOGIN or not PASSWORD):
        logger.error(
            "LOGIN/PASSWORD missing from environment variables. "
            "Set repository secrets `MANIAPLANET_LOGIN` and `MANIAPLANET_PASSWORD` "
            "or export `LOGIN` and `PASSWORD` in the environment. "
            "For local testing you can set `DRY_RUN=1` to skip Selenium actions."
        )
        sys.exit(1)

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

    playlist_id, bucket = select_playlist_for_day(PLAYLIST_IDS, day, date_dt)
    _log(logging.INFO, f"Selected playlist_id (lunar calendar): {playlist_id} (bucket={bucket}, day={day})")
    if DRY_RUN:
        _log(logging.INFO, "DRY RUN enabled, skipping Selenium.")
        return

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