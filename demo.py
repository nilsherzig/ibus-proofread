"""Safe standalone GTK sandbox using the same debounce/inference controller."""
import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk
from core import Debouncer


class DemoWindow(Gtk.Window):
    def __init__(self, correct):
        super().__init__(title="Gemma proofreading · 800 ms")
        self.set_default_size(760, 440)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin=20)
        self.add(box)
        box.pack_start(Gtk.Label(label="Type a sentence, then pause. Tab accepts · Esc dismisses."), False, False, 0)
        self.editor = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR)
        scroll = Gtk.ScrolledWindow()
        scroll.add(self.editor)
        box.pack_start(scroll, True, True, 0)
        self.status = Gtk.Label(xalign=0)
        self.result = Gtk.Label(xalign=0, selectable=True, wrap=True)
        box.pack_start(self.status, False, False, 0)
        box.pack_start(self.result, False, False, 0)
        self.accept = Gtk.Button(label="Accept suggestion")
        self.accept.set_sensitive(False)
        self.accept.set_can_focus(False)
        self.accept.connect("clicked", lambda *_: self.apply())
        box.pack_start(self.accept, False, False, 0)
        self.debounce = Debouncer(GLib.timeout_add, GLib.source_remove, GLib.idle_add, correct, self.show_result)
        self.editor.get_buffer().connect("changed", self.changed)
        self.editor.connect("key-press-event", self.key)
        self.editor.connect("focus-out-event", self.blur)
        self.editor.get_buffer().connect("mark-set", self.cursor_changed)

    def changed(self, buffer):
        self.debounce.change(buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), True))

    def cursor_changed(self, buffer, location, mark):
        if mark.get_name() in ("insert", "selection_bound"):
            self.debounce.invalidate()
            self.show_result(None, "")
            # Reschedule for this cursor state, even if text did not change.
            self.changed(buffer)

    def blur(self, *_):
        self.debounce.invalidate()
        # Discard suggestions and in-flight results when focus leaves the editor.
        self.show_result(None, "")
        return False

    def show_result(self, suggestion, status):
        self.status.set_text(status)
        self.result.set_text(suggestion or "")
        self.accept.set_sensitive(bool(suggestion))

    def apply(self):
        suggestion = self.debounce.suggestion
        if suggestion:
            self.editor.get_buffer().set_text(suggestion)
            self.editor.grab_focus()

    def key(self, widget, event):
        if event.keyval == Gdk.KEY_Tab and self.debounce.suggestion:
            self.apply()
            return True
        if event.keyval == Gdk.KEY_Escape:
            self.debounce.invalidate()
            self.show_result(None, "Suggestion dismissed.")
            return True
        return False


def run_demo(correct):
    window = DemoWindow(correct)
    window.connect("destroy", Gtk.main_quit)
    window.show_all()
    Gtk.main()
