from pathlib import Path

from PySide6.QtWidgets import QWidget, QHBoxLayout, QPushButton, QLabel, QFileDialog
from PySide6.QtCore import Qt, QTimer, Signal


class TransportBar(QWidget):
    """Single ▶/⏸ toggle + Stop + time display + Open Audio."""

    audio_loaded = Signal(str)   # file path after successful load

    def __init__(self, controller=None):
        super().__init__()
        self.controller = controller
        self.setFixedHeight(40)
        self.setStyleSheet("background: #1a1a1a; border-bottom: 1px solid #333;")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 12, 0)
        layout.setSpacing(6)

        btn_style = """
            QPushButton {
                background: #2e2e2e; color: white;
                border: 1px solid #555; border-radius: 4px;
                font-size: 14px; min-width: 32px; min-height: 26px;
            }
            QPushButton:hover   { background: #3e3e3e; }
            QPushButton:pressed { background: #1a1a1a; }
            QPushButton:checked { background: #1a5533; border-color: #00ff66; }
        """
        open_style = """
            QPushButton {
                background: #2e2e2e; color: #aaa;
                border: 1px solid #555; border-radius: 4px;
                font-size: 11px; padding: 0 8px; min-height: 26px;
            }
            QPushButton:hover   { background: #3e3e3e; color: white; }
            QPushButton:pressed { background: #1a1a1a; }
        """

        # Single play/pause toggle
        self.btn_play_pause = QPushButton("▶")
        self.btn_play_pause.setCheckable(True)
        self.btn_play_pause.setToolTip("Play / Pause  (Space)")
        self.btn_play_pause.setStyleSheet(btn_style)

        self.btn_stop = QPushButton("⏹")
        self.btn_stop.setToolTip("Stop & rewind")
        self.btn_stop.setStyleSheet(btn_style)

        self.time_label = QLabel("0:00.000")
        self.time_label.setStyleSheet(
            "color: #00ff66; font-family: 'Menlo', 'Courier New'; font-size: 13px;"
            "min-width: 80px; border: none;"
        )
        self.time_label.setAlignment(Qt.AlignCenter)

        sep = QLabel("|")
        sep.setStyleSheet("color: #444; border: none;")

        self.btn_open_audio = QPushButton("Open Audio…")
        self.btn_open_audio.setStyleSheet(open_style)
        self.btn_open_audio.setToolTip("Load WAV / FLAC / OGG as backing track")

        self.audio_label = QLabel("No audio loaded")
        self.audio_label.setStyleSheet(
            "color: #666; font-size: 11px; border: none; font-style: italic;"
        )

        self.btn_play_pause.clicked.connect(self._toggle_play)
        self.btn_stop.clicked.connect(self._stop)
        self.btn_open_audio.clicked.connect(self._open_audio_dialog)

        layout.addWidget(self.btn_play_pause)
        layout.addWidget(self.btn_stop)
        layout.addSpacing(8)
        layout.addWidget(self.time_label)
        layout.addSpacing(8)
        layout.addWidget(sep)
        layout.addSpacing(8)
        layout.addWidget(self.btn_open_audio)
        layout.addWidget(self.audio_label)
        layout.addStretch()

        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._refresh_display)
        self._timer.start()

    def set_controller(self, controller):
        self.controller = controller

    def toggle_play_pause(self):
        """Called by spacebar shortcut or button click."""
        self.btn_play_pause.click()

    def _toggle_play(self, checked: bool):
        if not self.controller:
            return
        if checked:
            self.controller.play()
            self.btn_play_pause.setText("⏸")
        else:
            self.controller.pause()
            self.btn_play_pause.setText("▶")

    def _stop(self):
        if self.controller:
            self.controller.stop()
        self.btn_play_pause.setChecked(False)
        self.btn_play_pause.setText("▶")

    def _open_audio_dialog(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Audio File", "",
            "Audio Files (*.wav *.flac *.ogg *.aif *.aiff);;All Files (*)",
        )
        if not path:
            return

        was_playing = self.controller and self.controller.is_playing
        if was_playing:
            self.controller.pause()

        if self.controller and self.controller.load_audio(path):
            self.audio_label.setText(Path(path).name)
            self.audio_label.setStyleSheet("color: #00ff66; font-size: 11px; border: none;")
            self.audio_loaded.emit(path)
            if was_playing:
                self.controller.play()
        else:
            self.audio_label.setText("Failed to load audio")
            self.audio_label.setStyleSheet(
                "color: #ff5555; font-size: 11px; border: none; font-style: italic;"
            )

    def _refresh_display(self):
        if not self.controller:
            return
        # Sync button state with controller
        playing = self.controller.is_playing
        if playing != self.btn_play_pause.isChecked():
            self.btn_play_pause.blockSignals(True)
            self.btn_play_pause.setChecked(playing)
            self.btn_play_pause.setText("⏸" if playing else "▶")
            self.btn_play_pause.blockSignals(False)

        t = self.controller.playhead_time
        self.time_label.setText(
            f"{int(t // 60)}:{int(t % 60):02d}.{int((t % 1) * 1000):03d}"
        )
