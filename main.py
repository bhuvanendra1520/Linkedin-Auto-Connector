from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from configparser import ConfigParser
from selenium.webdriver.common.action_chains import ActionChains
from colorama import Fore, Style, init
import time
from urllib.parse import quote
import os
import json
import traceback 
import sys
from selenium.webdriver.common.keys import Keys

# Initialize colorama
init(autoreset=True)

# Initialize config parser
config = ConfigParser()
config_file = 'setup.ini'
config.read(config_file)

# Add input config file
input_config = ConfigParser()
input_config_file = 'input_config.ini'

# Debug controls (override with environment variables if needed)
DEBUG_VERBOSE = os.environ.get("LAC_DEBUG_VERBOSE", "1").lower() in ("1", "true", "yes", "on")
DEBUG_ARTIFACTS = os.environ.get("LAC_DEBUG_ARTIFACTS", "1").lower() in ("1", "true", "yes", "on")
DEBUG_ARTIFACT_DIR = os.environ.get("LAC_DEBUG_ARTIFACT_DIR", "debug_artifacts")

# LinkedIn UI text constants — update here if LinkedIn changes button labels
_BTN_CONNECT         = "Connect"
_BTN_ADD_NOTE        = "Add a note"
_BTN_SEND_NO_NOTE    = "Send without a note"
_BTN_SEND_INVITATION = "Send invitation"
_BTN_MESSAGE         = "Message"
_BTN_PENDING         = "Pending"
_BTN_MORE_ACTIONS    = "More actions"

def setup_driver() -> webdriver.Chrome:
    try:
        chrome_options = Options()
        chrome_options.add_argument("--log-level=2")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-blink-features=AutomationControlled")
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        chrome_options.add_experimental_option("useAutomationExtension", False)

        # Uncomment the line below if you're having issues with the driver
        # service = Service(ChromeDriverManager().install())
        # driver = webdriver.Chrome(service=service, options=chrome_options)
        driver = webdriver.Chrome(options=chrome_options)
        # Remove webdriver flag so LinkedIn doesn't detect automation
        driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
            "source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        })
        return driver
    except Exception as e:
        print(Fore.RED + f"[ERROR] Failed to setup Chrome driver: {e}")
        traceback.print_exc()
        sys.exit(1)

def save_cookie(driver:webdriver.Chrome):
    """Save the cookie to the setup.ini file"""
    try:
        li_at_cookie = driver.get_cookie('li_at')['value']
        config.set('LinkedIn', 'li_at', li_at_cookie)
        with open(config_file, 'w') as f:
            config.write(f)
    except Exception as e:
        print(Fore.YELLOW + f"[WARNING] Could not save cookie: {e}")

def _wait_for_logged_in(driver, timeout=20):
    """Wait for any element that indicates successful LinkedIn login."""
    selectors = [
        (By.ID, "global-nav-typeahead"),
        (By.ID, "global-nav"),
        (By.CSS_SELECTOR, "input[aria-label='Search']"),
        (By.CSS_SELECTOR, "nav.global-nav"),
        (By.CSS_SELECTOR, "[data-test-global-nav]"),
        (By.CSS_SELECTOR, "div.search-global-typeahead"),
        (By.CSS_SELECTOR, "img.global-nav__me-photo"),
    ]
    def _check(d):
        # URL-based check: if we're on the feed or any authenticated page, we're logged in
        current = d.current_url
        if any(path in current for path in ["/feed", "/mynetwork", "/messaging", "/notifications", "/search/results"]):
            if DEBUG_VERBOSE:
                print(Fore.CYAN + f"  [DEBUG] Login confirmed via URL: {current}")
            return True
        for by, value in selectors:
            try:
                el = d.find_element(by, value)
                if el:
                    if DEBUG_VERBOSE:
                        print(Fore.CYAN + f"  [DEBUG] Login confirmed via: {by}={value}")
                    return el
            except Exception:
                pass
        return False
    return WebDriverWait(driver, timeout).until(_check)

def login_with_cookie(driver:webdriver.Chrome, li_at):
    """Attempt to login with the existing 'li_at' cookie"""
    try:
        print(Fore.YELLOW + "Attempting to log in with cookie...")
        driver.get("https://www.linkedin.com")
        driver.add_cookie(
            {
                "name": "li_at",
                "value": f"{li_at}",
                "path": "/",
                "secure": True,
                "domain": ".linkedin.com"  # Added domain to fix cookie issues
            }
        )
        driver.refresh()
        _wait_for_logged_in(driver, timeout=20)
        print(Fore.GREEN + "[INFO] Logged in with cookie successfully.")
    except Exception as e:
        print(Fore.RED + f"[ERROR] Cookie login failed: {e}")
        if DEBUG_VERBOSE:
            print(Fore.CYAN + f"  [DEBUG] Current URL: {driver.current_url}")
            print(Fore.CYAN + f"  [DEBUG] Page title: {driver.title}")
        if DEBUG_ARTIFACTS:
            os.makedirs(DEBUG_ARTIFACT_DIR, exist_ok=True)
            driver.save_screenshot(os.path.join(DEBUG_ARTIFACT_DIR, "cookie_login_fail.png"))
            print(Fore.CYAN + f"  [DEBUG] Screenshot saved to {DEBUG_ARTIFACT_DIR}/cookie_login_fail.png")
        traceback.print_exc()
        raise

def login_with_credentials(driver:webdriver.Chrome, email:str, password:str):
    """Login using credentials and handle verification code if required"""
    try:
        print(Fore.YELLOW + "Logging in with credentials...")
        driver.get("https://www.linkedin.com/login")
        if DEBUG_VERBOSE:
            print(Fore.CYAN + f"  [DEBUG] Login page URL: {driver.current_url}")
            print(Fore.CYAN + f"  [DEBUG] Login page title: {driver.title}")
        WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.ID, "username")))

        driver.find_element(By.ID, "username").send_keys(email)
        driver.find_element(By.ID, "password").send_keys(password)
        driver.find_element(By.XPATH, "//button[@type='submit']").click()

        # Wait for either successful login or verification code prompt
        WebDriverWait(driver, 10).until(
            lambda d: any(
                d.find_elements(by, val) for by, val in [
                    (By.ID, "global-nav-typeahead"), (By.ID, "global-nav"),
                    (By.CSS_SELECTOR, "nav.global-nav"), (By.CSS_SELECTOR, "input[aria-label='Search']"),
                ]
            ) or "Enter the code" in d.page_source or "verification" in d.page_source.lower()
        )

        if "Enter the code" in driver.page_source or "verification" in driver.page_source.lower():
            verification_code = input("[+] Enter the verification code sent to your email: ")
            WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.ID, "input__email_verification_pin")))
            driver.find_element(By.ID, "input__email_verification_pin").send_keys(verification_code)
            driver.find_element(By.ID, "email-pin-submit-button").click()

        _wait_for_logged_in(driver, timeout=10)
        print(Fore.GREEN + "[INFO] Logged in with credentials successfully.")
        save_cookie(driver)
    except Exception as e:
        print(Fore.RED + f"[ERROR] Credential login failed: {e}")
        traceback.print_exc()
        raise

