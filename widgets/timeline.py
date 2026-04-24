from PySide6.QtWidgets import QGraphicsView, QGraphicsScene, QGraphicsRectItem, QGraphicsItem
from PySide6.QtCore import Qt, QRectF, QPointF, Signal
from PySide6.QtGui import QColor, QBrush, QPen, QPainter, QFont, QCursor

from widgets.constants import TRACK_HEIGHT, RULER_HEIGHT, PIXELS_PER_SECOND

HANDLE_WIDTH = 8   # px from clip edge that activates resize cursor


class TimeRulerItem(QGraphicsItem):
    """Time ruler at the top of the scene. Click → seek."""

    def __init__(self, width: float, on_seek=None):
        super().__init__()
        self._width = width
        self._on_seek = on_seek   # callable(seconds: float) | None
        self.setZValue(5)
        self.setAcceptedMouseButtons(Qt.LeftButton)

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

    def mousePressEvent(self, event):
        if self._on_seek:
            t = max(0.0, event.pos().x() / PIXELS_PER_SECOND)
            self._on_seek(t)
        event.accept()


class ClipItem(QGraphicsRectItem):
    """
    A clip block. Left/right edges are resize handles (8 px).
    The middle area drags the clip horizontally.
    Y axis is locked to its track lane at all times.
    """

    COLORS = [
        QColor(140, 100, 200, 200),
        QColor(80, 160, 220, 200),
        QColor(80, 200, 130, 200),
        QColor(220, 160, 60, 200),
        QColor(220, 80, 80, 200),
    ]

    def __init__(self, clip_model, y_offset: float, color_index: int = 0, on_selected=None):
        super().__init__()
        self.clip = clip_model
        self._locked_y = y_offset + 5
        self._on_selected = on_selected    # callable(clip) | None

        self._resize_edge: str | None = None
        self._drag_origin_x: float = 0.0
        self._drag_origin_start: float = 0.0
        self._drag_origin_dur: float = 0.0

        self._update_rect()
        self.setPos(self.clip.start * PIXELS_PER_SECOND, self._locked_y)

        self.setFlag(QGraphicsItem.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.ItemSendsGeometryChanges, True)
        self.setAcceptHoverEvents(True)

        color = self.COLORS[color_index % len(self.COLORS)]
        self.setBrush(QBrush(color))
        self.setPen(QPen(QColor(220, 220, 220), 1))

    def _update_rect(self):
        w = max(0.1, self.clip.duration) * PIXELS_PER_SECOND
        self.setRect(0, 0, w, TRACK_HEIGHT - 10)

    # ------------------------------------------------------------------
    # Drag (horizontal move)
    # ------------------------------------------------------------------

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionChange and self._resize_edge is None:
            return QPointF(max(0.0, value.x()), self._locked_y)
        if change == QGraphicsItem.ItemPositionHasChanged and self._resize_edge is None:
            self.clip.start = self.pos().x() / PIXELS_PER_SECOND
        return super().itemChange(change, value)

    # ------------------------------------------------------------------
    # Resize handles
    # ------------------------------------------------------------------

    def _edge_at(self, local_x: float) -> str | None:
        w = self.rect().width()
        if local_x <= HANDLE_WIDTH:
            return "left"
        if local_x >= w - HANDLE_WIDTH:
            return "right"
        return None

    def hoverMoveEvent(self, event):
        edge = self._edge_at(event.pos().x())
        self.setCursor(Qt.SizeHorCursor if edge else Qt.SizeAllCursor)
        super().hoverMoveEvent(event)

    def hoverLeaveEvent(self, event):
        self.unsetCursor()
        super().hoverLeaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            edge = self._edge_at(event.pos().x())
            if edge:
                self._resize_edge = edge
                self._drag_origin_x = event.scenePos().x()
                self._drag_origin_start = self.clip.start
                self._drag_origin_dur = self.clip.duration
                self.setFlag(QGraphicsItem.ItemIsMovable, False)
                event.accept()
                return
            if self._on_selected:
                self._on_selected(self.clip)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._resize_edge:
            dx_sec = (event.scenePos().x() - self._drag_origin_x) / PIXELS_PER_SECOND

            if self._resize_edge == "right":
                self.clip.duration = max(0.1, self._drag_origin_dur + dx_sec)

            elif self._resize_edge == "left":
                new_end = self._drag_origin_start + self._drag_origin_dur
                new_start = min(new_end - 0.1, max(0.0, self._drag_origin_start + dx_sec))
                self.clip.start = new_start
                self.clip.duration = new_end - new_start
                self.setPos(new_start * PIXELS_PER_SECOND, self._locked_y)

            self._update_rect()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._resize_edge:
            self._resize_edge = None
            self.setFlag(QGraphicsItem.ItemIsMovable, True)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    # ------------------------------------------------------------------
    # Painting
    # ------------------------------------------------------------------

    def paint(self, painter, option, widget):
        super().paint(painter, option, widget)

        r = self.rect()

        # Resize handle hints (subtle brighter strips on edges)
        handle_color = QColor(255, 255, 255, 40)
        painter.fillRect(QRectF(0, 0, HANDLE_WIDTH, r.height()), handle_color)
        painter.fillRect(QRectF(r.width() - HANDLE_WIDTH, 0, HANDLE_WIDTH, r.height()), handle_color)

        # Duration label
        painter.setPen(QPen(QColor(255, 255, 255, 180)))
        painter.setFont(QFont("Arial", 8))
        painter.drawText(r.adjusted(HANDLE_WIDTH + 2, 2, -HANDLE_WIDTH - 2, -2),
                         Qt.AlignLeft | Qt.AlignTop,
                         f"{self.clip.duration:.2f}s")


class TimelineWidget(QGraphicsView):
    """
    DAW timeline. Signals:
      seek_requested(float)  — ruler click; connect to controller.seek()
      clip_selected(object)  — clip clicked; connect to PropertiesPanel.show_clip()
    """

    seek_requested = Signal(float)
    clip_selected  = Signal(object)   # carries the Clip dataclass

    SCENE_WIDTH = 5000

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

        ruler = TimeRulerItem(
            self.SCENE_WIDTH,
            on_seek=lambda t: self.seek_requested.emit(t),
        )
        self.scene.addItem(ruler)

        y = RULER_HEIGHT
        for track_idx, track in enumerate(self.project.tracks):
            bg = QGraphicsRectItem(0, y, self.SCENE_WIDTH, TRACK_HEIGHT)
            bg.setBrush(QBrush(QColor(40, 40, 40) if track_idx % 2 == 0 else QColor(35, 35, 35)))
            bg.setPen(QPen(QColor(20, 20, 20), 0))
            self.scene.addItem(bg)

            for subtrack in track.sub_tracks:
                for clip in subtrack.clips:
                    item = ClipItem(
                        clip, y, track_idx,
                        on_selected=lambda c: self.clip_selected.emit(c),
                    )
                    self.scene.addItem(item)

            y += TRACK_HEIGHT

        total_height = max(y, RULER_HEIGHT + TRACK_HEIGHT)
        self.scene.setSceneRect(0, 0, self.SCENE_WIDTH, total_height)

        self.playhead_line = self.scene.addLine(
            0, 0, 0, total_height,
            QPen(QColor(255, 50, 50), 2)
        )
        self.playhead_line.setZValue(10)

    def refresh(self):
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
