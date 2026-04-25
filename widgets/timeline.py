from PySide6.QtWidgets import QGraphicsView, QGraphicsScene, QGraphicsRectItem, QGraphicsItem
from PySide6.QtCore import Qt, QRectF, QPointF, Signal
from PySide6.QtGui import QColor, QBrush, QPen, QPainter, QFont, QImage

from widgets.constants import TRACK_HEIGHT, RULER_HEIGHT, AUDIO_TRACK_HEIGHT, PIXELS_PER_SECOND

HANDLE_WIDTH = 8   # px from clip edge that activates resize mode

# y-start of the first clip track lane (ruler + audio row)
_LANES_Y = RULER_HEIGHT + AUDIO_TRACK_HEIGHT


class TimeRulerItem(QGraphicsItem):
    """Painted time ruler. Mouse events handled at the view level for reliability."""

    def __init__(self, width: float):
        super().__init__()
        self._width = width
        self.setZValue(5)
        # Disable item-level mouse handling; the view handles ruler clicks
        self.setAcceptedMouseButtons(Qt.NoButton)

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
                mx = x + minor * PIXELS_PER_SECOND / 4
                if mx < self._width:
                    painter.drawLine(int(mx), RULER_HEIGHT * 3 // 4, int(mx), RULER_HEIGHT)


class AudioTrackItem(QGraphicsRectItem):
    """
    Spectrogram / waveform display for the loaded audio reference.
    Call set_image(qimage) after analysis is complete.
    """

    def __init__(self, width: float):
        super().__init__(0, 0, width, AUDIO_TRACK_HEIGHT)
        self.setPos(0, RULER_HEIGHT)
        self.setZValue(1)
        self.setAcceptedMouseButtons(Qt.NoButton)
        self._image: QImage | None = None

        self.setBrush(QBrush(QColor(15, 15, 30)))
        self.setPen(QPen(QColor(40, 40, 60), 1))

    def set_image(self, qimage: QImage):
        self._image = qimage.scaled(
            int(self.rect().width()), AUDIO_TRACK_HEIGHT,
            Qt.IgnoreAspectRatio, Qt.SmoothTransformation,
        )
        self.update()

    def paint(self, painter, option, widget):
        super().paint(painter, option, widget)
        r = self.rect()
        if self._image:
            painter.drawImage(r, self._image)
        else:
            painter.setPen(QPen(QColor(70, 70, 90)))
            painter.setFont(QFont("Arial", 10))
            painter.drawText(r, Qt.AlignCenter,
                             "Load audio to see spectrogram  (File → Open Audio…)")


class ClipItem(QGraphicsRectItem):
    """
    Clip block. Left/right 8 px edges are resize handles; middle drags.
    Y axis is locked to the track lane at all times.
    """

    COLORS = [
        QColor(140, 100, 200, 200),
        QColor(80, 160, 220, 200),
        QColor(80, 200, 130, 200),
        QColor(220, 160,  60, 200),
        QColor(220,  80,  80, 200),
    ]

    def __init__(self, clip_model, y_offset: float, color_index: int = 0, on_selected=None):
        super().__init__()
        self.clip = clip_model
        self._locked_y = y_offset + 5
        self._on_selected = on_selected

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
        self.setRect(0, 0, max(0.1, self.clip.duration) * PIXELS_PER_SECOND, TRACK_HEIGHT - 10)

    # ---- drag (horizontal move) ----------------------------------------

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionChange and self._resize_edge is None:
            return QPointF(max(0.0, value.x()), self._locked_y)
        if change == QGraphicsItem.ItemPositionHasChanged and self._resize_edge is None:
            self.clip.start = self.pos().x() / PIXELS_PER_SECOND
        return super().itemChange(change, value)

    # ---- resize handles -------------------------------------------------

    def _edge_at(self, local_x: float) -> str | None:
        w = self.rect().width()
        if local_x <= HANDLE_WIDTH:
            return "left"
        if local_x >= w - HANDLE_WIDTH:
            return "right"
        return None

    def hoverMoveEvent(self, event):
        self.setCursor(Qt.SizeHorCursor if self._edge_at(event.pos().x()) else Qt.SizeAllCursor)
        super().hoverMoveEvent(event)

    def hoverLeaveEvent(self, event):
        self.unsetCursor()
        super().hoverLeaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            edge = self._edge_at(event.pos().x())
            if edge:
                self._resize_edge = edge
                self._drag_origin_x     = event.scenePos().x()
                self._drag_origin_start = self.clip.start
                self._drag_origin_dur   = self.clip.duration
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
            else:  # left
                new_end   = self._drag_origin_start + self._drag_origin_dur
                new_start = min(new_end - 0.1, max(0.0, self._drag_origin_start + dx_sec))
                self.clip.start    = new_start
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

    def paint(self, painter, option, widget):
        super().paint(painter, option, widget)
        r = self.rect()
        painter.fillRect(QRectF(0, 0, HANDLE_WIDTH, r.height()), QColor(255, 255, 255, 30))
        painter.fillRect(QRectF(r.width() - HANDLE_WIDTH, 0, HANDLE_WIDTH, r.height()),
                         QColor(255, 255, 255, 30))
        painter.setPen(QPen(QColor(255, 255, 255, 180)))
        painter.setFont(QFont("Arial", 8))
        painter.drawText(r.adjusted(HANDLE_WIDTH + 2, 2, -HANDLE_WIDTH - 2, -2),
                         Qt.AlignLeft | Qt.AlignTop,
                         f"{self.clip.duration:.2f}s")


class TimelineWidget(QGraphicsView):
    """
    DAW timeline.

    Signals:
      seek_requested(float)  — ruler click/drag; connect to controller.seek()
      clip_selected(object)  — clip clicked; connect to PropertiesPanel.show_clip()
    """

    seek_requested = Signal(float)
    clip_selected  = Signal(object)

    SCENE_WIDTH = 5000

    def __init__(self, project):
        super().__init__()
        self.project = project
        self._seeking = False         # True while dragging in the ruler
        self._audio_item: AudioTrackItem | None = None

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
        self._audio_item = None

        # Ruler
        self.scene.addItem(TimeRulerItem(self.SCENE_WIDTH))

        # Audio reference track
        self._audio_item = AudioTrackItem(self.SCENE_WIDTH)
        self.scene.addItem(self._audio_item)

        # Clip track lanes (shifted down by audio row)
        y = _LANES_Y
        for track_idx, track in enumerate(self.project.tracks):
            bg = QGraphicsRectItem(0, y, self.SCENE_WIDTH, TRACK_HEIGHT)
            bg.setBrush(QBrush(QColor(40, 40, 40) if track_idx % 2 == 0 else QColor(35, 35, 35)))
            bg.setPen(QPen(QColor(20, 20, 20), 0))
            self.scene.addItem(bg)

            for subtrack in track.sub_tracks:
                for clip in subtrack.clips:
                    self.scene.addItem(ClipItem(
                        clip, y, track_idx,
                        on_selected=lambda c: self.clip_selected.emit(c),
                    ))
            y += TRACK_HEIGHT

        total_height = max(y, _LANES_Y + TRACK_HEIGHT)
        self.scene.setSceneRect(0, 0, self.SCENE_WIDTH, total_height)

        self.playhead_line = self.scene.addLine(
            0, 0, 0, total_height, QPen(QColor(255, 50, 50), 2)
        )
        self.playhead_line.setZValue(10)

    def refresh(self):
        self._populate_scene()

    def set_audio_image(self, qimage: QImage):
        """Called from main after analysis completes."""
        if self._audio_item:
            self._audio_item.set_image(qimage)

    def update_playhead(self, time_seconds: float):
        if self.playhead_line:
            self.playhead_line.setPos(time_seconds * PIXELS_PER_SECOND, 0)

    # ---- ruler seek (handled at view level — reliable, no item race) ----

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            scene_y = self.mapToScene(event.pos()).y()
            if 0 <= scene_y <= RULER_HEIGHT:
                self._seeking = True
                t = max(0.0, self.mapToScene(event.pos()).x() / PIXELS_PER_SECOND)
                self.seek_requested.emit(t)
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._seeking:
            t = max(0.0, self.mapToScene(event.pos()).x() / PIXELS_PER_SECOND)
            self.seek_requested.emit(t)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._seeking:
            self._seeking = False
            event.accept()
            return
        super().mouseReleaseEvent(event)

    # ---- zoom -----------------------------------------------------------

    def wheelEvent(self, event):
        if event.modifiers() in (Qt.ControlModifier, Qt.MetaModifier):
            factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
            self.scale(factor, 1.0)
        else:
            super().wheelEvent(event)