def select_location(driver:webdriver.Chrome, location:str):
    """Select the location in the LinkedIn search filter"""
    try:
        print("Selecting location")
        WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.ID, "searchFilter_geoUrn"))).click()
        time.sleep(1)
        location_input = WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.XPATH, "//input[@placeholder='Add a location']")))
        location_input.send_keys(location)
        time.sleep(2)
        try:
            driver.find_element(By.XPATH,f"//*[text()='{location.title()}']").click()
            # Close the dropdown suggestions
            location_input.send_keys(Keys.ESCAPE)
        except:
            # Try alternative location selector if the first one fails
            location_options = driver.find_elements(By.XPATH, "//span[contains(@class, 'search-typeahead-v2__hit-info')]")
            if location_options:
                location_options[0].click()
                location_input.send_keys(Keys.ESCAPE)
            else:
                print(Fore.YELLOW + f"[WARNING] Could not select location '{location}'. Continuing without location filter.")
                driver.find_element(By.XPATH, "//button[@aria-label='Dismiss']").click()
                return
                
        time.sleep(1)
        # First fallback: Use the text-based XPath for the 'Show Results' button
        try:
            show_results_button = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((
                    By.XPATH,
                    "//button[(translate(@aria-label,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz')='show results') or span[translate(normalize-space(),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz')='show results']]"
                ))
            )
            driver.execute_script("arguments[0].click();", show_results_button)
            print("[DEBUG] 'Show Results' button clicked using text-based XPath.")
        except:
            # Second fallback: Press Enter to apply the location filter
            print("[DEBUG] 'Show Results' button not clickable, pressing Enter.")
            location_input.send_keys(Keys.RETURN)
            time.sleep(3)
            
            # Third fallback: Force-click the first 'Show Results' button
            try:
                show_results = driver.find_element(By.XPATH,
                    "(//button[span[normalize-space()='Show results']])[1]")
                driver.execute_script("arguments[0].click();", show_results)
                print("[DEBUG] 'Show Results' button force-clicked.")
            except Exception as e:
                print(Fore.YELLOW + f"[WARNING] Could not force-click 'Show Results' button: {e}")
        time.sleep(3)
    except Exception as e:
        print(Fore.YELLOW + f"[WARNING] Error selecting location: {e}")
        traceback.print_exc()
        print(Fore.YELLOW + "Continuing without location filter...")

def _scroll_to_load(driver: webdriver.Chrome) -> None:
    """Scroll the page incrementally to trigger lazy-loaded action buttons."""
    driver.execute_script("window.scrollTo(0, document.body.scrollHeight * 0.3);")
    time.sleep(1)
    driver.execute_script("window.scrollTo(0, document.body.scrollHeight * 0.6);")
    time.sleep(1)
    driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
    time.sleep(2)


def collect_connect_elements(driver: webdriver.Chrome) -> list:
    """Find Connect elements (buttons or <a> tags) on the search page.
    Returns list of dicts: {'element': WebElement, 'name': str, 'profile_url': str}
    """
    # Wait for result cards to render
    try:
        WebDriverWait(driver, 8).until(
            EC.presence_of_element_located((By.XPATH,
                '//li[contains(@class,"reusable-search__result-container")]'
                ' | //li[contains(@class,"entity-result")]'
            ))
        )
    except Exception:
        pass

    _scroll_to_load(driver)

    # Find Connect elements — try <a> tags first (LinkedIn's current structure),
    # then fall back to <button> tags
    connect_els = []
    all_xpaths = [
        # <a> tags with aria-label "Invite X to connect"
        "//a[contains(translate(@aria-label,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'invite') and contains(translate(@aria-label,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'connect')]",
        # <button> with similar aria-label
        "//button[contains(translate(@aria-label,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'invite') and contains(translate(@aria-label,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'connect')]",
        # <button> or <a> with span text "Connect"
        "//button[.//span[normalize-space(text())='Connect']]",
        "//a[.//span[normalize-space(text())='Connect']]",
        # role=button
        "//*[@role='button'][contains(@aria-label,'onnect')]",
    ]
    for xpath in all_xpaths:
        try:
            found = driver.find_elements(By.XPATH, xpath)
            if found:
                print(Fore.CYAN + f"[DEBUG] Found {len(found)} Connect element(s) via: {xpath}")
                connect_els = found
                break
        except Exception:
            continue

    if not connect_els:
        # Diagnostic dump
        try:
            any_connect = driver.execute_script("""
                var all = Array.from(document.querySelectorAll('*'));
                var hits = [];
                all.forEach(function(el) {
                    var lbl = (el.getAttribute('aria-label') || '').toLowerCase();
                    var txt = (el.textContent || '').trim();
                    if (lbl.indexOf('connect') !== -1 || txt === 'Connect') {
                        hits.push(el.tagName + '[' + (el.getAttribute('aria-label') || txt.slice(0,30)) + ']');
                    }
                });
                return hits.slice(0, 20);
            """)
            print(Fore.CYAN + f"[DEBUG] ANY elements with 'connect': {any_connect}")
        except Exception:
            pass
        try:
            all_btns = driver.find_elements(By.XPATH, "//button")
            labels = list({(b.get_attribute("aria-label") or b.text or "").strip() for b in all_btns if (b.get_attribute("aria-label") or b.text or "").strip()})
            print(Fore.CYAN + f"[DEBUG] All <button> labels on page: {labels[:30]}")
        except Exception:
            pass
        return []

    # Build result list with element, name, and profile URL
    results = []
    seen = set()
    for el in connect_els:
        try:
            lbl = el.get_attribute("aria-label") or el.text or ""

            # Extract name from aria-label like "Invite Kerrie Trimm to connect"
            name = ""
            lbl_lower = lbl.lower()
            if "invite" in lbl_lower and "connect" in lbl_lower:
                name = lbl.replace("Invite ", "").replace(" to connect", "").strip()

            # Walk up DOM to find the /in/ profile link
            profile_url = driver.execute_script("""
                var el = arguments[0];
                var node = el.parentElement;
                for (var i = 0; i < 20; i++) {
                    if (!node) break;
                    var links = Array.from(node.querySelectorAll('a[href*="/in/"]'));
                    for (var j = 0; j < links.length; j++) {
                        var href = links[j].href || '';
                        if (href.indexOf('linkedin.com/in/') !== -1 && links[j] !== el) {
                            return href.split('?')[0].replace(/\\/+$/, '');
                        }
                    }
                    if (node.tagName === 'LI') break;
                    var cls = node.className || '';
                    if (cls.indexOf('entity-result') !== -1 || cls.indexOf('reusable-search__result-container') !== -1) break;
                    node = node.parentElement;
                }
                return '';
            """, el)

            key = profile_url or name or lbl
            if key and key not in seen:
                seen.add(key)
                results.append({'element': el, 'name': name, 'profile_url': profile_url})
                print(Fore.CYAN + f"[DEBUG] [{name or lbl.strip()}] -> {profile_url or 'no URL'}")
        except Exception as e:
            print(Fore.CYAN + f"[DEBUG] Error processing element: {e}")
            continue

    return results


