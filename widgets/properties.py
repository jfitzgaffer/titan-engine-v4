"""
PropertiesPanel — ParameterSet editor for the selected Clip.

Each parameter row has:
  [☑ checkbox]  [label]  [spinbox]

Checkbox checked  → this clip owns the value; spinbox is editable.
Checkbox unchecked → value is None (inherits from SubTrack/Track); spinbox
                     is disabled and shows the resolved inherited value in gray.
"""
from dataclasses import fields as dc_fields

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QCheckBox, QDoubleSpinBox, QScrollArea, QFrame, QSizePolicy,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont

from models.project import ParameterSet, resolve_params


# (display_label, min, max, single_step, decimals)
_FIELD_META = {
    "dim":          ("Dim",         0.0,   1.0,    0.01, 3),
    "r":            ("R",           0.0, 255.0,    1.0,  1),
    "g":            ("G",           0.0, 255.0,    1.0,  1),
    "b":            ("B",           0.0, 255.0,    1.0,  1),
    "w":            ("W",           0.0, 255.0,    1.0,  1),
    "effect_width": ("Width",       0.01,  1.0,   0.01,  3),
    "x_position":   ("X Pos",       0.0,   1.0,   0.01,  3),
    "atk_c":        ("Atk C",       0.0,  30.0,   0.05,  3),
    "dec_c":        ("Dec C",       0.0,  30.0,   0.05,  3),
    "sus_c":        ("Sus C",       0.0,   1.0,   0.01,  3),
    "rel_c":        ("Rel C",       0.0,  30.0,   0.05,  3),
    "atk_e":        ("Atk E",       0.0,  30.0,   0.05,  3),
    "dec_e":        ("Dec E",       0.0,  30.0,   0.05,  3),
    "sus_e":        ("Sus E",       0.0,   1.0,   0.01,  3),
    "rel_e":        ("Rel E",       0.0,  30.0,   0.05,  3),
    "glitch_digi":  ("Dig Glitch",  0.0,   1.0,   0.01,  3),
    "glitch_ana":   ("Ana Glitch",  0.0,   1.0,   0.01,  3),
    "overdrive":    ("Overdrive",   0.0,   1.0,   0.01,  3),
    "knee":         ("Knee",        0.0,   0.5,   0.01,  3),
    "eq_tilt":      ("EQ Tilt",    -1.0,   1.0,   0.05,  3),
}

_GROUPS = [
    ("Color",             ["dim", "r", "g", "b", "w"]),
    ("Spatial",           ["effect_width", "x_position"]),
    ("Envelope — Center", ["atk_c", "dec_c", "sus_c", "rel_c"]),
    ("Envelope — Edge",   ["atk_e", "dec_e", "sus_e", "rel_e"]),
    ("FX",                ["glitch_digi", "glitch_ana", "overdrive", "knee", "eq_tilt"]),
]

_LABEL_STYLE  = "color: #aaa; font-size: 11px; border: none; min-width: 72px;"
_HEADER_STYLE = "color: #666; font-size: 10px; border: none; margin-top: 6px;"
_TITLE_STYLE  = "color: #ccc; font-size: 12px; font-weight: bold; border: none;"
_SPIN_ENABLED  = "QDoubleSpinBox { background: #2a2a2a; color: white; border: 1px solid #555; padding: 1px 4px; }"
_SPIN_DISABLED = "QDoubleSpinBox { background: #222; color: #555; border: 1px solid #333; padding: 1px 4px; }"


