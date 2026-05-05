"""Tab panel builders for the main window.

Each panel is a mixin that contributes a ``_build_*_tab`` method to
``PathSafeWindow``. Panels are kept as mixins (rather than free
``QWidget`` subclasses) so that the many cross-panel attribute
references (``self.input_edit``, ``self.tabs``, etc.) keep working
without parameter passing.
"""
