import os
import platform

from selenium import webdriver
from selenium.webdriver.chrome.options import Options


def _find_brave_binary() -> str:
    if platform.system() == "Windows":
        candidates = [
            os.path.join(os.environ.get("PROGRAMFILES", ""), "BraveSoftware", "Brave-Browser", "Application", "brave.exe"),
            os.path.join(os.environ.get("PROGRAMFILES(X86)", ""), "BraveSoftware", "Brave-Browser", "Application", "brave.exe"),
            os.path.join(os.environ.get("LOCALAPPDATA", ""), "BraveSoftware", "Brave-Browser", "Application", "brave.exe"),
        ]
    elif platform.system() == "Darwin":
        candidates = [
            "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
            os.path.expanduser("~/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"),
        ]
    else:
        candidates = [
            "/usr/bin/brave-browser",
            "/usr/bin/brave",
            "/snap/bin/brave",
            "/opt/brave.com/brave/brave",
        ]

    for candidate in candidates:
        if candidate and os.path.isfile(candidate):
            return candidate

    raise FileNotFoundError(
        "Brave Browser executable was not found. Install Brave or update its path "
        "in src/brave_browser.py."
    )


def create_brave_driver(profile_path: str, headless: bool) -> webdriver.Chrome:
    expanded_path = os.path.abspath(
        os.path.expandvars(os.path.expanduser(profile_path.strip()))
    )
    if not os.path.isdir(expanded_path):
        raise ValueError(
            f"Brave profile path does not exist or is not a directory: {profile_path}"
        )

    if os.path.basename(expanded_path).lower() == "user data":
        user_data_dir = expanded_path
        profile_name = "Default"
    else:
        user_data_dir = os.path.dirname(expanded_path)
        profile_name = os.path.basename(expanded_path)

    options = Options()
    options.binary_location = _find_brave_binary()
    options.add_argument(f"--user-data-dir={user_data_dir}")
    options.add_argument(f"--profile-directory={profile_name}")
    if headless:
        options.add_argument("--headless")

    return webdriver.Chrome(options=options)
