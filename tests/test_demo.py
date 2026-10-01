"""GTK smoke test on an owned virtual display; optionally uses the real model."""
import os
import time
import unittest
from backend import model_path, server
from core import Corrector
from demo import DemoWindow
from gi.repository import Gdk, GLib, Gtk


def pump_until(predicate, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        while GLib.MainContext.default().pending():
            GLib.MainContext.default().iteration(False)
        if predicate():
            return
        time.sleep(0.005)
    raise AssertionError("Timed out waiting for GTK suggestion")


class DemoTests(unittest.TestCase):
    def setUp(self):
        self.window = DemoWindow(lambda text: text.replace("dise", "diese"))
        self.window.show_all()

    def tearDown(self):
        self.window.destroy()

    def test_pause_accept_and_dismiss(self):
        window = self.window
        window.editor.get_buffer().set_text("dise Nachricht")
        started = time.monotonic()
        self.assertIsNone(window.debounce.suggestion)
        pump_until(lambda: window.debounce.suggestion is not None)
        self.assertGreater(time.monotonic() - started, 0.70)
        self.assertEqual(window.result.get_text(), "diese Nachricht")
        window.apply()
        buffer = window.editor.get_buffer()
        self.assertEqual(buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), True), "diese Nachricht")
        buffer.set_text("dise")
        pump_until(lambda: window.debounce.suggestion is not None)
        event = Gdk.Event.new(Gdk.EventType.KEY_PRESS)
        event.keyval = Gdk.KEY_Escape
        self.assertTrue(window.key(window.editor, event))
        self.assertIsNone(window.debounce.suggestion)
        self.assertEqual(buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), True), "dise")

    @unittest.skipUnless(os.environ.get("PROOFREAD_TEST_MODEL") == "1", "Opt-in real GPU model test")
    def test_real_gemma(self):
        self.window.destroy()
        with server(model_path()) as (url, key):
            window = self.window = DemoWindow(Corrector(url, key))
            window.show_all()
            window.editor.get_buffer().set_text("Ich habe dise Nachicht geschriben.")
            started = time.monotonic()
            pump_until(lambda: window.debounce.suggestion is not None, timeout=60)
            self.assertEqual(window.debounce.suggestion, "Ich habe diese Nachricht geschrieben.")
            print(f"Real Gemma GTK suggestion: {time.monotonic() - started:.2f}s including debounce")


if __name__ == "__main__":
    unittest.main()
