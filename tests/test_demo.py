"""GTK auto-correction tests on an owned display, optionally with the real model."""
import os
import threading
import time
import unittest
from backend import model_path, server
from core import Corrector, SurroundingContext
from demo import DemoWindow
from gi.repository import Gdk, GLib


def pump_until(predicate, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        while GLib.MainContext.default().pending():
            GLib.MainContext.default().iteration(False)
        if predicate():
            return
        time.sleep(0.005)
    raise AssertionError("Timed out waiting for GTK auto-correction")


def editor_text(window):
    buffer = window.editor.get_buffer()
    return buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), True)


class DemoTests(unittest.TestCase):
    def setUp(self):
        self.window = DemoWindow(lambda text, context: text.replace("dise", "diese"))
        self.window.show_all()

    def tearDown(self):
        self.window.destroy()

    def test_pause_auto_applies_without_preview_or_repeat(self):
        window = self.window
        window.editor.get_buffer().set_text("dise Nachricht")
        started = time.monotonic()
        self.assertEqual(editor_text(window), "dise Nachricht")
        pump_until(lambda: editor_text(window) == "diese Nachricht")
        self.assertGreater(time.monotonic() - started, 0.70)
        self.assertIsNone(window.debounce.timer)
        self.assertFalse(hasattr(window, "result"))
        self.assertFalse(hasattr(window, "accept"))

    def test_escape_cancels_pending_auto_correction(self):
        window = self.window
        window.editor.get_buffer().set_text("dise")
        event = Gdk.Event.new(Gdk.EventType.KEY_PRESS)
        event.keyval = Gdk.KEY_Escape
        self.assertFalse(window.key(window.editor, event))
        self.assertIsNone(window.debounce.timer)
        self.assertEqual(editor_text(window), "dise")

    def test_typing_during_inference_prevents_stale_auto_correction(self):
        gate, started = threading.Event(), threading.Event()
        def correct(text, context):
            started.set()
            gate.wait(timeout=2)
            return "old correction"
        self.window.debounce.correct = correct
        self.window.editor.get_buffer().set_text("old text")
        pump_until(started.is_set)
        self.window.editor.get_buffer().set_text("new text")
        gate.set()
        pump_until(lambda: not self.window.debounce.busy)
        self.assertEqual(editor_text(self.window), "new text")

    @unittest.skipUnless(os.environ.get("PROOFREAD_TEST_MODEL") == "1", "Opt-in real GPU model test")
    def test_real_gemma(self):
        self.window.destroy()
        with server(model_path()) as (url, key):
            window = self.window = DemoWindow(Corrector(url, key))
            window.show_all()
            window.editor.get_buffer().set_text("Ich habe dise Nachicht geschriben.")
            started = time.monotonic()
            pump_until(lambda: editor_text(window) == "Ich habe diese Nachricht geschrieben.", timeout=60)
            print(f"Real Gemma GTK auto-correction: {time.monotonic() - started:.2f}s including debounce")
            corrected = Corrector(url, key)(
                "ich habe eine nachricht Geschrieben.",
                SurroundingContext("Vorher stand: alles ist gut. ", " Danach geht es weiter."),
            )
            self.assertEqual(corrected, "Ich habe eine Nachricht geschrieben.")
            boundary = Corrector(url, key)(
                "ich komme morgen. ", SurroundingContext("Das war gut.", ""),
            )
            self.assertEqual(boundary, " Ich komme morgen. ")
            question = Corrector(url, key)("Ist dise Nachicht richtig?")
            self.assertEqual(question, "Ist diese Nachricht richtig?")


if __name__ == "__main__":
    unittest.main()
