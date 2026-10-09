import os
import sys
import tempfile
import unittest
from unittest.mock import Mock, call, patch


ROOT_DIR = os.path.dirname(os.path.dirname(__file__))
SRC_DIR = os.path.join(ROOT_DIR, "src")

if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from brave_browser import create_brave_driver


class BraveBrowserTests(unittest.TestCase):
    @patch("brave_browser.webdriver.Chrome")
    @patch("brave_browser._find_brave_binary", return_value="brave.exe")
    @patch("brave_browser.Options")
    def test_uses_profile_folder_and_headless_option(
        self, options_factory, _binary, chrome
    ) -> None:
        options = Mock()
        options_factory.return_value = options
        with tempfile.TemporaryDirectory() as user_data_dir:
            profile_path = os.path.join(user_data_dir, "Default")
            os.mkdir(profile_path)

            driver = create_brave_driver(profile_path, headless=True)

        self.assertIs(driver, chrome.return_value)
        self.assertEqual(options.binary_location, "brave.exe")
        options.add_argument.assert_any_call(
            f"--user-data-dir={user_data_dir}"
        )
        options.add_argument.assert_any_call("--profile-directory=Default")
        options.add_argument.assert_any_call("--headless")
        chrome.assert_called_once_with(options=options)

    @patch("brave_browser.webdriver.Chrome")
    @patch("brave_browser._find_brave_binary", return_value="brave.exe")
    @patch("brave_browser.Options")
    def test_user_data_root_selects_default_profile(
        self, options_factory, _binary, _chrome
    ) -> None:
        options = Mock()
        options_factory.return_value = options
        with tempfile.TemporaryDirectory() as temp_dir:
            user_data_dir = os.path.join(temp_dir, "User Data")
            os.mkdir(user_data_dir)
            create_brave_driver(user_data_dir, headless=False)

        options.add_argument.assert_any_call(
            f"--user-data-dir={os.path.abspath(user_data_dir)}"
        )
        options.add_argument.assert_any_call("--profile-directory=Default")
        self.assertNotIn(call("--headless"), options.add_argument.call_args_list)

    def test_rejects_missing_profile_directory(self) -> None:
        with self.assertRaisesRegex(ValueError, "Brave profile path"):
            create_brave_driver("missing-brave-profile", headless=False)


if __name__ == "__main__":
    unittest.main()
