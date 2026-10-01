"""Real D-Bus boundary test; must run under a fresh dbus-run-session."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

import gi

gi.require_version("IBus", "1.0")
from gi.repository import GLib, IBus

ROOT = Path(__file__).resolve().parents[1]


def wait_until(predicate, timeout=5):
    deadline = time.monotonic() + timeout
    context = GLib.MainContext.default()
    while time.monotonic() < deadline:
        while context.pending():
            context.iteration(False)
        if predicate():
            return
        time.sleep(0.005)
    raise AssertionError("Timed out waiting for IBus event")


class IBusIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.environ.get("PROOFREAD_TEST_PRIVATE_BUS") != "1":
            raise unittest.SkipTest("Requires isolated dbus-run-session")
        cls.tmp = tempfile.TemporaryDirectory()
        env = dict(os.environ, GIO_USE_VFS="local", IBUS_ADDRESS="unix:path=" + cls.tmp.name + "/ibus.sock",
                   XDG_CONFIG_HOME=cls.tmp.name, XDG_CACHE_HOME=cls.tmp.name,
                   DISPLAY="", WAYLAND_DISPLAY="")
        os.environ["IBUS_ADDRESS"] = env["IBUS_ADDRESS"]
        cls.daemon_log = tempfile.TemporaryFile()
        cls.daemon = subprocess.Popen([
            "ibus-daemon", "--single", "--panel", "disable", "--config", "disable",
            "--address", env["IBUS_ADDRESS"],
        ], env=env, stdout=cls.daemon_log, stderr=cls.daemon_log)
        wait_until(lambda: Path(cls.tmp.name, "ibus.sock").exists())
        IBus.init()
        cls.bus = IBus.Bus.new()
        assert cls.bus.is_connected()
        activated = []
        cls.bus.set_watch_ibus_signal(True)
        cls.bus.connect("global-engine-changed", lambda _, name: activated.append(name))
        cls.engine_log = tempfile.TemporaryFile()
        cls.engine = subprocess.Popen([
            sys.executable, "-u", "-c",
            "from engine import run_engine; run_engine(lambda t: t.replace('dise', 'diese'))",
        ], cwd=ROOT, env=env, stdout=cls.engine_log, stderr=cls.engine_log)
        try:
            wait_until(lambda: "gemma-proofread-demo" in activated)
            assert cls.bus.get_global_engine().get_name() == "gemma-proofread-demo"
        except Exception:
            cls.engine.terminate()
            cls.engine.wait()
            cls.engine_log.seek(0)
            print(cls.engine_log.read().decode(), file=sys.stderr)
            cls.daemon.terminate()
            cls.daemon.wait()
            cls.tmp.cleanup()
            raise

    @classmethod
    def tearDownClass(cls):
        cls.engine.terminate()
        cls.engine.wait(timeout=5)
        cls.daemon.terminate()
        cls.daemon.wait(timeout=5)
        cls.engine_log.close()
        cls.daemon_log.close()
        cls.tmp.cleanup()

    def setUp(self):
        self.context = self.bus.create_input_context("proofread-test")
        self.commits, self.candidates = [], []
        self.context.connect("commit-text", lambda _, text: self.commits.append(text.get_text()))
        self.context.connect("update-lookup-table", self.lookup)
        self.context.set_capabilities(int(IBus.Capabilite.PREEDIT_TEXT | IBus.Capabilite.LOOKUP_TABLE |
                                          IBus.Capabilite.AUXILIARY_TEXT | IBus.Capabilite.FOCUS))
        self.context.focus_in()
        self.context.set_engine("gemma-proofread-demo")
        wait_until(lambda: self.context.get_engine() is not None)

    def tearDown(self):
        self.context.focus_out()
        self.context.destroy()

    def lookup(self, context, table, visible):
        if visible:
            self.candidates.append(table.get_candidate(0).get_text())

    def key(self, keyval, state=0):
        done = []
        def complete(context, result, _):
            done.append(context.process_key_event_async_finish(result))
        self.context.process_key_event_async(keyval, 0, state, 2000, None, complete, None)
        wait_until(lambda: bool(done))
        return done[0]

    def type(self, text):
        for char in text:
            self.assertTrue(self.key(IBus.unicode_to_keyval(char)))

    def test_suggestion_after_pause_tab_accepts(self):
        self.type("dise Nachricht")
        self.assertFalse(self.candidates)
        started = time.monotonic()
        wait_until(lambda: bool(self.candidates))
        self.assertGreater(time.monotonic() - started, 0.70)
        self.assertEqual(self.candidates[-1], "diese Nachricht")
        self.assertTrue(self.key(IBus.KEY_Tab))
        wait_until(lambda: bool(self.commits))
        self.assertEqual(self.commits, ["diese Nachricht"])

    def test_enter_commits_original(self):
        self.type("dise Nachricht")
        wait_until(lambda: bool(self.candidates))
        self.assertFalse(self.key(IBus.KEY_Return))
        wait_until(lambda: bool(self.commits))
        self.assertEqual(self.commits, ["dise Nachricht"])

    def test_password_field_passes_keys_through(self):
        self.context.set_content_type(IBus.InputPurpose.PASSWORD, 0)
        self.assertFalse(self.key(IBus.KEY_a))
        self.assertFalse(self.commits)
        self.assertFalse(self.candidates)

    def test_escape_keeps_original(self):
        self.type("dise")
        wait_until(lambda: bool(self.candidates))
        self.assertTrue(self.key(IBus.KEY_Escape))
        self.key(IBus.KEY_Return)
        wait_until(lambda: bool(self.commits))
        self.assertEqual(self.commits, ["dise"])


if __name__ == "__main__":
    unittest.main()
