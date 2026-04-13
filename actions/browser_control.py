import threading
import platform
import shutil
import subprocess
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.chrome.service  import Service as ChromeService
from selenium.webdriver.chrome.options  import Options as ChromeOptions
from selenium.webdriver.firefox.service import Service as FirefoxService
from selenium.webdriver.firefox.options import Options as FirefoxOptions
from selenium.webdriver.edge.service    import Service as EdgeService
from selenium.webdriver.edge.options    import Options as EdgeOptions
from selenium.webdriver.common.by            import By
from selenium.webdriver.common.keys          import Keys
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui           import WebDriverWait
from selenium.webdriver.support              import expected_conditions as EC
from webdriver_manager.chrome    import ChromeDriverManager
from webdriver_manager.firefox   import GeckoDriverManager
from webdriver_manager.microsoft import EdgeChromiumDriverManager


# ── Default-browser detection (unchanged from original) ──────────────────────

def _get_default_browser_id() -> str:
    """Returns raw default browser identifier string for current OS."""
    system = platform.system()
    try:
        if system == "Windows":
            import winreg
            key     = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\Shell\Associations\UrlAssociations\http\UserChoice"
            )
            prog_id = winreg.QueryValueEx(key, "ProgId")[0].lower()
            winreg.CloseKey(key)
            return prog_id

        elif system == "Darwin":
            result = subprocess.run(
                ["defaults", "read",
                 "com.apple.LaunchServices/com.apple.launchservices.secure",
                 "LSHandlers"],
                capture_output=True, text=True, timeout=5
            )
            return result.stdout.lower()

        elif system == "Linux":
            result = subprocess.run(
                ["xdg-settings", "get", "default-web-browser"],
                capture_output=True, text=True, timeout=5
            )
            return result.stdout.lower()

    except Exception:
        pass

    return ""


_BROWSER_BINARIES = {
    "Windows": {
        "opera":   ["opera.exe"],
        "brave":   ["brave.exe"],
        "vivaldi": ["vivaldi.exe"],
        "chrome":  ["chrome.exe"],
        "firefox": ["firefox.exe"],
    },
    "Darwin": {
        "opera":   ["opera"],
        "brave":   ["brave browser", "brave"],
        "vivaldi": ["vivaldi"],
        "chrome":  ["google chrome", "google-chrome"],
        "firefox": ["firefox"],
    },
    "Linux": {
        "opera":   ["opera", "opera-stable"],
        "brave":   ["brave-browser", "brave"],
        "vivaldi": ["vivaldi-stable", "vivaldi"],
        "chrome":  ["google-chrome", "google-chrome-stable", "chromium-browser", "chromium"],
        "firefox": ["firefox"],
    },
}


def _get_opera_executable() -> str | None:
    if platform.system() != "Windows":
        return None
    try:
        import winreg
        candidate_keys = [
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\opera.exe",
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\launcher.exe",
            r"SOFTWARE\Clients\StartMenuInternet\OperaStable\shell\open\command",
            r"SOFTWARE\Clients\StartMenuInternet\OperaGXStable\shell\open\command",
        ]
        for key_path in candidate_keys:
            for hive in [winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER]:
                try:
                    key  = winreg.OpenKey(hive, key_path)
                    val  = winreg.QueryValue(key, None)
                    winreg.CloseKey(key)
                    exe  = val.strip().strip('"').split('"')[0].split(" --")[0].strip()
                    if exe and Path(exe).exists():
                        print(f"[Browser] 🔍 Opera found via registry: {exe}")
                        return exe
                except Exception:
                    continue
    except Exception:
        pass
    return None


def _find_browser_executable(prog_id: str) -> tuple:
    system  = platform.system()
    os_bins = _BROWSER_BINARIES.get(system, {})

    if any(x in prog_id for x in ["firefox", "mozilla"]):
        return "firefox", None, None

    if "safari" in prog_id:
        return "chromium", None, None   # WebKit not supported in Selenium; fall back to Chrome

    if "edge" in prog_id:
        return "chromium", None, "msedge"

    if "opera" in prog_id:
        exe = _get_opera_executable()
        if exe:
            return "chromium", exe, None
        for binary in os_bins.get("opera", []):
            path = shutil.which(binary)
            if path:
                return "chromium", path, None

    browser_patterns = {
        "brave":   ["brave"],
        "vivaldi": ["vivaldi"],
        "chrome":  ["chrome"],
    }
    for browser_name, patterns in browser_patterns.items():
        if not any(p in prog_id for p in patterns):
            continue
        binaries = os_bins.get(browser_name, [])
        for binary in binaries:
            path = shutil.which(binary)
            if path:
                print(f"[Browser] 🔍 Found {browser_name} at: {path}")
                return "chromium", path, None

    if "chrome" in prog_id or not prog_id:
        return "chromium", None, "chrome"

    return "chromium", None, None


