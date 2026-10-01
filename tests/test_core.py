import queue
import threading
import unittest
from core import Debouncer


class Harness:
    def __init__(self, correct=lambda text: text + "!"):
        self.timers = {}
        self.next_id = 0
        self.callbacks = queue.Queue()
        self.shown = []
        self.controller = Debouncer(self.schedule, self.timers.pop, self.callbacks.put, correct,
                                    lambda *args: self.shown.append(args))

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
        self.assertEqual(h.controller.suggestion, "ab!")

    def test_stale_result_is_discarded_even_when_text_returns_to_same_value(self):
        h = Harness()
        h.controller.change("a")
        h.fire()
        h.controller.change("b")
        h.controller.change("a")
        h.finish()
        self.assertIsNone(h.controller.suggestion)

    def test_focus_loss_discards_result(self):
        h = Harness()
        h.controller.change("text")
        h.fire()
        h.controller.invalidate()
        h.finish()
        self.assertIsNone(h.controller.suggestion)

    def test_only_latest_debounced_request_is_queued(self):
        gate = threading.Event()
        calls = []

        def correct(text):
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
        self.assertEqual(h.controller.suggestion, "c!")

    def test_error_preserves_original(self):
        def fail(text):
            raise RuntimeError("offline")
        h = Harness(fail)
        h.controller.change("original")
        h.fire()
        h.finish()
        self.assertEqual(h.controller.text, "original")
        self.assertIsNone(h.controller.suggestion)
        self.assertIn("failed", h.shown[-1][1])

    def test_empty_and_oversized_text_do_not_run_inference(self):
        h = Harness()
        for text in ("", "   ", "a" * 1201):
            h.controller.change(text)
            self.assertFalse(h.timers)

    def test_no_change_is_not_a_suggestion(self):
        h = Harness(lambda text: text)
        h.controller.change("fine")
        h.fire()
        h.finish()
        self.assertIsNone(h.controller.suggestion)
        self.assertIn("No correction", h.shown[-1][1])


if __name__ == "__main__":
    unittest.main()
