"""Temporary IBus engine. Composition is owned by the engine, not reconstructed."""
import gi

gi.require_version("IBus", "1.0")
from gi.repository import GLib, IBus
from core import Debouncer, MAX_CHARS

ENGINE_NAME = "gemma-proofread-demo"


def make_engine(correct):
    class ProofreadEngine(IBus.Engine):
        __gtype_name__ = "GemmaProofreadEngine"

        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.buffer = ""
            self.private = False
            self.debounce = Debouncer(
                GLib.timeout_add, GLib.source_remove, GLib.idle_add, correct, self.show,
            )

        def show(self, suggestion, status):
            self.update_auxiliary_text(IBus.Text.new_from_string(status), bool(status))
            table = IBus.LookupTable.new(1, 0, False, False)
            if suggestion:
                table.append_candidate(IBus.Text.new_from_string(suggestion))
            self.update_lookup_table(table, bool(suggestion))

        def changed(self):
            text = IBus.Text.new_from_string(self.buffer)
            text.append_attribute(IBus.AttrType.UNDERLINE, IBus.AttrUnderline.SINGLE, 0, len(self.buffer))
            # Commit original preedit on focus loss; never commit an unconfirmed suggestion.
            self.update_preedit_text_with_mode(
                text, len(self.buffer), bool(self.buffer), IBus.PreeditFocusMode.COMMIT,
            )
            self.debounce.change(self.buffer)

        def commit(self, corrected=False):
            text = self.debounce.suggestion if corrected else self.buffer
            if text:
                self.commit_text(IBus.Text.new_from_string(text))
            self.buffer = ""
            self.changed()

        def do_process_key_event(self, keyval, keycode, state):
            if state & IBus.ModifierType.RELEASE_MASK:
                return False
            if self.private:
                return False
            if state & (IBus.ModifierType.CONTROL_MASK | IBus.ModifierType.MOD1_MASK | IBus.ModifierType.MOD4_MASK):
                self.commit()
                return False
            if keyval in (IBus.KEY_Tab, IBus.KEY_ISO_Left_Tab) and self.debounce.suggestion:
                self.commit(corrected=True)
                return True
            if keyval == IBus.KEY_Escape and self.buffer:
                self.debounce.invalidate()
                self.show(None, "Suggestion dismissed; Enter commits the original.")
                return True
            if keyval in (IBus.KEY_Return, IBus.KEY_KP_Enter):
                self.commit()
                return False
            if keyval == IBus.KEY_BackSpace and self.buffer:
                self.buffer = self.buffer[:-1]
                self.changed()
                return True
            char = IBus.keyval_to_unicode(keyval)
            if char and char.isprintable():
                if len(self.buffer) >= MAX_CHARS:
                    self.commit()
                self.buffer += char
                self.changed()
                return True
            # Navigation, Delete, Tab without suggestion, etc. act on committed text.
            self.commit()
            return False

        def do_candidate_clicked(self, index, button, state):
            if index == 0 and button == 1 and self.debounce.suggestion:
                self.commit(corrected=True)

        def do_reset(self):
            self.buffer = ""
            self.changed()

        def do_focus_out(self):
            # The input context commits preedit according to COMMIT mode.
            self.buffer = ""
            self.debounce.invalidate()
            self.show(None, "")

        def do_disable(self):
            self.do_focus_out()

        def do_set_content_type(self, purpose, hints):
            private = purpose in (IBus.InputPurpose.PASSWORD, IBus.InputPurpose.PIN)
            private = private or bool(hints & IBus.InputHints.PRIVATE)
            if private:
                self.do_reset()
            self.private = private

    return ProofreadEngine


def run_engine(correct):
    IBus.init()
    bus = IBus.Bus.new()
    if not bus.is_connected():
        raise RuntimeError("No IBus session bus. Run this inside your GNOME session.")
    previous = bus.get_global_engine()
    loop = GLib.MainLoop()
    bus.connect("disconnected", lambda *_: loop.quit())
    factory = IBus.Factory.new(bus.get_connection())
    factory.add_engine(ENGINE_NAME, make_engine(correct).__gtype__)
    component = IBus.Component.new(
        "org.freedesktop.IBus.GemmaProofreadDemo", "Local Gemma proofreading demo",
        "0.1", "MIT", "", "", "", "",
    )
    component.add_engine(IBus.EngineDesc.new(
        ENGINE_NAME, "Gemma proofreading demo", "800 ms local spelling suggestions",
        "de", "MIT", "", "", "de",
    ))
    if not bus.register_component(component):
        raise RuntimeError("IBus component registration failed")
    activation_errors = []

    def activated(bus, result, _):
        try:
            if not bus.set_global_engine_async_finish(result):
                raise RuntimeError("Could not activate demo input method")
            print("IBus demo active. Tab accepts a suggestion; Enter commits original. Ctrl+C here stops.")
        except Exception as exc:
            activation_errors.append(exc)
            loop.quit()

    # Factory CreateEngine requests need the main loop; synchronous activation
    # would block the very process that must answer those D-Bus requests.
    bus.set_global_engine_async(ENGINE_NAME, 5000, None, activated, None)
    try:
        loop.run()
        if activation_errors:
            raise activation_errors[0]
    finally:
        if previous and bus.is_connected():
            current = bus.get_global_engine()
            if current and current.get_name() == ENGINE_NAME:
                bus.set_global_engine(previous.get_name())
