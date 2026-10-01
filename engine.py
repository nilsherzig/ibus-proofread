"""Temporary IBus engine. Composition is owned by the engine, not reconstructed."""
import logging
import gi

gi.require_version("IBus", "1.0")
from gi.repository import GLib, IBus
from core import Debouncer, MAX_CHARS, SurroundingContext, surrounding_context

ENGINE_NAME = "gemma-proofread-demo"
logger = logging.getLogger("proofread.ibus")
BYPASS_PURPOSES = {
    IBus.InputPurpose.URL, IBus.InputPurpose.EMAIL, IBus.InputPurpose.DIGITS,
    IBus.InputPurpose.NUMBER, IBus.InputPurpose.PHONE, IBus.InputPurpose.TERMINAL,
    IBus.InputPurpose.PASSWORD, IBus.InputPurpose.PIN,
}
SENSITIVE_HINTS = IBus.InputHints.PRIVATE | IBus.InputHints.HIDDEN_TEXT
BYPASS_HINTS = IBus.InputHints.NO_SPELLCHECK | SENSITIVE_HINTS


def make_engine(correct):
    class ProofreadEngine(IBus.Engine):
        __gtype_name__ = "GemmaProofreadEngine"

        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.buffer = ""
            self.bypass = False
            self.field_description = None
            self.context = SurroundingContext()
            self.context_position = None
            self.debounce = Debouncer(
                GLib.timeout_add, GLib.source_remove, GLib.idle_add, correct, self.commit,
            )

        def changed(self):
            text = IBus.Text.new_from_string(self.buffer)
            text.append_attribute(IBus.AttrType.UNDERLINE, IBus.AttrUnderline.SINGLE, 0, len(self.buffer))
            # Focus loss commits original preedit and invalidates in-flight corrections.
            self.update_preedit_text_with_mode(
                text, len(self.buffer), bool(self.buffer), IBus.PreeditFocusMode.COMMIT,
            )
            self.debounce.change(self.buffer, self.context)

        def commit(self, correction=None):
            text = self.buffer if correction is None else correction
            if text:
                logger.info("Commit %s: chars=%d", "automatic result" if correction is not None else "original", len(text))
                self.commit_text(IBus.Text.new_from_string(text))
            self.buffer = ""
            self.changed()

        def do_process_key_event(self, keyval, keycode, state):
            if state & IBus.ModifierType.RELEASE_MASK:
                return False
            if self.bypass:
                logger.debug("Key passed through: field excluded")
                return False
            if state & (IBus.ModifierType.CONTROL_MASK | IBus.ModifierType.MOD1_MASK | IBus.ModifierType.MOD4_MASK):
                self.commit()
                return False
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
            # Navigation, Delete, Tab and Escape act on original committed text.
            self.commit()
            return False

        def do_reset(self):
            self.buffer = ""
            self.changed()

        def do_enable(self):
            self.get_surrounding_text()  # Ask the client to provide context updates.

        def do_focus_in(self):
            logger.info("Field entered: %s", self.field_description or "type missing (not reported yet)")
            if not self.bypass:
                self.get_surrounding_text()

        def do_set_surrounding_text(self, text, cursor, anchor):
            if self.bypass:
                logger.debug("Ignore surrounding text: field excluded")
                return
            try:
                context = surrounding_context(text.get_text(), cursor, anchor)
            except ValueError:
                logger.warning("Ignore invalid surrounding-text positions")
                context = SurroundingContext()
            position = (cursor, anchor, context)
            if position == self.context_position:
                return
            self.context, self.context_position = context, position
            logger.debug("Context changed: before=%d after=%d cursor=%d anchor=%d",
                         len(context.before), len(context.after), cursor, anchor)
            if self.buffer:
                self.debounce.change(self.buffer, context)

        def do_set_capabilities(self, capabilities):
            logger.info("Client supports surrounding text: %s",
                        bool(capabilities & IBus.Capabilite.SURROUNDING_TEXT))

        def do_focus_out(self):
            logger.info("Focus lost: discard outstanding results")
            # The input context commits preedit according to COMMIT mode.
            self.buffer = ""
            self.context = SurroundingContext()
            self.context_position = None
            self.field_description = None
            self.bypass = False
            self.debounce.invalidate()

        def do_disable(self):
            self.do_focus_out()

        def do_set_content_type(self, purpose, hints):
            sensitive = purpose in (IBus.InputPurpose.PASSWORD, IBus.InputPurpose.PIN)
            sensitive = sensitive or bool(hints & SENSITIVE_HINTS)
            bypass = purpose in BYPASS_PURPOSES or bool(hints & BYPASS_HINTS)
            try:
                purpose_name = IBus.InputPurpose(purpose).value_nick
            except ValueError:
                purpose_name = str(purpose)
            hint_names = ",".join(IBus.InputHints(hints).value_nicks) or "none"
            self.field_description = f"purpose={purpose_name} hints={hint_names} (reported)"
            logger.info("Field purpose=%s hints=%s: %s", purpose_name, hint_names,
                        "BYPASS" if bypass else "proofreading enabled")
            if bypass:
                self.context = SurroundingContext()
                self.context_position = None
                if sensitive:
                    self.do_reset()
                else:
                    # A field can change its hints while composing. Keep original
                    # input, never silently discard it or apply a pending correction.
                    self.commit()
            self.bypass = bypass
            if not bypass:
                self.get_surrounding_text()

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
        ENGINE_NAME, "Gemma proofreading demo", "800 ms local automatic spelling correction",
        "de", "MIT", "", "", "de",
    ))
    if not bus.register_component(component):
        raise RuntimeError("IBus component registration failed")
    activation_errors = []

    def activated(bus, result, _):
        try:
            if not bus.set_global_engine_async_finish(result):
                raise RuntimeError("Could not activate demo input method")
            logger.info("Demo engine active: automatic correction after pause, Ctrl+C stops")
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
                logger.info("Restoring previous engine: %s", previous.get_name())
                bus.set_global_engine(previous.get_name())
