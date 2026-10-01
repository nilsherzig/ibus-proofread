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
            "import logging; logging.basicConfig(level=logging.DEBUG); "
            "from engine import run_engine; "
            "run_engine(lambda t, c: t.replace('dise', 'diese') + "
            "(' [context]' if c.before == 'Vorher. ' and c.after == ' Nachher.' else ''))",
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
                                          IBus.Capabilite.AUXILIARY_TEXT | IBus.Capabilite.FOCUS |
                                          IBus.Capabilite.SURROUNDING_TEXT))
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

    def test_pause_auto_commits_without_preview_or_tab(self):
        self.type("dise Nachricht")
        self.assertFalse(self.commits)
        started = time.monotonic()
        wait_until(lambda: bool(self.commits))
        self.assertGreater(time.monotonic() - started, 0.70)
        self.assertEqual(self.commits, ["diese Nachricht"])
        self.assertFalse(self.candidates)

    def test_shift_question_mark_keeps_sentence_in_one_composition(self):
        self.type("Ist dise Nachricht richtig")
        self.assertFalse(self.key(IBus.KEY_Shift_L))
        self.assertFalse(self.commits)
        self.assertTrue(self.key(IBus.KEY_question, IBus.ModifierType.SHIFT_MASK))
        self.assertFalse(self.key(IBus.KEY_Shift_L, IBus.ModifierType.RELEASE_MASK))
        self.assertFalse(self.commits)
        wait_until(lambda: bool(self.commits))
        self.assertEqual(self.commits, ["Ist diese Nachricht richtig?"])

    def test_shift_capital_letter_keeps_words_in_one_composition(self):
        self.type("dise ")
        self.assertFalse(self.key(IBus.KEY_Shift_R))
        self.assertTrue(self.key(IBus.KEY_N, IBus.ModifierType.SHIFT_MASK))
        self.assertFalse(self.key(IBus.KEY_Shift_R, IBus.ModifierType.RELEASE_MASK))
        self.type("achricht")
        self.assertFalse(self.commits)
        wait_until(lambda: bool(self.commits))
        self.assertEqual(self.commits, ["diese Nachricht"])

    def test_modifier_classification_does_not_include_text_or_navigation(self):
        from engine import is_modifier_key
        for keyval in (IBus.KEY_Shift_L, IBus.KEY_Control_R, IBus.KEY_Caps_Lock,
                       IBus.KEY_ISO_Level3_Shift, IBus.KEY_ISO_Level5_Lock,
                       IBus.KEY_Mode_switch, IBus.KEY_Num_Lock):
            self.assertTrue(is_modifier_key(keyval))
        for keyval in (IBus.KEY_a, IBus.KEY_question, IBus.KEY_Tab, IBus.KEY_Left,
                       IBus.KEY_BackSpace, IBus.KEY_F1, IBus.KEY_Return):
            self.assertFalse(is_modifier_key(keyval))

    def test_modifier_keys_alone_do_not_commit_composition(self):
        self.type("dise")
        for keyval, state in (
            (IBus.KEY_Shift_L, 0), (IBus.KEY_Shift_R, IBus.ModifierType.SHIFT_MASK),
            (IBus.KEY_Caps_Lock, IBus.ModifierType.LOCK_MASK),
            (IBus.KEY_ISO_Level3_Shift, IBus.ModifierType.MOD5_MASK),
            (IBus.KEY_Control_L, IBus.ModifierType.CONTROL_MASK),
            (IBus.KEY_Alt_L, IBus.ModifierType.MOD1_MASK),
            (IBus.KEY_Super_L, IBus.ModifierType.MOD4_MASK),
        ):
            with self.subTest(keyval=keyval):
                self.assertFalse(self.key(keyval, state))
                self.assertFalse(self.commits)
        self.assertTrue(self.key(IBus.KEY_period))
        wait_until(lambda: bool(self.commits))
        self.assertEqual(self.commits, ["diese."])

    def test_actual_control_shortcut_still_commits_original(self):
        self.type("dise")
        self.assertFalse(self.key(IBus.KEY_Control_L))
        self.assertFalse(self.commits)
        self.assertFalse(self.key(IBus.KEY_x, IBus.ModifierType.CONTROL_MASK))
        wait_until(lambda: bool(self.commits))
        self.assertEqual(self.commits, ["dise"])

    def test_navigation_still_commits_original(self):
        self.type("dise")
        self.assertFalse(self.key(IBus.KEY_Left))
        wait_until(lambda: bool(self.commits))
        self.assertEqual(self.commits, ["dise"])

    def test_unchanged_text_also_auto_commits(self):
        self.type("Nachricht")
        wait_until(lambda: bool(self.commits))
        self.assertEqual(self.commits, ["Nachricht"])
        self.assertFalse(self.candidates)

    def test_enter_commits_original(self):
        self.type("dise Nachricht")
        self.assertFalse(self.key(IBus.KEY_Return))
        wait_until(lambda: bool(self.commits))
        self.assertEqual(self.commits, ["dise Nachricht"])

    def test_password_field_passes_keys_through(self):
        self.context.set_content_type(IBus.InputPurpose.PASSWORD, 0)
        self.assertFalse(self.key(IBus.KEY_a))
        self.assertFalse(self.commits)
        self.assertFalse(self.candidates)

    def test_surrounding_text_reaches_inference_without_being_replaced(self):
        wait_until(lambda: self.context.needs_surrounding_text())
        self.context.set_surrounding_text(IBus.Text.new_from_string("Vorher.  Nachher."), 8, 8)
        self.type("dise")
        wait_until(lambda: bool(self.commits))
        self.assertEqual(self.commits, ["diese [context]"])
        self.assertFalse(self.candidates)

    def test_field_entry_and_type_decisions_are_logged_without_text(self):
        self.context.set_content_type(IBus.InputPurpose.URL, IBus.InputHints.NO_SPELLCHECK)
        self.assertFalse(self.key(IBus.KEY_a))
        self.engine_log.seek(0)
        output = self.engine_log.read().decode()
        self.assertIn("Field entered:", output)
        self.assertIn("type missing (not reported yet)", output)
        self.assertIn("purpose=url", output)
        self.assertIn("BYPASS", output)
        self.assertNotIn("dise", output)

    def test_special_field_types_pass_keys_through(self):
        for purpose in (IBus.InputPurpose.URL, IBus.InputPurpose.EMAIL,
                        IBus.InputPurpose.DIGITS, IBus.InputPurpose.NUMBER,
                        IBus.InputPurpose.PHONE, IBus.InputPurpose.TERMINAL,
                        IBus.InputPurpose.PIN):
            with self.subTest(purpose=purpose):
                self.context.set_content_type(purpose, 0)
                self.assertFalse(self.key(IBus.KEY_a))
                self.assertFalse(self.key(IBus.KEY_Tab))
                self.assertFalse(self.commits)
                self.assertFalse(self.candidates)
        self.context.set_content_type(IBus.InputPurpose.FREE_FORM, 0)
        self.assertTrue(self.key(IBus.KEY_a))
        self.key(IBus.KEY_Return)
        wait_until(lambda: bool(self.commits))
        self.assertEqual(self.commits, ["a"])

    def test_field_hints_pass_keys_through(self):
        for hint in (IBus.InputHints.NO_SPELLCHECK, IBus.InputHints.PRIVATE,
                     IBus.InputHints.HIDDEN_TEXT):
            with self.subTest(hint=hint):
                self.context.set_content_type(IBus.InputPurpose.FREE_FORM, hint)
                self.assertFalse(self.key(IBus.KEY_a))
                self.assertFalse(self.commits)
                self.assertFalse(self.candidates)

    def test_excluding_current_field_commits_original_and_cancels_correction(self):
        self.type("dise")
        self.context.set_content_type(IBus.InputPurpose.FREE_FORM, IBus.InputHints.NO_SPELLCHECK)
        self.assertFalse(self.key(IBus.KEY_Tab))
        wait_until(lambda: bool(self.commits))
        self.assertEqual(self.commits, ["dise"])
        self.context.set_content_type(IBus.InputPurpose.FREE_FORM, IBus.InputHints.SPELLCHECK)
        self.assertTrue(self.key(IBus.KEY_a))

    def test_word_completion_hint_does_not_disable_normal_text(self):
        self.context.set_content_type(IBus.InputPurpose.FREE_FORM, IBus.InputHints.WORD_COMPLETION)
        self.type("dise")
        wait_until(lambda: bool(self.commits))
        self.assertEqual(self.commits, ["diese"])
        self.assertFalse(self.candidates)

    def test_escape_commits_original_and_passes_through(self):
        self.type("dise")
        self.assertFalse(self.key(IBus.KEY_Escape))
        wait_until(lambda: bool(self.commits))
        self.assertEqual(self.commits, ["dise"])
        self.assertFalse(self.candidates)


if __name__ == "__main__":
    unittest.main()
