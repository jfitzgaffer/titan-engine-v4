from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QSlider, QComboBox
from PySide6.QtCore import Qt

# These MUST match the dimensions in timeline.py to keep everything aligned!
TRACK_HEIGHT = 60
RULER_HEIGHT = 30


class SingleTrackHeader(QWidget):
    """The UI box for an individual track (Name, Opacity, Blend Mode)."""

    def __init__(self, track):
        super().__init__()
        self.track = track
        self.setFixedHeight(TRACK_HEIGHT)

        # Styling: Dark gray background with a subtle border on the bottom
        self.setStyleSheet("background-color: #333333; border-bottom: 1px solid #222;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 5, 10, 5)

        # --- Top Row: Track Name & Blending Mode ---
        top_row = QHBoxLayout()

        name_label = QLabel(self.track.name)
        name_label.setStyleSheet("color: white; font-weight: bold; border: none;")

        self.blend_combo = QComboBox()
        self.blend_combo.addItems(["Add", "Overwrite", "Multiply"])
        self.blend_combo.setCurrentText(self.track.blending_mode)
        self.blend_combo.setStyleSheet("color: white; background: #555; border: none; padding: 2px;")
        self.blend_combo.currentTextChanged.connect(self.update_blend_mode)

        top_row.addWidget(name_label)
        top_row.addStretch()  # Pushes the combo box all the way to the right
        top_row.addWidget(self.blend_combo)

        # --- Bottom Row: Opacity Slider ---
        bottom_row = QHBoxLayout()

        op_label = QLabel("Opacity:")
        op_label.setStyleSheet("color: #aaa; font-size: 10px; border: none;")

        self.op_slider = QSlider(Qt.Horizontal)
        self.op_slider.setRange(0, 100)
        self.op_slider.setValue(int(self.track.opacity * 100))
        self.op_slider.valueChanged.connect(self.update_opacity)

        bottom_row.addWidget(op_label)
        bottom_row.addWidget(self.op_slider)

        layout.addLayout(top_row)
        layout.addLayout(bottom_row)

    def update_blend_mode(self, mode):
        # Update the underlying data model! The Compositor will instantly use the new math.
        self.track.blending_mode = mode

    def update_opacity(self, val):
        # Slider is 0-100, our math expects 0.0-1.0
        self.track.opacity = val / 100.0


class TrackHeaderPanel(QWidget):
    """The left-hand column containing all the track headers."""

    def __init__(self, project):
        super().__init__()
        self.setFixedWidth(200)  # Fixed width so the timeline doesn't crush it
        self.setStyleSheet("background-color: #2a2a2a;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 1. Spacer to account for the Timeline's Time Ruler
        ruler_spacer = QWidget()
        ruler_spacer.setFixedHeight(RULER_HEIGHT)
        ruler_spacer.setStyleSheet("background-color: #222222; border-bottom: 1px solid #111;")
        layout.addWidget(ruler_spacer)

        # 2. Add a header box for every track in the project
        for track in project.tracks:
            header = SingleTrackHeader(track)
            layout.addWidget(header)

        # 3. Add a stretch at the bottom to push all tracks up to the top
        layout.addStretch()