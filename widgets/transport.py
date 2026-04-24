from PySide6.QtWidgets import QWidget, QHBoxLayout, QPushButton, QLabel
from PySide6.QtCore import Qt, QTimer


class TransportBar(QWidget):
    """Play / Pause / Stop bar with a live time display."""

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
            QPushButton:hover  { background: #3e3e3e; }
            QPushButton:pressed { background: #1a1a1a; }
        """

        self.btn_play = QPushButton("▶")
        self.btn_pause = QPushButton("⏸")
        self.btn_stop = QPushButton("⏹")

        for btn in (self.btn_play, self.btn_pause, self.btn_stop):
            btn.setStyleSheet(btn_style)

        self.btn_play.setToolTip("Play (Space)")
        self.btn_pause.setToolTip("Pause")
        self.btn_stop.setToolTip("Stop & rewind")

        self.time_label = QLabel("0:00.000")
        self.time_label.setStyleSheet(
            "color: #00ff66; font-family: monospace; font-size: 13px; "
            "min-width: 80px; border: none;"
        )
        self.time_label.setAlignment(Qt.AlignCenter)

        self.btn_play.clicked.connect(self._play)
        self.btn_pause.clicked.connect(self._pause)
        self.btn_stop.clicked.connect(self._stop)

        layout.addWidget(self.btn_play)
        layout.addWidget(self.btn_pause)
        layout.addWidget(self.btn_stop)
        layout.addSpacing(8)
        layout.addWidget(self.time_label)
        layout.addStretch()

        self._timer = QTimer(self)
        self._timer.setInterval(33)   # ~30 Hz display refresh
        self._timer.timeout.connect(self._refresh_display)
        self._timer.start()

    def set_controller(self, controller):
        self.controller = controller

    def _play(self):
        if self.controller:
            self.controller.play()

    def _pause(self):
        if self.controller:
            self.controller.pause()

    def _stop(self):
        if self.controller:
            self.controller.stop()

    def _refresh_display(self):
        if not self.controller:
            return
        t = self.controller.playhead_time
        minutes = int(t // 60)
        seconds = int(t % 60)
        ms = int((t % 1) * 1000)
        self.time_label.setText(f"{minutes}:{seconds:02d}.{ms:03d}")
