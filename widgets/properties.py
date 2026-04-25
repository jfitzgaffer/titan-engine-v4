"""
PropertiesPanel — editor for the selected Clip.

Layout (top to bottom):
  • Timing row:      [Clip label]  Start: [spinbox]  Dur: [spinbox]
  • Instances:       INSTANCES  N  [+] [−]
                     #1  X: [spin]  W: [spin]
                     #2  X: [spin]  W: [spin]  …
  • Parameter groups: Color / Spatial / Envelope-C / Envelope-E / FX
    Each field: [☑] label [spinbox]
    Checked = own value; unchecked = inherit from track (shown gray).

Signals:
  params_changed      — any value changed; connect to live-preview slot
  clip_layout_changed — start / duration / pixel list changed;
                        connect to timeline.refresh()
"""
from dataclasses import fields as dc_fields

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QCheckBox, QDoubleSpinBox, QScrollArea, QFrame,
    QPushButton,
)
from PySide6.QtCore import Qt, Signal

from models.project import ParameterSet, VirtualPixel, resolve_params


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

_LABEL_STYLE   = "color: #aaa; font-size: 11px; border: none; min-width: 52px;"
_HEADER_STYLE  = "color: #666; font-size: 10px; border: none; margin-top: 6px;"
_TITLE_STYLE   = "color: #ccc; font-size: 12px; font-weight: bold; border: none;"
_SPIN_ENABLED  = "QDoubleSpinBox { background: #2a2a2a; color: white; border: 1px solid #555; padding: 1px 4px; }"
_SPIN_DISABLED = "QDoubleSpinBox { background: #222; color: #555; border: 1px solid #333; padding: 1px 4px; }"
_SPIN_TIME     = ("QDoubleSpinBox { background: #2a2a2a; color: #00ff66; "
                  "border: 1px solid #555; padding: 1px 4px; min-width: 62px; }")
_BTN_STYLE     = ("QPushButton { background: #2e2e2e; color: white; border: 1px solid #555; "
                  "border-radius: 3px; font-size: 12px; min-width: 22px; min-height: 18px; padding: 0 4px; }"
                  "QPushButton:hover { background: #3e3e3e; }"
                  "QPushButton:pressed { background: #1a1a1a; }")

_MAX_PIXELS = 8   # pre-allocated pixel rows


class _PixelRow(QWidget):
    """One VirtualPixel: index label + X spinbox + Width spinbox."""

    changed = Signal()

    def __init__(self, idx: int):
        super().__init__()
        self._pixel: VirtualPixel | None = None
        self._loading = False

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 1, 0, 1)
        row.setSpacing(4)

        num = QLabel(f"#{idx + 1}")
        num.setStyleSheet("color: #666; font-size: 10px; border: none; min-width: 20px;")

        x_lbl = QLabel("X")
        x_lbl.setStyleSheet("color: #aaa; font-size: 11px; border: none; min-width: 14px;")
        self.x_spin = QDoubleSpinBox()
        self.x_spin.setRange(0.0, 1.0)
        self.x_spin.setSingleStep(0.05)
        self.x_spin.setDecimals(3)
        self.x_spin.setFixedWidth(72)
        self.x_spin.setStyleSheet(_SPIN_ENABLED)

        w_lbl = QLabel("W")
        w_lbl.setStyleSheet("color: #aaa; font-size: 11px; border: none; min-width: 14px;")
        self.w_spin = QDoubleSpinBox()
        self.w_spin.setRange(0.01, 1.0)
        self.w_spin.setSingleStep(0.05)
        self.w_spin.setDecimals(3)
        self.w_spin.setFixedWidth(72)
        self.w_spin.setStyleSheet(_SPIN_ENABLED)

        row.addWidget(num)
        row.addWidget(x_lbl)
        row.addWidget(self.x_spin)
        row.addWidget(w_lbl)
        row.addWidget(self.w_spin)
        row.addStretch()

        self.x_spin.valueChanged.connect(self._on_x)
        self.w_spin.valueChanged.connect(self._on_w)

    def load(self, pixel: VirtualPixel):
        self._pixel = pixel
        self._loading = True
        self.x_spin.setValue(pixel.x)
        self.w_spin.setValue(pixel.width)
        self._loading = False

    def _on_x(self, val: float):
        if not self._loading and self._pixel:
            self._pixel.x = val
            self.changed.emit()

    def _on_w(self, val: float):
        if not self._loading and self._pixel:
            self._pixel.width = val
            self.changed.emit()