class _ParamRow(QWidget):
    """One parameter: checkbox + label + spinbox."""

    def __init__(self, field_name: str):
        super().__init__()
        self.field_name = field_name
        self._params: ParameterSet | None = None
        self._loading = False

        meta = _FIELD_META.get(field_name, (field_name, 0.0, 1.0, 0.01, 3))
        label_text, mn, mx, step, decimals = meta

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 1, 0, 1)
        row.setSpacing(4)

        self.chk = QCheckBox()
        self.chk.setFixedWidth(16)
        self.chk.setToolTip("Checked = own value  |  Unchecked = inherit from track")

        lbl = QLabel(label_text)
        lbl.setStyleSheet(_LABEL_STYLE)

        self.spin = QDoubleSpinBox()
        self.spin.setRange(mn, mx)
        self.spin.setSingleStep(step)
        self.spin.setDecimals(decimals)
        self.spin.setFixedWidth(80)
        self.spin.setStyleSheet(_SPIN_DISABLED)

        row.addWidget(self.chk)
        row.addWidget(lbl)
        row.addWidget(self.spin)
        row.addStretch()

        self.chk.toggled.connect(self._on_toggle)
        self.spin.valueChanged.connect(self._on_value)

    def load(self, params: ParameterSet, resolved_val=None):
        self._params = params
        self._loading = True
        val = getattr(params, self.field_name)
        has_own = val is not None

        self.chk.setChecked(has_own)
        self.spin.setEnabled(has_own)
        self.spin.setStyleSheet(_SPIN_ENABLED if has_own else _SPIN_DISABLED)

        display = val if has_own else (resolved_val or 0.0)
        self.spin.setValue(display if display is not None else 0.0)
        self._loading = False

    def _on_toggle(self, checked: bool):
        if self._loading or self._params is None:
            return
        if checked:
            setattr(self._params, self.field_name, self.spin.value())
        else:
            setattr(self._params, self.field_name, None)
        self.spin.setEnabled(checked)
        self.spin.setStyleSheet(_SPIN_ENABLED if checked else _SPIN_DISABLED)

    def _on_value(self, val: float):
        if self._loading or self._params is None:
            return
        if self.chk.isChecked():
            setattr(self._params, self.field_name, val)


class PropertiesPanel(QWidget):
    """
    Shows and edits the ParameterSet of the selected Clip.
    Call show_clip(clip, subtrack, track) when selection changes.
    Call clear() to collapse when nothing is selected.
    """

    def __init__(self):
        super().__init__()
        self._clip = None
        self._rows: dict[str, _ParamRow] = {}

        self.setStyleSheet("background: #1e1e1e; border-top: 1px solid #333;")
        self.setMinimumHeight(0)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 6, 12, 6)
        outer.setSpacing(0)

        # Title row
        self._title = QLabel("No clip selected")
        self._title.setStyleSheet(_TITLE_STYLE)
        outer.addWidget(self._title)

        # Scrollable content
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")

        content = QWidget()
        content.setStyleSheet("background: transparent;")
        self._content_layout = QVBoxLayout(content)
        self._content_layout.setContentsMargins(0, 4, 0, 4)
        self._content_layout.setSpacing(0)

        # Build all rows up-front (hidden until a clip is selected)
        for group_label, field_names in _GROUPS:
            hdr = QLabel(group_label.upper())
            hdr.setStyleSheet(_HEADER_STYLE)
            self._content_layout.addWidget(hdr)

            grid = QWidget()
            grid_layout = QHBoxLayout(grid)
            grid_layout.setContentsMargins(0, 0, 0, 0)
            grid_layout.setSpacing(0)

            col_widgets = [[], [], []]
            for i, name in enumerate(field_names):
                row = _ParamRow(name)
                self._rows[name] = row
                col_widgets[i % 3].append(row)

            for col in col_widgets:
                col_vbox = QVBoxLayout()
                col_vbox.setContentsMargins(0, 0, 8, 0)
                col_vbox.setSpacing(0)
                for w in col:
                    col_vbox.addWidget(w)
                grid_layout.addLayout(col_vbox)

            self._content_layout.addWidget(grid)

        self._content_layout.addStretch()
        scroll.setWidget(content)
        outer.addWidget(scroll, stretch=1)

        self._set_visible(False)

    def _set_visible(self, visible: bool):
        for row in self._rows.values():
            row.setVisible(visible)

    def show_clip(self, clip, subtrack=None, track=None):
        """Load clip's ParameterSet into the editor. Pass subtrack+track for resolved hints."""
        self._clip = clip

        # Compute resolved values for inherit hints
        resolved = None
        if subtrack is not None and track is not None:
            resolved = resolve_params(clip, subtrack, track)

        self._title.setText(
            f"Clip  ·  start {clip.start:.2f}s  ·  dur {clip.duration:.2f}s"
        )

        for name, row in self._rows.items():
            resolved_val = getattr(resolved, name) if resolved else None
            row.load(clip.params, resolved_val)

        self._set_visible(True)

    def clear(self):
        self._clip = None
        self._title.setText("No clip selected")
        self._set_visible(False)
