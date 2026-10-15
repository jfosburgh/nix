import importlib.util
from pathlib import Path
import tempfile
import unittest
import zipfile
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("installer", Path(__file__).with_name("install.py"))
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class InstallerTests(unittest.TestCase):
    def test_config_preserves_settings_and_is_idempotent(self):
        original = "[General]\nname=test\n[FeatureSettings]\nOther=true\nExcludeSyncFolders=existing\n[Next]\nfoo=bar\n"
        result = installer.exclude_adds(original)
        self.assertIn("Other=true", result)
        self.assertIn("(existing)|(^|/)[.]adds($|/)", result)
        self.assertTrue(result.endswith("[Next]\nfoo=bar\n"))
        self.assertEqual(installer.exclude_adds(result), result)

    def test_config_adds_section(self):
        self.assertIn("[FeatureSettings]\nExcludeSyncFolders=", installer.exclude_adds("[General]\nx=1\n"))

    def test_reject_quoted_expression(self):
        with self.assertRaises(SystemExit):
            installer.exclude_adds('[FeatureSettings]\nExcludeSyncFolders="complex"\n')

    def test_archive_traversal(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with zipfile.ZipFile(root / "bad.zip", "w") as z:
                z.writestr("bookorbit.koplugin/../../escape", "bad")
            with self.assertRaises(SystemExit):
                installer.extract_zip(root / "bad.zip", root / "out", "bookorbit.koplugin")
            self.assertFalse((root / "escape").exists())

    def test_dry_run_and_firmware_guard(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            mount = root / "kobo"
            (mount / ".kobo/Kobo").mkdir(parents=True)
            config = mount / ".kobo/Kobo/Kobo eReader.conf"
            config.write_text("[General]\nx=1\n")
            version = mount / ".kobo/version"
            version.write_text("serial,unused,4.44.23552,unused\n")
            plugin = root / "plugin.zip"
            with zipfile.ZipFile(plugin, "w") as z:
                z.writestr("bookorbit.koplugin/main.lua", "return {}")
            argv = ["installer", str(mount), "--plugin", str(plugin), "--dry-run"]
            with patch("sys.argv", argv), patch("os.path.ismount", return_value=True), patch.object(installer, "download") as download:
                installer.main()
                download.assert_not_called()
                self.assertEqual(config.read_text(), "[General]\nx=1\n")
                self.assertFalse((mount / ".adds").exists())
                version.write_text("serial,unused,5.0.1\n")
                with self.assertRaisesRegex(SystemExit, "unsupported"):
                    installer.main()


if __name__ == "__main__":
    unittest.main()