class _ParamRow(QWidget):
    """One parameter: checkbox + label + spinbox."""

    changed = Signal()

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
        setattr(self._params, self.field_name, self.spin.value() if checked else None)
        self.spin.setEnabled(checked)
        self.spin.setStyleSheet(_SPIN_ENABLED if checked else _SPIN_DISABLED)
        self.changed.emit()

    def _on_value(self, val: float):
        if not self._loading and self._params and self.chk.isChecked():
            setattr(self._params, self.field_name, val)
            self.changed.emit()


class PropertiesPanel(QWidget):
    """
    Shows and edits the selected Clip: timing, pixel instances, and ParameterSet.

    params_changed      — any value written; connect to live-preview slot
    clip_layout_changed — start/duration or pixel list changed;
                          connect to timeline.refresh()
    """

    params_changed      = Signal()
    clip_layout_changed = Signal()

    def __init__(self):
        super().__init__()
        self._clip = None
        self._rows: dict[str, _ParamRow] = {}
        self._pixel_rows: list[_PixelRow] = []
        self._loading = False

        self.setStyleSheet("background: #1e1e1e; border-top: 1px solid #333;")
        self.setMinimumHeight(0)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 6, 12, 6)
        outer.setSpacing(0)

        # ── Timing header ──────────────────────────────────────────────
        timing_row = QHBoxLayout()
        timing_row.setSpacing(6)

        self._title = QLabel("No clip selected")
        self._title.setStyleSheet(_TITLE_STYLE)

        start_lbl = QLabel("Start")
        start_lbl.setStyleSheet("color: #aaa; font-size: 11px; border: none;")
        self._start_spin = QDoubleSpinBox()
        self._start_spin.setRange(0.0, 3600.0)
        self._start_spin.setSingleStep(0.1)
        self._start_spin.setDecimals(2)
        self._start_spin.setFixedWidth(70)
        self._start_spin.setStyleSheet(_SPIN_TIME)
        self._start_spin.setSuffix(" s")

        dur_lbl = QLabel("Dur")
        dur_lbl.setStyleSheet("color: #aaa; font-size: 11px; border: none;")
        self._dur_spin = QDoubleSpinBox()
        self._dur_spin.setRange(0.01, 3600.0)
        self._dur_spin.setSingleStep(0.1)
        self._dur_spin.setDecimals(2)
        self._dur_spin.setFixedWidth(70)
        self._dur_spin.setStyleSheet(_SPIN_TIME)
        self._dur_spin.setSuffix(" s")

        timing_row.addWidget(self._title)
        timing_row.addStretch()
        timing_row.addWidget(start_lbl)
        timing_row.addWidget(self._start_spin)
        timing_row.addWidget(dur_lbl)
        timing_row.addWidget(self._dur_spin)
        outer.addLayout(timing_row)

        # ── Scrollable content ─────────────────────────────────────────
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

        # ── Instances section ──────────────────────────────────────────
        inst_hdr = QHBoxLayout()
        inst_hdr.setSpacing(4)
        inst_label = QLabel("INSTANCES")
        inst_label.setStyleSheet(_HEADER_STYLE)
        self._inst_count = QLabel("0")
        self._inst_count.setStyleSheet("color: #888; font-size: 10px; border: none; min-width: 16px;")
        btn_add = QPushButton("+")
        btn_add.setStyleSheet(_BTN_STYLE)
        btn_add.setToolTip("Add pixel instance")
        btn_rem = QPushButton("−")
        btn_rem.setStyleSheet(_BTN_STYLE)
        btn_rem.setToolTip("Remove last pixel instance")
        inst_hdr.addWidget(inst_label)
        inst_hdr.addWidget(self._inst_count)
        inst_hdr.addStretch()
        inst_hdr.addWidget(btn_add)
        inst_hdr.addWidget(btn_rem)
        self._content_layout.addLayout(inst_hdr)

        self._pixel_container = QWidget()
        self._pixel_container.setStyleSheet("background: transparent;")
        pixel_vbox = QVBoxLayout(self._pixel_container)
        pixel_vbox.setContentsMargins(0, 0, 0, 0)
        pixel_vbox.setSpacing(0)
        for i in range(_MAX_PIXELS):
            pr = _PixelRow(i)
            pr.changed.connect(self.params_changed)
            pr.setVisible(False)
            self._pixel_rows.append(pr)
            pixel_vbox.addWidget(pr)
        self._content_layout.addWidget(self._pixel_container)

        # ── Parameter groups ───────────────────────────────────────────
        for group_label, field_names in _GROUPS:
            hdr = QLabel(group_label.upper())
            hdr.setStyleSheet(_HEADER_STYLE)
            self._content_layout.addWidget(hdr)

            grid = QWidget()
            grid_layout = QHBoxLayout(grid)
            grid_layout.setContentsMargins(0, 0, 0, 0)
            grid_layout.setSpacing(0)

            col_widgets: list[list] = [[], [], []]
            for i, name in enumerate(field_names):
                row = _ParamRow(name)
                row.changed.connect(self.params_changed)
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

        # Wire
        self._start_spin.valueChanged.connect(self._on_start_changed)
        self._dur_spin.valueChanged.connect(self._on_dur_changed)
        btn_add.clicked.connect(self._on_add_pixel)
        btn_rem.clicked.connect(self._on_rem_pixel)

        self._set_timing_visible(False)
        self._set_params_visible(False)

    # ── visibility helpers ─────────────────────────────────────────────

    def _set_params_visible(self, visible: bool):
        for row in self._rows.values():
            row.setVisible(visible)

    def _set_timing_visible(self, visible: bool):
        self._start_spin.setVisible(visible)
        self._dur_spin.setVisible(visible)

    # ── timing slots ──────────────────────────────────────────────────

    def _on_start_changed(self, val: float):
        if not self._loading and self._clip:
            self._clip.start = val
            self.clip_layout_changed.emit()

    def _on_dur_changed(self, val: float):
        if not self._loading and self._clip:
            self._clip.duration = val
            self.clip_layout_changed.emit()

    # ── pixel instance slots ──────────────────────────────────────────

    def _on_add_pixel(self):
        if self._clip is None or len(self._clip.pixels) >= _MAX_PIXELS:
            return
        self._clip.pixels.append(VirtualPixel())
        self._refresh_pixel_rows()
        self.params_changed.emit()
        self.clip_layout_changed.emit()

    def _on_rem_pixel(self):
        if self._clip is None or len(self._clip.pixels) <= 1:
            return
        self._clip.pixels.pop()
        self._refresh_pixel_rows()
        self.params_changed.emit()
        self.clip_layout_changed.emit()

    def _refresh_pixel_rows(self):
        n = len(self._clip.pixels) if self._clip else 0
        self._inst_count.setText(str(n))
        for i, row in enumerate(self._pixel_rows):
            if i < n:
                row.load(self._clip.pixels[i])
                row.setVisible(True)
            else:
                row.setVisible(False)

    # ── public API ────────────────────────────────────────────────────

    def show_clip(self, clip, subtrack=None, track=None):
        self._clip = clip
        self._loading = True

        self._title.setText("Clip")
        self._start_spin.setValue(clip.start)
        self._dur_spin.setValue(clip.duration)
        self._set_timing_visible(True)
        self._refresh_pixel_rows()

        resolved = None
        if subtrack is not None and track is not None:
            resolved = resolve_params(clip, subtrack, track)
        for name, row in self._rows.items():
            resolved_val = getattr(resolved, name) if resolved else None
            row.load(clip.params, resolved_val)

        self._loading = False
        self._set_params_visible(True)

    def clear(self):
        self._clip = None
        self._title.setText("No clip selected")
        self._set_timing_visible(False)
        self._set_params_visible(False)
        for row in self._pixel_rows:
            row.setVisible(False)
