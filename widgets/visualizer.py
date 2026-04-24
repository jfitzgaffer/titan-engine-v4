from PySide6.QtWidgets import QWidget
from PySide6.QtGui import QPainter, QColor, QBrush
from PySide6.QtCore import Signal, QRectF


class VisualizerWidget(QWidget):
    # This signal acts as a thread-safe bridge.
    # It can safely carry our 512-byte array from the background thread to the UI thread.
    frame_received = Signal(bytearray)

    def __init__(self, mapper):
        super().__init__()
        self.mapper = mapper
        self.setMinimumHeight(80)
        self.current_packet = bytearray(512)

        # Sort the physical LEDs from left to right so we draw them in the correct order
        self.ordered_leds = sorted(self.mapper._pixel_map, key=lambda p: p["x"])

        # Connect the signal to our internal update function
        self.frame_received.connect(self._process_frame)

    def update_frame(self, packet: bytearray):
        """Called by the PlaybackController from the background thread."""
        self.frame_received.emit(packet)

    def _process_frame(self, packet: bytearray):
        """Called by Qt on the main GUI thread."""
        self.current_packet = packet
        self.update()  # Tells Qt to run paintEvent()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        # Fill background with a dark studio gray
        painter.fillRect(self.rect(), QColor(25, 25, 25))

        if not self.ordered_leds:
            return

        width = self.width()
        height = self.height()

        # Calculate how wide each virtual LED block should be on screen
        step = width / len(self.ordered_leds)
        pixel_width = step * 0.8  # 80% width leaves a nice little gap between bulbs

        # Draw each LED
        for led in self.ordered_leds:
            x_pos = led["x"] * width
            addr = led["address"] - 1  # DMX is 1-indexed, Python arrays are 0-indexed

            # Extract RGB from the DMX packet
            r = self.current_packet[addr]
            g = self.current_packet[addr + 1]
            b = self.current_packet[addr + 2]

            # Draw the LED rectangle
            rect = QRectF(x_pos - (pixel_width / 2), 15, pixel_width, height - 30)
            painter.fillRect(rect, QBrush(QColor(r, g, b)))