# ── Browser manager ───────────────────────────────────────────────────────────

class _BrowserManager:
    """
    Manages normal and incognito WebDriver instances.
    Replaces the original async _BrowserThread; Selenium is synchronous so no
    asyncio event loop is needed.
    """

    def __init__(self):
        self._lock         = threading.Lock()
        self._driver       = None   # normal browser
        self._incog_driver = None   # incognito / private browser
        self._engine_name  = "chromium"
        self._exe_path     = None
        self._channel      = None
        self._detected     = False

    # ── Detection ────────────────────────────────────────────────────────────

    def _detect(self):
        if self._detected:
            return
        prog_id = _get_default_browser_id()
        self._engine_name, self._exe_path, self._channel = _find_browser_executable(prog_id)
        self._detected = True

    # ── Liveness ─────────────────────────────────────────────────────────────

    @staticmethod
    def _alive(driver) -> bool:
        if driver is None:
            return False
        try:
            _ = driver.title
            return True
        except Exception:
            return False

    # ── Options builders ─────────────────────────────────────────────────────

    def _chrome_options(self, incognito: bool = False) -> ChromeOptions:
        opts = ChromeOptions()
        opts.add_experimental_option("excludeSwitches", ["enable-automation"])
        opts.add_experimental_option("useAutomationExtension", False)
        opts.add_argument("--start-maximized")
        opts.add_argument("--disable-blink-features=AutomationControlled")
        opts.add_argument("--disable-infobars")
        if incognito:
            opts.add_argument("--incognito")
        if self._exe_path:
            opts.binary_location = self._exe_path
        return opts

    @staticmethod
    def _firefox_options(incognito: bool = False) -> FirefoxOptions:
        opts = FirefoxOptions()
        if incognito:
            opts.set_preference("browser.privatebrowsing.autostart", True)
        return opts

    @staticmethod
    def _edge_options(incognito: bool = False) -> EdgeOptions:
        opts = EdgeOptions()
        opts.add_argument("--start-maximized")
        if incognito:
            opts.add_argument("--inprivate")
        return opts

    # ── Launch ───────────────────────────────────────────────────────────────

    def _launch(self, incognito: bool = False):
        self._detect()
        label = "incognito" if incognito else "normal"
        try:
            if self._engine_name == "firefox":
                driver = webdriver.Firefox(
                    service=FirefoxService(GeckoDriverManager().install()),
                    options=self._firefox_options(incognito=incognito),
                )
                print(f"[Browser] ✅ Firefox [{label}]")
                return driver

            if self._channel == "msedge":
                driver = webdriver.Edge(
                    service=EdgeService(EdgeChromiumDriverManager().install()),
                    options=self._edge_options(incognito=incognito),
                )
                print(f"[Browser] ✅ Edge [{label}]")
                return driver

            # Chromium-based: Chrome, Brave, Vivaldi, Opera, or fallback
            driver = webdriver.Chrome(
                service=ChromeService(ChromeDriverManager().install()),
                options=self._chrome_options(incognito=incognito),
            )
            bin_label = self._exe_path or self._channel or "Chrome"
            print(f"[Browser] ✅ {bin_label} [{label}]")
            return driver

        except Exception as e:
            print(f"[Browser] ⚠️ Launch failed ({e}), falling back to system Chrome")
            opts = ChromeOptions()
            opts.add_argument("--start-maximized")
            if incognito:
                opts.add_argument("--incognito")
            return webdriver.Chrome(
                service=ChromeService(ChromeDriverManager().install()),
                options=opts,
            )

    # ── Driver accessor ───────────────────────────────────────────────────────

    def _get_driver(self, incognito: bool = False):
        with self._lock:
            if incognito:
                if not self._alive(self._incog_driver):
                    self._incog_driver = self._launch(incognito=True)
                return self._incog_driver
            else:
                if not self._alive(self._driver):
                    self._driver = self._launch(incognito=False)
                return self._driver

    @staticmethod
    def _wait(driver, timeout: int = 10) -> WebDriverWait:
        return WebDriverWait(driver, timeout)

    # ── Actions ───────────────────────────────────────────────────────────────

    def _go_to(self, url: str, incognito: bool = False) -> str:
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        driver = self._get_driver(incognito=incognito)
        try:
            driver.get(url)
            mode = " [private]" if incognito else ""
            return f"Opened{mode}: {driver.current_url}"
        except Exception as e:
            return f"Navigation error: {e}"

    def _search(self, query: str, engine: str = "google", incognito: bool = False) -> str:
        engines = {
            "google":     f"https://www.google.com/search?q={query.replace(' ', '+')}",
            "bing":       f"https://www.bing.com/search?q={query.replace(' ', '+')}",
            "duckduckgo": f"https://duckduckgo.com/?q={query.replace(' ', '+')}",
        }
        url = engines.get(engine.lower(), engines["google"])
        return self._go_to(url, incognito=incognito)

    def _click(self, selector=None, text=None, incognito: bool = False) -> str:
        driver = self._get_driver(incognito=incognito)
        try:
            if text:
                element = self._wait(driver, 8).until(
                    EC.element_to_be_clickable(
                        (By.XPATH, f"//*[contains(text(), '{text}')]")
                    )
                )
                element.click()
                return f"Clicked: '{text}'"
            elif selector:
                element = self._wait(driver, 8).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, selector))
                )
                element.click()
                return f"Clicked: {selector}"
            return "No selector or text provided."
        except Exception as e:
            return f"Click error: {e}"

    def _type(self, selector=None, text: str = "", clear_first: bool = True, incognito: bool = False) -> str:
        driver = self._get_driver(incognito=incognito)
        try:
            if selector:
                element = self._wait(driver).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, selector))
                )
            else:
                element = driver.switch_to.active_element
            if clear_first:
                element.clear()
            element.send_keys(text)
            return "Text typed."
        except Exception as e:
            return f"Type error: {e}"

    def _scroll(self, direction: str = "down", amount: int = 500, incognito: bool = False) -> str:
        driver = self._get_driver(incognito=incognito)
        try:
            y = amount if direction == "down" else -amount
            driver.execute_script(f"window.scrollBy(0, {y});")
            return f"Scrolled {direction}."
        except Exception as e:
            return f"Scroll error: {e}"

    def _fill_form(self, fields: dict, incognito: bool = False) -> str:
        driver  = self._get_driver(incognito=incognito)
        results = []
        for selector, value in fields.items():
            try:
                element = self._wait(driver).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, selector))
                )
                element.clear()
                element.send_keys(str(value))
                results.append(f"✓ {selector}")
            except Exception as e:
                results.append(f"✗ {selector}: {e}")
        return "Form filled: " + ", ".join(results)

    def _smart_click(self, description: str, incognito: bool = False) -> str:
        driver     = self._get_driver(incognito=incognito)
        desc_lower = description.lower()

        role_hints = {
            "button":  ["button", "buton", "btn"],
            "link":    ["link", "bağlantı"],
            "search":  ["search", "arama"],
            "textbox": ["input", "field", "alan"],
        }
        for role, keywords in role_hints.items():
            if any(k in desc_lower for k in keywords):
                try:
                    element = self._wait(driver, 5).until(
                        EC.element_to_be_clickable(
                            (By.XPATH,
                             f"//*[@role='{role}' or @aria-label='{description}']")
                        )
                    )
                    element.click()
                    return f"Clicked ({role}): '{description}'"
                except Exception:
                    pass

        # Visible text
        try:
            element = self._wait(driver, 5).until(
                EC.element_to_be_clickable(
                    (By.XPATH,
                     f"//*[contains(text(), '{description}') "
                     f"or normalize-space(text())='{description}']")
                )
            )
            element.click()
            return f"Clicked (text): '{description}'"
        except Exception:
            pass

        # Placeholder / aria-label / title
        try:
            element = self._wait(driver, 5).until(
                EC.element_to_be_clickable(
                    (By.XPATH,
                     f"//*[@placeholder='{description}' "
                     f"or @aria-label='{description}' "
                     f"or @title='{description}']")
                )
            )
            element.click()
            return f"Clicked (placeholder): '{description}'"
        except Exception:
            pass

        return f"Could not find: '{description}'"

    def _smart_type(self, description: str, text: str, incognito: bool = False) -> str:
        driver     = self._get_driver(incognito=incognito)
        strategies = [
            ("placeholder",
             f"//input[@placeholder='{description}'] | //textarea[@placeholder='{description}']"),
            ("label",
             f"//input[@aria-label='{description}'] | //textarea[@aria-label='{description}']"),
            ("name",
             f"//input[@name='{description}'] | //textarea[@name='{description}']"),
            ("role",
             "//input[@type='text'] | //textarea | //input[not(@type)]"),
        ]
        for method, xpath in strategies:
            try:
                element = self._wait(driver, 5).until(
                    EC.presence_of_element_located((By.XPATH, xpath))
                )
                element.clear()
                element.send_keys(text)
                return f"Typed into ({method}): '{description}'"
            except Exception:
                continue

        return f"Could not find input: '{description}'"

    def _get_text(self, incognito: bool = False) -> str:
        driver = self._get_driver(incognito=incognito)
        try:
            text = driver.find_element(By.TAG_NAME, "body").text
            return text[:4000] if len(text) > 4000 else text
        except Exception as e:
            return f"Could not get page text: {e}"

    def _press(self, key: str, incognito: bool = False) -> str:
        driver  = self._get_driver(incognito=incognito)
        key_map = {
            "enter":     Keys.ENTER,
            "escape":    Keys.ESCAPE,
            "esc":       Keys.ESCAPE,
            "tab":       Keys.TAB,
            "backspace": Keys.BACKSPACE,
            "delete":    Keys.DELETE,
            "space":     Keys.SPACE,
            "up":        Keys.ARROW_UP,
            "down":      Keys.ARROW_DOWN,
            "left":      Keys.ARROW_LEFT,
            "right":     Keys.ARROW_RIGHT,
            "f5":        Keys.F5,
            "home":      Keys.HOME,
            "end":       Keys.END,
        }
        try:
            mapped = key_map.get(key.lower(), key)
            ActionChains(driver).send_keys(mapped).perform()
            return f"Pressed: {key}"
        except Exception as e:
            return f"Key error: {e}"

    def _close_browser(self) -> str:
        with self._lock:
            if self._incog_driver:
                try:
                    self._incog_driver.quit()
                except Exception:
                    pass
                self._incog_driver = None

            if self._driver:
                try:
                    self._driver.quit()
                except Exception:
                    pass
                self._driver = None

        return "Browser closed."


