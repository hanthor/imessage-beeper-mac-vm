"""_vnc_connect must not pick its port-file name with tempfile.mktemp.

mktemp returns a name without creating the file, so another local user can
create that name (or a symlink to it) before virtctl writes the port into it.
"""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts", "console"))
import driver  # noqa: E402


class VncPortfileTest(unittest.TestCase):
    def test_port_file_is_created_without_mktemp(self):
        seen = {}

        def fake_popen(argv, stdout=None, stderr=None):
            seen["path"] = stdout.name
            stdout.write(json.dumps({"port": 5901}) + "\n")
            stdout.flush()
            return mock.Mock()

        with mock.patch.object(tempfile, "mktemp",
                               side_effect=AssertionError("mktemp is racy")), \
             mock.patch.object(driver.subprocess, "Popen", side_effect=fake_popen), \
             mock.patch.object(driver.time, "sleep"), \
             mock.patch.object(driver.socket, "create_connection",
                               return_value=mock.Mock()):
            driver._vnc_connect()

        self.assertIn("path", seen)
        self.assertFalse(os.path.exists(seen["path"]),
                         "port file should be removed after it is read")


if __name__ == "__main__":
    unittest.main()


class BeeperScriptsTmpPathTest(unittest.TestCase):
    def test_beeper_scripts_do_not_use_fixed_tmp_paths(self):
        # The shell scripts cannot run without a Mac VM, so guard the pattern
        # the finding is about: any literal /tmp/ path in a beeper script.
        folder = os.path.join(ROOT, "scripts", "beeper")
        for name in sorted(os.listdir(folder)):
            if not name.endswith(".sh"):
                continue
            with open(os.path.join(folder, name)) as f:
                for lineno, line in enumerate(f, 1):
                    self.assertNotIn("/tmp/", line,
                                     f"{name}:{lineno} uses a fixed /tmp path")
