import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from core_loader import load_core


class CoreLoaderTests(unittest.TestCase):
    def test_ignores_stale_or_unrelated_app_module(self):
        stale = types.ModuleType("app")
        with patch.dict(sys.modules, {"app": stale}):
            core = load_core(Path(__file__).parent / "app.py")
            self.assertTrue(callable(core.stock_split_events))
            self.assertTrue(issubclass(core.SplitQuotePending, RuntimeError))
            self.assertIs(sys.modules["app"], stale)
            self.assertIs(core, load_core(Path(__file__).parent / "app.py"))

    def test_source_update_loads_new_core_without_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "app.py"
            path.write_text("VERSION = 'old'\n", encoding="utf-8")
            old = load_core(path)
            path.write_text("VERSION = 'new'\n", encoding="utf-8")
            new = load_core(path)
            self.assertEqual(old.VERSION, "old")
            self.assertEqual(new.VERSION, "new")
            self.assertIsNot(old, new)


if __name__ == "__main__":
    unittest.main()