def get_name_from_profile_page(driver: webdriver.Chrome) -> str:
    """Extract first name from a LinkedIn profile page h1."""
    try:
        h1 = WebDriverWait(driver, 8).until(
            EC.presence_of_element_located((By.XPATH, '//h1'))
        )
        full = h1.text.strip()
        return full.split(' ')[0].title() if full else ''
    except Exception:
        return ''


def collect_message_buttons(driver: webdriver.Chrome) -> list:
    """Collect Message buttons for 1st-degree connections."""
    try:
        WebDriverWait(driver, 8).until(
            EC.presence_of_element_located((By.XPATH,
                '//li[contains(@class,"reusable-search__result-container")]'
                ' | //li[contains(@class,"entity-result")]'
            ))
        )
    except Exception:
        pass
    _scroll_to_load(driver)

    for xpath in [
        "//button[contains(@aria-label,'Message')]",
        "//span[text()='Message']/ancestor::button",
        "//div[contains(@class,'entity-result__actions')]//button[contains(.,'Message')]",
    ]:
        try:
            found = driver.find_elements(By.XPATH, xpath)
            if found:
                return found
        except Exception:
            continue
    return []


def navigate_to_next_page(driver: webdriver.Chrome, current_page_num: int) -> bool:
    """Navigate to the next page of search results. Returns True if successful."""
    driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
    time.sleep(2)

    # Method 1: Find Next button directly (no timeout/clickable check that might fail)
    for xpath in [
        "//button[@aria-label='Next']",
        "//button[contains(@aria-label,'Next')]",
        "//span[normalize-space(text())='Next']/parent::button",
        "//button[contains(@class,'artdeco-pagination__button--next')]",
        "//li[contains(@class,'artdeco-pagination__button--next')]/button",
    ]:
        try:
            btns = driver.find_elements(By.XPATH, xpath)
            if btns:
                btn = btns[0]
                driver.execute_script("arguments[0].scrollIntoView({block:'center'});", btn)
                time.sleep(0.5)
                driver.execute_script("arguments[0].click();", btn)
                print(Fore.GREEN + f"[INFO] Clicked Next button → page {current_page_num+1}")
                return True
        except Exception:
            continue

    # Method 2: Click the next page number button
    try:
        next_num = current_page_num + 1
        # LinkedIn pagination buttons show "Page N" as aria-label and "N" as text
        for xpath in [
            f"//button[@aria-label='Page {next_num}']",
            f"//button[normalize-space(text())='{next_num}']",
            f"//button[normalize-space()='{next_num}']",
        ]:
            btns = driver.find_elements(By.XPATH, xpath)
            if btns:
                driver.execute_script("arguments[0].scrollIntoView({block:'center'});", btns[0])
                time.sleep(0.3)
                driver.execute_script("arguments[0].click();", btns[0])
                print(Fore.GREEN + f"[INFO] Clicked page number button {next_num}")
                return True
    except Exception:
        pass

    # Method 3: URL manipulation
    try:
        current_url = driver.current_url
        if "page=" in current_url:
            page_part = current_url.split("page=")[1]
            cur = int(page_part.split("&")[0]) if "&" in page_part else int(page_part)
            next_url = current_url.replace(f"page={cur}", f"page={cur+1}")
        else:
            next_url = current_url + ("&page=2" if "?" in current_url else "?page=2")
        driver.get(next_url)
        print(Fore.GREEN + f"[INFO] Navigated to page {current_page_num+1} via URL")
        return True
    except Exception:
        pass

    return False


def _safe_filename_component(value, max_len=72):
    raw = str(value or "").strip()
    if not raw:
        return "item"
    cleaned = "".join(ch if (ch.isalnum() or ch in ("-", "_")) else "_" for ch in raw)
    cleaned = cleaned.encode("ascii", "ignore").decode("ascii")
    while "__" in cleaned:
        cleaned = cleaned.replace("__", "_")
    cleaned = cleaned.strip("_")
    return (cleaned or "item")[:max_len]


def _capture_invite_state(driver):
    """Capture a compact snapshot of the current page/modal state for debugging."""
    try:
        return driver.execute_script("""
            function isVisible(el) {
                if (!el) return false;
                var rect = el.getBoundingClientRect();
                var style = window.getComputedStyle(el);
                return rect.width > 0 && rect.height > 0 &&
                    style.visibility !== 'hidden' && style.display !== 'none';
            }

            var info = {
                url: window.location.href,
                title: document.title || '',
                readyState: document.readyState || '',
                dialogCount: document.querySelectorAll('[role="dialog"], [role="alertdialog"]').length,
                modalCount: document.querySelectorAll('.artdeco-modal').length,
                actionButtons: [],
                activeElement: ''
            };

            var ae = document.activeElement;
            if (ae) {
                var aeLbl = (ae.getAttribute('aria-label') || '').trim();
                var aeTxt = (ae.innerText || ae.textContent || '').trim().replace(/\\s+/g, ' ');
                info.activeElement = (ae.tagName || '') + ' | ' + aeLbl + ' | ' + aeTxt;
            }

            var candidates = Array.from(document.querySelectorAll('button, a, [role="button"]'));
            var keywords = ['connect', 'invite', 'send', 'note', 'dismiss', 'pending', 'withdraw'];
            for (var i = 0; i < candidates.length && info.actionButtons.length < 30; i++) {
                var el = candidates[i];
                if (!isVisible(el)) continue;
                var lbl = (el.getAttribute('aria-label') || '').trim();
                var txt = (el.innerText || el.textContent || '').trim().replace(/\\s+/g, ' ');
                var blob = (lbl + ' ' + txt).toLowerCase();
                var matched = false;
                for (var k = 0; k < keywords.length; k++) {
                    if (blob.indexOf(keywords[k]) !== -1) {
                        matched = true;
                        break;
                    }
                }
                if (matched) {
                    info.actionButtons.push((el.tagName || '') + ' | ' + lbl + ' | ' + txt);
                }
            }
            return info;
        """)
    except Exception as e:
        return {
            "url": "",
            "title": "",
            "readyState": "",
            "dialogCount": -1,
            "modalCount": -1,
            "actionButtons": [],
            "activeElement": "",
            "error": str(e),
        }


def _debug_log_invite_state(driver, phase, candidate_key="", profile_name=""):
    if not DEBUG_VERBOSE:
        return
    target = candidate_key or profile_name or "unknown"
    state = _capture_invite_state(driver)
    print(Fore.CYAN + f"[DEBUG] State[{phase}] target={target}")
    print(
        Fore.CYAN
        + f"[DEBUG] URL={state.get('url','')} ready={state.get('readyState','')} "
        + f"dialogs={state.get('dialogCount','?')} modals={state.get('modalCount','?')}"
    )
    print(Fore.CYAN + f"[DEBUG] Active element: {state.get('activeElement','')}")
    if state.get("actionButtons"):
        print(Fore.CYAN + f"[DEBUG] Visible action controls: {state['actionButtons'][:15]}")
    if state.get("error"):
        print(Fore.CYAN + f"[DEBUG] State capture error: {state['error']}")