# ── Singleton ─────────────────────────────────────────────────────────────────

_bm = _BrowserManager()


# ── Public API (signature kept identical to original) ─────────────────────────

def browser_control(
    parameters:     dict,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    """
    Browser controller — auto-detects and uses system default browser.

    parameters:
        action      : go_to | search | click | type | scroll | fill_form |
                      smart_click | smart_type | get_text | press | close
        url         : URL for go_to
        query       : search query
        engine      : google | bing | duckduckgo  (default: google)
        selector    : CSS selector for click / type
        text        : text to click or type
        description : element description for smart_click / smart_type
        direction   : up | down for scroll
        amount      : scroll amount in pixels  (default: 500)
        key         : key name for press  (e.g. Enter, Escape, Tab)
        fields      : {selector: value} dict for fill_form
        clear_first : bool — clear input before typing  (default: True)
        incognito   : bool — open in private/incognito mode  (default: False)
    """
    action    = (parameters or {}).get("action", "").lower().strip()
    incognito = bool(parameters.get("incognito", False))
    result    = "Unknown action."

    try:
        if action == "go_to":
            result = _bm._go_to(parameters.get("url", ""), incognito=incognito)

        elif action == "search":
            result = _bm._search(
                parameters.get("query", ""),
                parameters.get("engine", "google"),
                incognito=incognito,
            )

        elif action == "click":
            result = _bm._click(
                selector=parameters.get("selector"),
                text=parameters.get("text"),
                incognito=incognito,
            )

        elif action == "type":
            result = _bm._type(
                selector=parameters.get("selector"),
                text=parameters.get("text", ""),
                clear_first=parameters.get("clear_first", True),
                incognito=incognito,
            )

        elif action == "scroll":
            result = _bm._scroll(
                direction=parameters.get("direction", "down"),
                amount=parameters.get("amount", 500),
                incognito=incognito,
            )

        elif action == "fill_form":
            result = _bm._fill_form(
                parameters.get("fields", {}),
                incognito=incognito,
            )

        elif action == "smart_click":
            result = _bm._smart_click(
                parameters.get("description", ""),
                incognito=incognito,
            )

        elif action == "smart_type":
            result = _bm._smart_type(
                parameters.get("description", ""),
                parameters.get("text", ""),
                incognito=incognito,
            )

        elif action == "get_text":
            result = _bm._get_text(incognito=incognito)

        elif action == "press":
            result = _bm._press(
                parameters.get("key", "Enter"),
                incognito=incognito,
            )

        elif action == "close":
            result = _bm._close_browser()

        else:
            result = f"Unknown action: {action}"

    except Exception as e:
        result = f"Browser error: {e}"

    print(f"[Browser] {result[:80]}")
    if player:
        player.write_log(f"[browser] {result[:60]}")

    return result
