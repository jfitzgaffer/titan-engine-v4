from PySide6.QtWidgets import QGraphicsView, QGraphicsScene, QGraphicsRectItem, QGraphicsItem
from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import QColor, QBrush, QPen, QPainter, QFont

from widgets.constants import TRACK_HEIGHT, RULER_HEIGHT, PIXELS_PER_SECOND


class TimeRulerItem(QGraphicsItem):
    """Time ruler painted at the top of the timeline scene."""

    def __init__(self, width: float):
        super().__init__()
        self._width = width
        self.setZValue(5)

    def boundingRect(self) -> QRectF:
        return QRectF(0, 0, self._width, RULER_HEIGHT)

    def paint(self, painter, option, widget):
        painter.fillRect(self.boundingRect(), QColor(35, 35, 35))
        painter.setPen(QPen(QColor(150, 150, 150), 1))
        painter.setFont(QFont("Arial", 9))

        total_seconds = int(self._width / PIXELS_PER_SECOND)
        for s in range(total_seconds + 1):
            x = s * PIXELS_PER_SECOND
            painter.drawLine(x, RULER_HEIGHT // 2, x, RULER_HEIGHT)
            painter.drawText(QRectF(x + 4, 2, 50, RULER_HEIGHT // 2), Qt.AlignLeft, f"{s}s")
            for minor in range(1, 4):
                mx = x + (minor * PIXELS_PER_SECOND / 4)
                if mx < self._width:
                    painter.drawLine(int(mx), RULER_HEIGHT * 3 // 4, int(mx), RULER_HEIGHT)


class ClipItem(QGraphicsRectItem):
    """A clip block in the timeline. Draggable horizontally, Y-axis locked."""

    # Track accent colours (cycle by track index)
    COLORS = [
        QColor(140, 100, 200, 200),   # purple
        QColor(80, 160, 220, 200),    # blue
        QColor(80, 200, 130, 200),    # green
        QColor(220, 160, 60, 200),    # amber
        QColor(220, 80, 80, 200),     # red
    ]

    def __init__(self, clip_model, y_offset: float, color_index: int = 0):
        super().__init__()
        self.clip = clip_model
        self._locked_y = y_offset + 5   # Y is fixed; only X moves during drag

        x = self.clip.start * PIXELS_PER_SECOND
        w = self.clip.duration * PIXELS_PER_SECOND

        self.setRect(0, 0, w, TRACK_HEIGHT - 10)
        self.setPos(x, self._locked_y)

        self.setFlag(QGraphicsItem.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.ItemSendsGeometryChanges, True)

        color = self.COLORS[color_index % len(self.COLORS)]
        self.setBrush(QBrush(color))
        self.setPen(QPen(QColor(220, 220, 220), 1))

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionChange:
            # Clamp to non-negative time, lock Y axis
            return QPointF(max(0.0, value.x()), self._locked_y)

        if change == QGraphicsItem.ItemPositionHasChanged:
            self.clip.start = self.pos().x() / PIXELS_PER_SECOND

        return super().itemChange(change, value)

    def paint(self, painter, option, widget):
        super().paint(painter, option, widget)
        # Draw clip label (duration in seconds)
        painter.setPen(QPen(QColor(255, 255, 255, 180), 1))
        painter.setFont(QFont("Arial", 8))
        label = f"{self.clip.duration:.1f}s"
        painter.drawText(self.rect().adjusted(4, 2, -4, -2), Qt.AlignLeft | Qt.AlignTop, label)


class TimelineWidget(QGraphicsView):
    """Main DAW timeline view. Horizontal Cmd/Ctrl+scroll zooms time axis."""

    SCENE_WIDTH = 5000   # virtual canvas width in scene pixels

    def __init__(self, project):
        super().__init__()
        self.project = project

        self.scene = QGraphicsScene(self)
        self.setScene(self.scene)

        self.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.setRenderHint(QPainter.Antialiasing)
        self.setBackgroundBrush(QBrush(QColor(25, 25, 25)))
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOn)

        self.playhead_line = None
        self._populate_scene()

    def _populate_scene(self):
        self.scene.clear()

        ruler = TimeRulerItem(self.SCENE_WIDTH)
        self.scene.addItem(ruler)

        y = RULER_HEIGHT
        for track_idx, track in enumerate(self.project.tracks):
            bg = QGraphicsRectItem(0, y, self.SCENE_WIDTH, TRACK_HEIGHT)
            bg.setBrush(QBrush(QColor(40, 40, 40) if track_idx % 2 == 0 else QColor(35, 35, 35)))
            bg.setPen(QPen(QColor(20, 20, 20), 0))
            self.scene.addItem(bg)

            for subtrack in track.sub_tracks:
                for clip in subtrack.clips:
                    self.scene.addItem(ClipItem(clip, y, track_idx))

            y += TRACK_HEIGHT

        total_height = max(y, RULER_HEIGHT + TRACK_HEIGHT)
        self.scene.setSceneRect(0, 0, self.SCENE_WIDTH, total_height)

        self.playhead_line = self.scene.addLine(
            0, 0, 0, total_height,
            QPen(QColor(255, 50, 50), 2)
        )
        self.playhead_line.setZValue(10)

    def refresh(self):
        """Rebuild the scene after the project structure changes."""
        self._populate_scene()

    def update_playhead(self, time_seconds: float):
        if self.playhead_line:
            self.playhead_line.setPos(time_seconds * PIXELS_PER_SECOND, 0)

    def wheelEvent(self, event):
        if event.modifiers() in (Qt.ControlModifier, Qt.MetaModifier):
            factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
            self.scale(factor, 1.0)
        else:
            super().wheelEvent(event)