def _save_debug_artifacts(driver, phase, candidate_key="", profile_name=""):
    if not DEBUG_ARTIFACTS:
        return None
    target = candidate_key or profile_name or "unknown"
    ts = time.strftime("%Y%m%d-%H%M%S")
    base = f"{ts}_{_safe_filename_component(phase)}_{_safe_filename_component(target)}"
    os.makedirs(DEBUG_ARTIFACT_DIR, exist_ok=True)

    screenshot_path = os.path.join(DEBUG_ARTIFACT_DIR, f"{base}.png")
    html_path = os.path.join(DEBUG_ARTIFACT_DIR, f"{base}.html")
    state_path = os.path.join(DEBUG_ARTIFACT_DIR, f"{base}.json")

    try:
        driver.save_screenshot(screenshot_path)
    except Exception as e:
        screenshot_path = f"failed: {e}"

    try:
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(driver.page_source)
    except Exception as e:
        html_path = f"failed: {e}"

    try:
        state = _capture_invite_state(driver)
        with open(state_path, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception as e:
        state_path = f"failed: {e}"

    return {
        "screenshot": screenshot_path,
        "html": html_path,
        "state": state_path,
    }


def _get_shadow_root(driver: webdriver.Chrome):
    """Get the shadow root from LinkedIn's interop-shadowdom container, if present."""
    try:
        host = driver.find_element(By.CSS_SELECTOR, '#interop-outlet[data-testid="interop-shadowdom"]')
        shadow = driver.execute_script("return arguments[0].shadowRoot", host)
        return shadow
    except Exception:
        return None

def _find_in_shadow(driver: webdriver.Chrome, css_selector: str):
    """Find an element inside the interop shadow DOM. Returns element or None."""
    try:
        el = driver.execute_script("""
            var host = document.querySelector('#interop-outlet[data-testid="interop-shadowdom"]');
            if (!host || !host.shadowRoot) return null;
            return host.shadowRoot.querySelector(arguments[0]);
        """, css_selector)
        return el
    except Exception:
        return None

def _find_all_in_shadow(driver: webdriver.Chrome, css_selector: str) -> list:
    """Find all elements inside the interop shadow DOM. Returns list."""
    try:
        els = driver.execute_script("""
            var host = document.querySelector('#interop-outlet[data-testid="interop-shadowdom"]');
            if (!host || !host.shadowRoot) return [];
            return Array.from(host.shadowRoot.querySelectorAll(arguments[0]));
        """, css_selector)
        return els or []
    except Exception:
        return []

def _wait_for_invite_dialog(driver, timeout=8):
    """Wait for any LinkedIn invite modal variant to appear (including Shadow DOM)."""
    # Traditional XPaths (for older LinkedIn layouts)
    dialog_xpaths = [
        '//*[@role="dialog" or @role="alertdialog"]',
        '//*[contains(@class,"artdeco-modal")]',
        '//button[@aria-label="Add a note"]',
        '//button[normalize-space()="Add a note"]',
        '//button[.//span[normalize-space()="Add a note"]]',
        '//button[@aria-label="Send without a note"]',
        '//button[normalize-space()="Send without a note"]',
        '//button[.//span[normalize-space()="Send without a note"]]',
    ]

    end_time = time.time() + timeout
    while time.time() < end_time:
        # Check Shadow DOM first (new LinkedIn layout)
        try:
            found = driver.execute_script("""
                var host = document.querySelector('#interop-outlet[data-testid="interop-shadowdom"]');
                if (!host || !host.shadowRoot) return false;
                var sr = host.shadowRoot;
                // Look for any button/text containing "note" or "invitation"
                var allButtons = sr.querySelectorAll('button');
                for (var i = 0; i < allButtons.length; i++) {
                    var txt = (allButtons[i].textContent || '').toLowerCase();
                    if (txt.includes('add a note') || txt.includes('send without') || txt.includes('invitation')) {
                        return true;
                    }
                }
                // Also check for visible dialog-like containers
                var dialogs = sr.querySelectorAll('[role="dialog"], [role="alertdialog"], dialog');
                for (var j = 0; j < dialogs.length; j++) {
                    if (dialogs[j].offsetParent !== null || dialogs[j].open) return true;
                }
                return false;
            """)
            if found:
                if DEBUG_VERBOSE:
                    print(Fore.CYAN + "  [DEBUG] Invite dialog detected in Shadow DOM")
                return True
        except Exception:
            pass

        # Check traditional DOM
        for xpath in dialog_xpaths:
            try:
                matches = driver.find_elements(By.XPATH, xpath)
                for match in matches:
                    if match.is_displayed():
                        if DEBUG_VERBOSE:
                            print(Fore.CYAN + f"  [DEBUG] Invite dialog detected via XPath: {xpath}")
                        return True
            except Exception:
                continue
        time.sleep(0.3)

    return False


def _click_send_invite_button(driver, timeout=10):
    """Click a visible/clickable invite send button in the current modal. Returns True if clicked."""

    end_time = time.time() + timeout
    while time.time() < end_time:
        # Try Shadow DOM first
        try:
            clicked = driver.execute_script("""
                var host = document.querySelector('#interop-outlet[data-testid="interop-shadowdom"]');
                if (!host || !host.shadowRoot) return false;
                var sr = host.shadowRoot;
                var allButtons = Array.from(sr.querySelectorAll('button'));
                for (var i = 0; i < allButtons.length; i++) {
                    var txt = (allButtons[i].textContent || '').trim().toLowerCase();
                    var label = (allButtons[i].getAttribute('aria-label') || '').toLowerCase();
                    if (txt.includes('send without') || txt.includes('send invitation') ||
                        txt.includes('send invite') || txt.includes('send now') ||
                        label.includes('send without') || label.includes('send invitation')) {
                        allButtons[i].click();
                        return true;
                    }
                }
                return false;
            """)
            if clicked:
                if DEBUG_VERBOSE:
                    print(Fore.CYAN + f"  [DEBUG] Clicked send button via Shadow DOM")
                return True
        except Exception:
            pass

        # Traditional DOM XPaths
        send_xpaths = [
            '//*[@role="dialog" or @role="alertdialog"]//button[@aria-label="Send without a note"]',
            '//*[@role="dialog" or @role="alertdialog"]//button[contains(@aria-label,"Send")]',
            '//button[@aria-label="Send without a note"]',
            '//button[@aria-label="Send invitation"]',
            '//button[@aria-label="Send invite"]',
            '//button[@aria-label="Send now"]',
        ]
        for xpath in send_xpaths:
            try:
                btns = driver.find_elements(By.XPATH, xpath)
            except:
                continue

            for btn in btns:
                try:
                    if btn.is_displayed() and btn.is_enabled():
                        if DEBUG_VERBOSE:
                            btn_label = (btn.get_attribute("aria-label") or btn.text or "").strip()
                            print(Fore.CYAN + f"[DEBUG] Clicking send button via XPath: {xpath} | {btn_label}")
                        driver.execute_script("arguments[0].click();", btn)
                        return True
                except Exception:
                    continue
        time.sleep(0.2)

    _debug_log_invite_state(driver, phase="send_button_not_found")
    return False


def _send_note_in_dialog(driver, name, letter):
    """Fill in the note textarea and click Send inside an open dialog. Returns True if sent.
    Handles both traditional DOM dialogs and LinkedIn's new Shadow DOM dialogs."""

    first_name = name.split()[0] if name.strip() else name
    personalized_letter = letter.replace("{name}", first_name).replace("{fullName}", name)

    # ── Try Shadow DOM path first (new LinkedIn layout) ──
    shadow_result = driver.execute_script("""
        var host = document.querySelector('#interop-outlet[data-testid="interop-shadowdom"]');
        if (!host || !host.shadowRoot) return {found: false};
        var sr = host.shadowRoot;

        // Find all buttons in shadow root
        var allButtons = Array.from(sr.querySelectorAll('button'));
        var addNoteBtn = null;
        var sendWithoutBtn = null;
        for (var i = 0; i < allButtons.length; i++) {
            var txt = (allButtons[i].textContent || '').trim().toLowerCase();
            if (txt.includes('add a note') && !addNoteBtn) addNoteBtn = allButtons[i];
            if (txt.includes('send without') && !sendWithoutBtn) sendWithoutBtn = allButtons[i];
        }

        if (addNoteBtn) {
            return {found: true, hasAddNote: true};
        }
        // If textarea is already visible (no "Add a note" button needed)
        var textarea = sr.querySelector('textarea');
        if (textarea) {
            return {found: true, hasTextarea: true};
        }
        return {found: false};
    """)

    if shadow_result and shadow_result.get("found"):
        if DEBUG_VERBOSE:
            print(Fore.CYAN + f"  [DEBUG] Using Shadow DOM path for note dialog")

        if shadow_result.get("hasAddNote"):
            # Click "Add a note" button inside shadow DOM
            driver.execute_script("""
                var host = document.querySelector('#interop-outlet[data-testid="interop-shadowdom"]');
                var sr = host.shadowRoot;
                var allButtons = Array.from(sr.querySelectorAll('button'));
                for (var i = 0; i < allButtons.length; i++) {
                    var txt = (allButtons[i].textContent || '').trim().toLowerCase();
                    if (txt.includes('add a note')) {
                        allButtons[i].click();
                        break;
                    }
                }
            """)
            time.sleep(1.5)  # increased: some profiles need more time for textarea to appear

        # Find and fill textarea in shadow DOM
        textarea_filled = driver.execute_script("""
            var host = document.querySelector('#interop-outlet[data-testid="interop-shadowdom"]');
            var sr = host.shadowRoot;
            var textarea = sr.querySelector('textarea');
            if (!textarea) return false;
            textarea.focus();
            textarea.value = arguments[0];
            textarea.dispatchEvent(new Event('input', {bubbles: true}));
            textarea.dispatchEvent(new Event('change', {bubbles: true}));
            return true;
        """, personalized_letter)

        if not textarea_filled:
            if DEBUG_VERBOSE:
                print(Fore.CYAN + f"  [DEBUG] Could not find textarea in Shadow DOM after clicking Add a note")
            # Fall through to traditional DOM path
        else:
            time.sleep(0.3)
            # Click Send button in shadow DOM
            send_clicked = driver.execute_script("""
                var host = document.querySelector('#interop-outlet[data-testid="interop-shadowdom"]');
                var sr = host.shadowRoot;
                var allButtons = Array.from(sr.querySelectorAll('button'));
                for (var i = 0; i < allButtons.length; i++) {
                    var txt = (allButtons[i].textContent || '').trim().toLowerCase();
                    var label = (allButtons[i].getAttribute('aria-label') || '').toLowerCase();
                    if (txt.includes('send invitation') || txt.includes('send invite') ||
                        txt.includes('send now') || label.includes('send invitation') ||
                        label.includes('send invite') || label.includes('send now')) {
                        allButtons[i].click();
                        return true;
                    }
                }
                // Fallback: look for a primary/submit-style button
                for (var j = 0; j < allButtons.length; j++) {
                    var txt2 = (allButtons[j].textContent || '').trim().toLowerCase();
                    if (txt2.includes('send') && !txt2.includes('without')) {
                        allButtons[j].click();
                        return true;
                    }
                }
                return false;
            """)
            if send_clicked:
                if DEBUG_VERBOSE:
                    print(Fore.CYAN + f"  [DEBUG] Note sent via Shadow DOM")
                return True
            else:
                if DEBUG_VERBOSE:
                    print(Fore.CYAN + f"  [DEBUG] Could not find Send button in Shadow DOM")

    # ── Traditional DOM path (older LinkedIn layout) ──
    textarea = None
    try:
        t = driver.find_element(By.XPATH, '//*[@role="dialog" or @role="alertdialog"]//textarea')
        if t.is_displayed():
            textarea = t
    except Exception:
        pass

    if not textarea:
        # Click "Add a note" button
        add_note_clicked = False
        for xpath in [
            '//*[@role="dialog" or @role="alertdialog"]//button[@aria-label="Add a note"]',
            '//button[@aria-label="Add a note"]',
            '//button[normalize-space()="Add a note"]',
            '//button[.//span[normalize-space()="Add a note"]]',
        ]:
            try:
                btn = WebDriverWait(driver, 3).until(EC.element_to_be_clickable((By.XPATH, xpath)))
                driver.execute_script("arguments[0].click();", btn)
                add_note_clicked = True
                time.sleep(1)
                break
            except Exception:
                continue

        if not add_note_clicked:
            return False

        for selector in [
            '//*[@role="dialog" or @role="alertdialog"]//textarea',
            '//textarea',
        ]:
            try:
                textarea = WebDriverWait(driver, 5).until(EC.presence_of_element_located((By.XPATH, selector)))
                break
            except Exception:
                continue

    if not textarea:
        return False

    try:
        textarea.clear()
        textarea.send_keys(personalized_letter)
        time.sleep(0.5)
    except Exception as e:
        print(Fore.YELLOW + f"[WARNING] Could not type message: {e}")
        return False

    for xpath in [
        '//*[@role="dialog" or @role="alertdialog"]//button[@aria-label="Send invitation"]',
        '//*[@role="dialog" or @role="alertdialog"]//button[contains(@aria-label,"Send")]',
        '//button[@aria-label="Send invitation"]',
        '//button[@aria-label="Send invite"]',
        '//button[@aria-label="Send now"]',
        '//button[.//span[normalize-space()="Send invitation"]]',
    ]:
        try:
            send_btn = WebDriverWait(driver, 8).until(EC.element_to_be_clickable((By.XPATH, xpath)))
            driver.execute_script("arguments[0].click();", send_btn)
            return True
        except Exception:
            continue

    return False


def _click_connect_on_profile(driver: webdriver.Chrome, name: str = "") -> bool:
    """Click the Connect button on a profile page. Returns True if clicked."""
    # Build name-specific XPaths first (most reliable — targets the right person)
    name_xpaths = []
    if name:
        # LinkedIn uses "Invite {Full Name} to connect" as aria-label
        name_xpaths = [
            f'//a[contains(@aria-label,"Invite {name}") and contains(@aria-label,"connect")]',
            f'//button[contains(@aria-label,"Invite {name}") and contains(@aria-label,"connect")]',
        ]

    # Generic profile-section-scoped XPaths (avoid sidebar "More profiles for you")
    profile_section_xpaths = [
        '//*[contains(@class,"pv-top-card")]//a[.//span[text()="Connect"]]',
        '//*[contains(@class,"pv-top-card")]//button[.//span[text()="Connect"]]',
        '//*[contains(@class,"profile-action")]//a[.//span[text()="Connect"]]',
        '//*[contains(@class,"profile-action")]//button[.//span[text()="Connect"]]',
        '//*[contains(@class,"pvs-profile-actions")]//a[.//span[text()="Connect"]]',
        '//*[contains(@class,"pvs-profile-actions")]//button[.//span[text()="Connect"]]',
    ]

    # Fallback: generic but use first match (profile's own button comes first in DOM)
    fallback_xpaths = [
        '//button[@aria-label="Connect"]',
        '(//a[contains(@aria-label,"to connect")])[1]',
        '(//main//*[.//span[text()="Connect"] and (self::a or self::button)])[1]',
    ]

    for xpath in name_xpaths + profile_section_xpaths + fallback_xpaths:
        try:
            btn = WebDriverWait(driver, 3).until(EC.element_to_be_clickable((By.XPATH, xpath)))
            if DEBUG_VERBOSE:
                tag = btn.tag_name
                label = btn.get_attribute("aria-label") or btn.text or ""
                print(Fore.CYAN + f"  [DEBUG] Clicking Connect via <{tag}> aria-label=\"{label.strip()}\"")
            driver.execute_script("arguments[0].click();", btn)
            return True
        except Exception:
            continue

    # Connect hidden under "More actions" dropdown
    try:
        more = WebDriverWait(driver, 3).until(
            EC.element_to_be_clickable((By.XPATH, '//button[contains(@aria-label,"More actions")]'))
        )
        driver.execute_script("arguments[0].click();", more)
        time.sleep(1)
        for xpath in [
            '//div[@role="option"]//span[text()="Connect"]/..',
            '//li//span[text()="Connect"]/ancestor::button',
            '//*[contains(@class,"dropdown")]//span[text()="Connect"]/ancestor::button',
            '//*[@role="listbox"]//span[text()="Connect"]/..',
        ]:
            try:
                opt = WebDriverWait(driver, 3).until(EC.element_to_be_clickable((By.XPATH, xpath)))
                driver.execute_script("arguments[0].click();", opt)
                return True
            except Exception:
                continue
    except Exception:
        pass

    return False


def send_connection_to_profile(driver, profile_url, letter, include_notes, require_note=False, known_name=""):
    """
    Navigate to a LinkedIn profile page, extract the first name,
    click Connect, and (if include_notes) add the personalised note before sending.
    Returns (sent: bool, name: str). If require_note=True, only returns True when
    note is successfully added and sent.
    known_name: name already extracted from search results — used as fallback if profile h1 fails.
    """
    driver.get(profile_url)
    time.sleep(1.5)

    # Check if already connected / pending
    try:
        page_src = driver.page_source
        if 'Pending' in page_src or 'Message' in page_src[:5000]:
            # May already be connected or request pending – check carefully
            pass
    except Exception:
        pass

    name = get_name_from_profile_page(driver)
    if not name:
        # Prefer the name from search results over the URL slug
        name = known_name or profile_url.rstrip('/').split('/')[-1].replace('-', ' ').title()

    if not _click_connect_on_profile(driver, name=name):
        print(Fore.YELLOW + f"[WARNING] Could not find Connect button on profile: {profile_url}")
        return False, name

    time.sleep(1)

    # Check if LinkedIn sent the invite immediately (no dialog) by looking for "Pending" state
    # Scope to profile-specific elements to avoid matching sidebar "Pending" for other people
    try:
        pending_xpaths = []
        if name:
            pending_xpaths.append(f'//*[contains(@aria-label,"Pending") and contains(@aria-label,"{name}")]')
        pending_xpaths += [
            '//*[contains(@class,"pv-top-card")]//*[.//span[text()="Pending"] and (self::a or self::button)]',
            '//*[contains(@class,"pvs-profile-actions")]//*[.//span[text()="Pending"] and (self::a or self::button)]',
            '//*[contains(@class,"profile-action")]//*[.//span[text()="Pending"] and (self::a or self::button)]',
        ]
        for xp in pending_xpaths:
            matches = driver.find_elements(By.XPATH, xp)
            if any(m.is_displayed() for m in matches):
                if DEBUG_VERBOSE:
                    print(Fore.CYAN + f"  [DEBUG] Invite sent immediately (no dialog) — button changed to Pending")
                if require_note:
                    print(Fore.YELLOW + f"[WARNING] Invite sent without note for {name} (LinkedIn skipped dialog). Counting as sent.")
                return True, name
    except Exception:
        pass

    # Wait for dialog
    dialog_appeared = _wait_for_invite_dialog(driver, timeout=8)

    if not dialog_appeared:
        # Strict mode: only count as sent when invite is explicitly submitted via dialog
        print(Fore.YELLOW + f"[WARNING] No dialog after clicking Connect for {name}. Not counted in strict mode.")
        return False, name

    if require_note:
        if not include_notes or not (letter or "").strip():
            print(Fore.YELLOW + f"[WARNING] Note-required mode enabled, but note message is empty for {name}.")
            return False, name

        sent = _send_note_in_dialog(driver, name, letter)
        if sent:
            return True, name

        print(Fore.YELLOW + f"[WARNING] Could not add/send note for {name}. Not sent in note-required mode.")
        # Dismiss dialog (Shadow DOM or traditional)
        try:
            driver.execute_script("""
                var host = document.querySelector('#interop-outlet[data-testid="interop-shadowdom"]');
                if (host && host.shadowRoot) {
                    var btn = host.shadowRoot.querySelector('button[aria-label="Dismiss"]');
                    if (btn) { btn.click(); return; }
                }
                var dismiss = document.querySelector('button[aria-label="Dismiss"]');
                if (dismiss) dismiss.click();
            """)
        except Exception:
            pass
        return False, name

    if include_notes and letter:
        sent = _send_note_in_dialog(driver, name, letter)
        if sent:
            return True, name
        # Fall back to sending without note only when note is not required
        print(Fore.YELLOW + f"[WARNING] Could not add note for {name}. Sending without note.")

    # Send without note
    for xpath in [
        '//*[@role="dialog"]//button[@aria-label="Send without a note"]',
        '//*[@role="dialog"]//button[@aria-label="Send now"]',
        '//*[@role="dialog"]//button[@aria-label="Send invite"]',
        '//*[@role="dialog"]//button[contains(@aria-label,"without")]',
        '//*[@role="dialog"]//button[contains(@aria-label,"Send")]',
    ]:
        try:
            btn = WebDriverWait(driver, 3).until(EC.element_to_be_clickable((By.XPATH, xpath)))
            driver.execute_script("arguments[0].click();", btn)
            return True, name
        except Exception:
            continue

    return False, name


def send_connection_request(driver: webdriver.Chrome, limit: int, letter: str, include_notes: bool, message_letter: str):
    """Send connection requests / messages up to `limit` total."""
    try:
        time.sleep(2)
        actions = ActionChains(driver)
        connections_sent = 0
        page_num = 1
        search_url = driver.current_url  # saved for returning after profile visits

        while connections_sent < limit:
            print(Fore.CYAN + f"\n[INFO] ── Page {page_num} ──")

            if message_letter != "":
                # ── 1st degree: send a message ──────────────────────────────
                msg_buttons = collect_message_buttons(driver)
                print(f"[INFO] Found {len(msg_buttons)} Message buttons on page {page_num}")
                if not msg_buttons:
                    if not navigate_to_next_page(driver, page_num):
                        print(Fore.YELLOW + "[INFO] No more pages.")
                        break
                    page_num += 1
                    time.sleep(2)
                    continue

                for btn in msg_buttons:
                    if connections_sent >= limit:
                        break
                    try:
                        actions.move_to_element(btn).perform()
                        time.sleep(0.5)
                        driver.execute_script("arguments[0].click();", btn)
                        time.sleep(2)

                        message_box = WebDriverWait(driver, 5).until(
                            EC.presence_of_element_located((By.XPATH, "//div[@role='textbox']"))
                        )
                        message_box.clear()
                        message_box.send_keys(message_letter)
                        time.sleep(0.5)
                        send_btn = WebDriverWait(driver, 5).until(
                            EC.element_to_be_clickable((By.XPATH, '//button[text()="Send"]'))
                        )
                        send_btn.click()
                        time.sleep(1)
                        try:
                            close_btn = WebDriverWait(driver, 5).until(
                                EC.element_to_be_clickable((By.XPATH,
                                    "//button[contains(@class,'msg-overlay-bubble-header__control')]"
                                ))
                            )
                            close_btn.click()
                        except Exception:
                            pass
                        connections_sent += 1
                        print(Fore.GREEN + f"[INFO] Message sent ({connections_sent}/{limit})")
                        print("─" * 80)
                        time.sleep(3)
                    except Exception as e:
                        print(Fore.YELLOW + f"[WARNING] Could not send message: {e}")
                        try:
                            driver.find_element(By.XPATH, "//button[@aria-label='Dismiss']").click()
                        except Exception:
                            pass
                        continue

            else:
                # ── 2nd/3rd degree: guaranteed-note mode via profile pages ─
                if not include_notes or not (letter or "").strip():
                    print(Fore.RED + "[ERROR] Guaranteed-note mode requires a non-empty connection_message with include_note=True.")
                    break

                page_candidates = collect_connect_elements(driver)
                print(f"[INFO] Found {len(page_candidates)} Connect buttons on page {page_num}")

                if not page_candidates:
                    print(Fore.YELLOW + f"[WARNING] No Connect buttons on page {page_num}.")
                else:
                    attempted_on_page = set()
                    for elem_info in page_candidates:
                        if connections_sent >= limit:
                            break

                        name = (elem_info.get('name') or "").strip()
                        profile_url = (elem_info.get('profile_url') or "").strip()
                        label = ""
                        try:
                            label = (elem_info['element'].get_attribute("aria-label") or "").strip()
                        except Exception:
                            pass
                        candidate_key = profile_url or name or label
                        if not candidate_key or candidate_key in attempted_on_page:
                            continue
                        attempted_on_page.add(candidate_key)

                        if not profile_url:
                            print(Fore.YELLOW + f"[WARNING] Missing profile URL for {name or candidate_key}. Skipping (cannot guarantee note).")
                            continue

                        print(Fore.CYAN + f"[INFO] Opening profile for note-required invite: {name or profile_url}")
                        sent_profile, resolved_name = send_connection_to_profile(
                            driver=driver,
                            profile_url=profile_url,
                            letter=letter,
                            include_notes=True,
                            require_note=True,
                            known_name=name,
                        )

                        if sent_profile:
                            connections_sent += 1
                            display_name = (resolved_name or name or profile_url).strip()
                            print(Fore.GREEN + f"[INFO] ✓ Sent with note to {display_name} ({connections_sent}/{limit})")
                        else:
                            print(Fore.YELLOW + f"[WARNING] ✗ Could not send note-required invite to {name or profile_url}")
                            artifact_paths = _save_debug_artifacts(
                                driver, phase="profile_note_required_failed", candidate_key=candidate_key, profile_name=name
                            )
                            if artifact_paths:
                                print(Fore.CYAN + f"[DEBUG] Failure artifacts: {artifact_paths}")

                        print("─" * 80)
                        time.sleep(2)  # rate-limit between requests

            if connections_sent >= limit:
                break

            # ── Navigate to next page ────────────────────────────────────────
            # Ensure we are on the search page before paginating
            if "search/results" not in driver.current_url:
                driver.get(search_url)
                time.sleep(2)

            if not navigate_to_next_page(driver, page_num):
                print(Fore.YELLOW + "[INFO] No more pages. Stopping.")
                break

            page_num += 1
            search_url = driver.current_url if "search/results" in driver.current_url else search_url
            time.sleep(2)

        print(Fore.GREEN + f"\n[INFO] Done — sent {connections_sent}/{limit} connection requests.")

    except Exception as e:
        print(Fore.RED + f"[ERROR] send_connection_request: {e}")
        traceback.print_exc()

def main():
    # Check if input config file exists
    if not os.path.exists(input_config_file):
        create_default_input_config()
        print(Fore.YELLOW + f"[INFO] Created default input configuration file: {input_config_file}")
        print(Fore.YELLOW + f"[INFO] Please edit {input_config_file} with your search criteria and run the script again.")
        return

    # Read input configuration
    input_config.read(input_config_file)
    
    driver = None
    
    try:
        # Get search criteria from input config
        connection_degree = input_config.get('SearchCriteria', 'connection_degree')
        keyword = input_config.get('SearchCriteria', 'keyword')
        location = input_config.get('SearchCriteria', 'location')
        location_code_mapping = {
            'united states': '103644278',
            'india': '102713980',
            'canada': '101174742',
            'united kingdom': '102264111',
            'australia': '102300403',
            'germany': '101282230'  # Added Germany
        }
        location_code = location_code_mapping.get(location.lower(), '')
        limit = input_config.getint('SearchCriteria', 'limit')
        li_at = input_config.get('LinkedIn', 'li_at')
        if not li_at or li_at.strip() == 'YOUR_LI_AT_COOKIE_HERE':
            print(Fore.RED + "[ERROR] li_at cookie is not set in input_config.ini.")
            print(Fore.YELLOW + "[INFO] See README for how to get your li_at cookie from Chrome DevTools.")
            return

        # Get the actively_hiring parameter if it exists
        actively_hiring = input_config.get('SearchCriteria', 'actively_hiring', fallback='Any job title')
        
        # Check for message options
        message_letter = ''
        include_note = False
        message = ''
        
        if connection_degree.lower() == '1st':
            if input_config.has_option('Messages', 'message_letter'):
                message_letter = input_config.get('Messages', 'message_letter')
        
        if message_letter == "":
            if input_config.has_option('Messages', 'include_note'):
                include_note = input_config.getboolean('Messages', 'include_note')
                if include_note and input_config.has_option('Messages', 'connection_message'):
                    message = input_config.get('Messages', 'connection_message')
                    if len(message) > 300:
                        print(Fore.RED + f"[ERROR] connection_message is {len(message)} characters — LinkedIn limit is 300. Please shorten it before running.")
                        sys.exit(1)

        # Display the loaded configuration
        print(Fore.CYAN + "[-] Using the following search criteria from input_config.ini:")
        print(Fore.MAGENTA + f"[+] Connection degree: {connection_degree}")
        print(Fore.MAGENTA + f"[+] Keyword: {keyword}")
        print(Fore.MAGENTA + f"[+] Location: {location}")
        if actively_hiring:
            print(Fore.MAGENTA + f"[+] Actively Hiring: {actively_hiring}")
        print(Fore.MAGENTA + f"[+] Maximum connection requests: {limit}")
        print(Fore.MAGENTA + f"[+] Debug verbose: {DEBUG_VERBOSE}")
        print(Fore.MAGENTA + f"[+] Debug artifacts: {DEBUG_ARTIFACTS} ({DEBUG_ARTIFACT_DIR})")
        if connection_degree.lower() == '1st' and message_letter:
            print(Fore.MAGENTA + f"[+] Using message for 1st connections")
        elif include_note:
            print(Fore.MAGENTA + f"[+] Including note with connection requests")
            print(Fore.MAGENTA + "[+] Mode: Guaranteed-note (opens profiles for 2nd/3rd and sends only if note is added)")
        print("----------------------------------------------------------------")
        
        driver = setup_driver()

        try:
            login_with_cookie(driver, li_at)
        except Exception as e:
            print(Fore.RED + f"[INFO] Cookie login failed: {e}\n" + Fore.YELLOW + "Attempting login with credentials.")
            # Check if setup.ini exists and has LinkedIn credentials
            if os.path.exists(config_file) and config.has_section('LinkedIn') and config.has_option('LinkedIn', 'email') and config.has_option('LinkedIn', 'password'):
                email = config.get('LinkedIn', 'email')
                password = config.get('LinkedIn', 'password')
                login_with_credentials(driver, email, password)
            else:
                print(Fore.RED + "[ERROR] No valid login credentials found in setup.ini")
                print(Fore.YELLOW + "Please add your LinkedIn email and password to setup.ini or provide a valid li_at cookie in input_config.ini")
                return
        
        network_mapping = {
            "1st": "%5B%22F%22%5D",  
            "2nd": "%5B%22S%22%5D",  
            "3rd": "%5B%22O%22%5D"   
        }
        network_code = network_mapping.get(connection_degree.lower(), "")
        if not network_code:
            print(Fore.YELLOW + f"[WARNING] Invalid connection degree '{connection_degree}'. Using default (2nd).")
            network_code = "%5B%22S%22%5D"

        # Build the search URL
        search_url = f"https://www.linkedin.com/search/results/people/?keywords={keyword.replace(' ','%20').lower()}"
        
        if location_code:
            search_url += f"&geoUrn=%5B%22{location_code}%22%5D"
        elif location:
            search_url += f"&locations={location.replace(' ','%20')}"
        
        # Add network code
        search_url += f"&network={network_code}"
        
        # Add actively hiring filter according to new LinkedIn URL pattern
        if actively_hiring:
            if actively_hiring.lower() in ['any job', 'any job title']:
                # -100 is LinkedIn's internal code that represents "Any job title"
                search_url += "&activelyHiringForJobTitles=%5B%22-100%22%5D"
            else:
                # Keep generic actively hiring flag and pass the text in the title parameter as before
                search_url += "&facetActivelyHiring=true"
                search_url += f"&title={actively_hiring.replace(' ','%20')}"
        
        search_url += "&origin=FACETED_SEARCH"
        
        print(Fore.YELLOW + f"[INFO] Navigating to search URL: {search_url}")
        driver.get(search_url)
        time.sleep(1.5)  # let LinkedIn settle before checking state
        current_url = driver.current_url
        if "authwall" in current_url or "/login" in current_url or "checkpoint" in current_url:
            print(Fore.RED + "[ERROR] LinkedIn redirected to a login/verification page.")
            print(Fore.YELLOW + "[INFO] To fix: Open LinkedIn in Chrome, open DevTools (F12) > Application > Cookies, copy the 'li_at' value and update input_config.ini")
            return
        if "challenge" in current_url or "captcha" in current_url:
            print(Fore.RED + "[ERROR] LinkedIn is showing a CAPTCHA/challenge page.")
            print(Fore.YELLOW + "[INFO] Complete the challenge manually in the browser window, then re-run the script.")
            return
        if "search/results" not in current_url:
            print(Fore.RED + f"[ERROR] Unexpected page after search navigation. Current URL: {current_url}")
            return
        print(Fore.GREEN + "[INFO] Search results page loaded successfully.")
        
        if location != "" and not location_code:
            select_location(driver, location)
            
        send_connection_request(driver=driver, limit=limit, letter=message, include_notes=include_note, message_letter=message_letter)
        print(Fore.GREEN + "[INFO] Script completed successfully!")
        
    except Exception as e:
        print(Fore.RED + f"[ERROR] An error occurred in the main function: {e}")
        traceback.print_exc()
    finally:
        if driver:
            print(Fore.YELLOW + "[INFO] Closing browser...")
            driver.quit()

def create_default_input_config():
    """Create a default input configuration file"""
    input_config = ConfigParser()
    
    input_config['SearchCriteria'] = {
        'connection_degree': '2nd',
        'keyword': 'software engineer',
        'location': 'United States',
        'actively_hiring': 'Any job title',
        'limit': '10'
    }
    
    input_config['LinkedIn'] = {
        'li_at': 'YOUR_LI_AT_COOKIE_HERE'
    }
    
    input_config['Messages'] = {
        'include_note': 'True',
        'connection_message': 'Hi {name}, I noticed your profile and would like to connect. Best regards.',
        'message_letter': ''
    }
    
    with open(input_config_file, 'w') as f:
        input_config.write(f)

if __name__ == "__main__":
    try:
        print(Fore.CYAN + "LinkedIn Auto Connector")
        print(Fore.CYAN + "=====================")
        main()
    except KeyboardInterrupt:
        print(Fore.YELLOW + "\n[INFO] Script terminated by user.")
    except Exception as e:
        print(Fore.RED + f"[ERROR] Unhandled exception: {e}")
        traceback.print_exc()
    finally:
        print(Fore.GREEN + "[INFO] Script execution completed.")
