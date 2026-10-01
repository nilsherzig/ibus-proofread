"""Safe standalone GTK sandbox with automatic correction and no preview."""
import logging
import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk
from core import Debouncer

logger = logging.getLogger("proofread.demo")


class DemoWindow(Gtk.Window):
    def __init__(self, correct):
        super().__init__(title="Gemma auto-correction · 800 ms")
        self.set_default_size(760, 440)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin=20)
        self.add(box)
        box.pack_start(Gtk.Label(label="Type, then pause. Corrections are applied automatically."), False, False, 0)
        self.editor = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR)
        scroll = Gtk.ScrolledWindow()
        scroll.add(self.editor)
        box.pack_start(scroll, True, True, 0)
        self.debounce = Debouncer(GLib.timeout_add, GLib.source_remove, GLib.idle_add, correct, self.apply)
        self.change_handler = self.editor.get_buffer().connect("changed", self.changed)
        self.mark_handler = self.editor.get_buffer().connect("mark-set", self.cursor_changed)
        self.editor.connect("key-press-event", self.key)
        self.editor.connect("focus-out-event", self.blur)
        self.connect("destroy", lambda *_: self.debounce.invalidate())

    def changed(self, buffer):
        self.debounce.change(buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), True))

    def cursor_changed(self, buffer, location, mark):
        if mark.get_name() in ("insert", "selection_bound"):
            self.changed(buffer)

    def blur(self, *_):
        logger.info("Editor focus lost: invalidate outstanding correction")
        self.debounce.invalidate()
        return False

    def apply(self, correction):
        buffer = self.editor.get_buffer()
        original = buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), True)
        self.debounce.invalidate()
        if correction == original:
            return
        cursor = buffer.get_iter_at_mark(buffer.get_insert()).get_offset()
        # Programmatic corrections must not recursively trigger another inference.
        buffer.handler_block(self.change_handler)
        buffer.handler_block(self.mark_handler)
        try:
            buffer.begin_user_action()
            buffer.set_text(correction)
            position = len(correction) if cursor == len(original) else min(cursor, len(correction))
            buffer.place_cursor(buffer.get_iter_at_offset(position))
            buffer.end_user_action()
        finally:
            buffer.handler_unblock(self.mark_handler)
            buffer.handler_unblock(self.change_handler)
        logger.info("Editor auto-corrected: chars=%d", len(correction))

    def key(self, widget, event):
        if event.keyval == Gdk.KEY_Escape:
            logger.info("Escape: cancel outstanding correction")
            self.debounce.invalidate()
        return False


def run_demo(correct):
    window = DemoWindow(correct)
    window.connect("destroy", Gtk.main_quit)
    window.show_all()
    Gtk.main()
