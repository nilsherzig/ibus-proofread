import queue
import threading
import unittest
from core import Debouncer, SurroundingContext, surrounding_context, preserve_boundary_whitespace


class Harness:
    def __init__(self, correct=lambda text, context: text + "!"):
        self.timers = {}
        self.next_id = 0
        self.callbacks = queue.Queue()
        self.applied = []
        self.controller = Debouncer(self.schedule, self.timers.pop, self.callbacks.put, correct, self.applied.append)

    def schedule(self, delay, callback):
        assert delay == 800
        self.next_id += 1
        self.timers[self.next_id] = callback
        return self.next_id

    def fire(self):
        self.timers.pop(self.controller.timer)()

    def finish(self):
        self.callbacks.get(timeout=2)()


class DebounceTests(unittest.TestCase):
    def test_typing_restarts_timer(self):
        h = Harness()
        h.controller.change("a")
        h.controller.change("ab")
        self.assertEqual(len(h.timers), 1)
        h.fire()
        h.finish()
        self.assertEqual(h.applied, ["ab!"])

    def test_stale_result_is_discarded_even_when_text_returns_to_same_value(self):
        h = Harness()
        h.controller.change("a")
        h.fire()
        h.controller.change("b")
        h.controller.change("a")
        h.finish()
        self.assertEqual(h.applied, [])

    def test_focus_loss_discards_result(self):
        h = Harness()
        h.controller.change("text")
        h.fire()
        h.controller.invalidate()
        h.finish()
        self.assertEqual(h.applied, [])

    def test_only_latest_debounced_request_is_queued(self):
        gate = threading.Event()
        calls = []

        def correct(text, context):
            calls.append(text)
            if text == "a":
                gate.wait(timeout=2)
            return text + "!"

        h = Harness(correct)
        h.controller.change("a")
        h.fire()
        h.controller.change("b")
        h.fire()
        h.controller.change("c")
        h.fire()
        gate.set()
        h.finish()
        h.finish()
        self.assertEqual(calls, ["a", "c"])
        self.assertEqual(h.applied, ["c!"])

    def test_error_preserves_original(self):
        def fail(text, context):
            raise RuntimeError("offline")
        h = Harness(fail)
        h.controller.change("original")
        h.fire()
        h.finish()
        self.assertEqual(h.controller.text, "original")
        self.assertEqual(h.applied, [])

    def test_empty_and_oversized_text_do_not_run_inference(self):
        h = Harness()
        for text in ("", "   ", "a" * 1201):
            h.controller.change(text)
            self.assertFalse(h.timers)

    def test_context_is_forwarded_and_context_change_invalidates_result(self):
        received = []
        def correct(text, context):
            received.append((text, context))
            return text + "!"
        h = Harness(correct)
        before = SurroundingContext("Previous sentence. ", " Next sentence.")
        after = SurroundingContext("Different sentence. ", " Next sentence.")
        h.controller.change("text", before)
        h.fire()
        h.controller.change("text", after)
        h.finish()
        self.assertEqual(h.applied, [])
        h.fire()
        h.finish()
        self.assertEqual(received, [("text", before), ("text", after)])
        self.assertEqual(h.applied, ["text!"])

    def test_existing_boundary_whitespace_is_preserved(self):
        self.assertEqual(preserve_boundary_whitespace(" word ", "Word"), " Word ")
        self.assertEqual(preserve_boundary_whitespace("\tword\n", " Word "), "\tWord\n")
        self.assertEqual(preserve_boundary_whitespace("word", " Word"), " Word")
        self.assertEqual(preserve_boundary_whitespace("word ", "Word   "), "Word ")

    def test_surrounding_context_is_bounded_and_excludes_selection(self):
        text = "a" * 600 + "selected" + "b" * 600
        expected = SurroundingContext("a" * 400, "b" * 400)
        self.assertEqual(surrounding_context(text, 600, 608), expected)
        self.assertEqual(surrounding_context(text, 608, 600), expected)
        self.assertEqual(surrounding_context("Grüße 🙂!", 7, 7), SurroundingContext("Grüße 🙂", "!"))
        with self.assertRaises(ValueError):
            surrounding_context("short", 6, 0)

    def test_debug_logs_explain_decisions_without_text(self):
        h = Harness()
        with self.assertLogs("proofread.debounce", level="DEBUG") as logs:
            h.controller.change("never-log-this-text")
            h.fire()
            h.finish()
        output = "\n".join(logs.output)
        self.assertIn("Debounce scheduled", output)
        self.assertIn("Inference started", output)
        self.assertIn("Apply automatically", output)
        self.assertNotIn("never-log-this-text", output)

    def test_unchanged_result_is_applied_to_finish_composition(self):
        h = Harness(lambda text, context: text)
        h.controller.change("fine")
        h.fire()
        h.finish()
        self.assertEqual(h.applied, ["fine"])


if __name__ == "__main__":
    unittest.main()
