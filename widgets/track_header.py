from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QSlider, QComboBox, QPushButton
from PySide6.QtCore import Qt, Signal

from widgets.constants import TRACK_HEIGHT, RULER_HEIGHT, AUDIO_TRACK_HEIGHT


class AudioTrackHeader(QWidget):
    """Left-side header for the audio reference row."""

    view_mode_changed = Signal(str)   # "spectrogram" | "waveform" | "both" | "none"
    bpm_grid_toggled  = Signal(bool)

    def __init__(self):
        super().__init__()
        self.setFixedHeight(AUDIO_TRACK_HEIGHT)
        self.setStyleSheet("background: #151525; border-bottom: 1px solid #333;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(3)

        # Row 1: title + filename
        top = QHBoxLayout()
        top.setSpacing(4)
        title = QLabel("Audio")
        title.setStyleSheet("color: #8888cc; font-weight: bold; font-size: 11px; border: none;")
        self._filename = QLabel("No audio")
        self._filename.setStyleSheet(
            "color: #555; font-size: 10px; border: none; font-style: italic;"
        )
        self._filename.setWordWrap(False)
        top.addWidget(title)
        top.addWidget(self._filename, stretch=1)
        layout.addLayout(top)

        # Row 2: view-mode combo + BPM label
        mid = QHBoxLayout()
        mid.setSpacing(4)
        self._view_combo = QComboBox()
        self._view_combo.addItems(["Spectrogram", "Waveform", "Both", "None"])
        self._view_combo.setStyleSheet(
            "QComboBox { color: #aaa; background: #222; border: 1px solid #444; "
            "font-size: 10px; padding: 1px 4px; }"
            "QComboBox QAbstractItemView { background: #2a2a2a; color: white; }"
        )
        self._view_combo.setFixedHeight(20)
        self._bpm_label = QLabel("")
        self._bpm_label.setStyleSheet("color: #ffcc00; font-size: 10px; border: none;")
        mid.addWidget(self._view_combo, stretch=1)
        mid.addWidget(self._bpm_label)
        layout.addLayout(mid)

        # Row 3: BPM grid toggle
        bot = QHBoxLayout()
        bot.setSpacing(4)
        self._bpm_btn = QPushButton("BPM Grid")
        self._bpm_btn.setCheckable(True)
        self._bpm_btn.setStyleSheet(
            "QPushButton { color: #aaa; background: #222; border: 1px solid #444; "
            "border-radius: 3px; font-size: 10px; padding: 1px 6px; }"
            "QPushButton:checked { color: #ffcc00; border-color: #ffcc00; background: #2a2200; }"
            "QPushButton:hover { background: #2e2e2e; }"
        )
        self._bpm_btn.setFixedHeight(20)
        bot.addWidget(self._bpm_btn)
        bot.addStretch()
        layout.addLayout(bot)

        self._view_combo.currentTextChanged.connect(
            lambda t: self.view_mode_changed.emit(t.lower())
        )
        self._bpm_btn.toggled.connect(self.bpm_grid_toggled)

    def set_filename(self, name: str):
        self._filename.setText(name)
        self._filename.setStyleSheet("color: #8888cc; font-size: 10px; border: none;")

    def set_bpm(self, bpm: float):
        self._bpm_label.setText(f"{bpm:.1f} BPM")


class SingleTrackHeader(QWidget):
    """Left-side header for one clip track: name, blend mode, opacity."""

    def __init__(self, track, track_index: int = 0):
        super().__init__()
        self.track = track
        self.setFixedHeight(TRACK_HEIGHT)

        bg = "#333333" if track_index % 2 == 0 else "#2e2e2e"
        self.setStyleSheet(f"background-color: {bg}; border-bottom: 1px solid #222;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 5, 10, 5)
        layout.setSpacing(2)

        # Top row: name + blend mode
        top_row = QHBoxLayout()
        top_row.setSpacing(4)

        name_label = QLabel(self.track.name)
        name_label.setStyleSheet("color: white; font-weight: bold; border: none;")

        self.blend_combo = QComboBox()
        self.blend_combo.addItems(["Add", "Overwrite", "Multiply"])
        self.blend_combo.setCurrentText(self.track.blending_mode)
        self.blend_combo.setStyleSheet(
            "color: white; background: #555; border: none; padding: 2px; font-size: 10px;"
        )
        self.blend_combo.setFixedWidth(80)
        self.blend_combo.currentTextChanged.connect(self._on_blend_change)

        top_row.addWidget(name_label)
        top_row.addStretch()
        top_row.addWidget(self.blend_combo)

        # Bottom row: opacity
        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(4)

        op_label = QLabel("Opacity")
        op_label.setStyleSheet("color: #aaa; font-size: 10px; border: none;")
        op_label.setFixedWidth(44)

        self.op_slider = QSlider(Qt.Horizontal)
        self.op_slider.setRange(0, 100)
        self.op_slider.setValue(int(self.track.opacity * 100))
        self.op_slider.setStyleSheet("""
            QSlider::groove:horizontal { height: 4px; background: #555; border-radius: 2px; }
            QSlider::handle:horizontal {
                width: 10px; height: 10px; background: #00ff66;
                border-radius: 5px; margin: -3px 0;
            }
        """)
        self.op_slider.valueChanged.connect(self._on_opacity_change)

        self.op_value = QLabel(f"{int(self.track.opacity * 100)}%")
        self.op_value.setStyleSheet("color: #00ff66; font-size: 10px; border: none;")
        self.op_value.setFixedWidth(32)

        bottom_row.addWidget(op_label)
        bottom_row.addWidget(self.op_slider)
        bottom_row.addWidget(self.op_value)

        layout.addLayout(top_row)
        layout.addLayout(bottom_row)

    def _on_blend_change(self, mode: str):
        self.track.blending_mode = mode

    def _on_opacity_change(self, val: int):
        self.track.opacity = val / 100.0
        self.op_value.setText(f"{val}%")


class TrackHeaderPanel(QWidget):
    """Left column: audio header + one row per clip track."""

    def __init__(self, project):
        super().__init__()
        self.setFixedWidth(180)
        self.setStyleSheet("background-color: #2a2a2a;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Ruler spacer
        ruler_spacer = QWidget()
        ruler_spacer.setFixedHeight(RULER_HEIGHT)
        ruler_spacer.setStyleSheet("background-color: #222222; border-bottom: 1px solid #111;")
        layout.addWidget(ruler_spacer)

        # Audio track header
        self.audio_header = AudioTrackHeader()
        layout.addWidget(self.audio_header)

        # Clip track rows
        for i, track in enumerate(project.tracks):
            layout.addWidget(SingleTrackHeader(track, track_index=i))

        layout.addStretch()
