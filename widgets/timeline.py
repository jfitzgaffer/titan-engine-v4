import copy

from PySide6.QtWidgets import QGraphicsView, QGraphicsScene, QGraphicsRectItem, QGraphicsItem, QMenu
from PySide6.QtCore import Qt, QRectF, QPointF, Signal
from PySide6.QtGui import QColor, QBrush, QPen, QPainter, QFont, QImage, QCursor

from models.project import Clip, SubTrack, Track, VirtualPixel
from widgets.constants import TRACK_HEIGHT, RULER_HEIGHT, AUDIO_TRACK_HEIGHT, PIXELS_PER_SECOND

HANDLE_WIDTH = 8

_LANES_Y = RULER_HEIGHT + AUDIO_TRACK_HEIGHT

_MENU_SS = (
    "QMenu { background: #2a2a2a; color: white; border: 1px solid #444; }"
    "QMenu::item:selected { background: #3a3a3a; }"
    "QMenu::separator { height: 1px; background: #444; margin: 2px 0; }"
)


class TimeRulerItem(QGraphicsItem):
    """Painted time ruler — mouse events handled at view level."""

    def __init__(self, width: float):
        super().__init__()
        self._width = width
        self.setZValue(5)
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
    Audio reference row. Supports four view modes:
      spectrogram | waveform | both | none
    """

    def __init__(self, width: float):
        super().__init__(0, 0, width, AUDIO_TRACK_HEIGHT)
        self.setPos(0, RULER_HEIGHT)
        self.setZValue(1)
        self.setAcceptedMouseButtons(Qt.NoButton)
        self._spec_image: QImage | None = None
        self._wave_image: QImage | None = None
        self._view_mode: str = "spectrogram"
        self.setBrush(QBrush(QColor(15, 15, 30)))
        self.setPen(QPen(QColor(40, 40, 60), 1))

    def set_spectrogram_image(self, qimage: QImage):
        self._spec_image = qimage.scaled(
            int(self.rect().width()), AUDIO_TRACK_HEIGHT,
            Qt.IgnoreAspectRatio, Qt.SmoothTransformation,
        )
        self.update()

    def set_waveform_image(self, qimage: QImage):
        self._wave_image = qimage.scaled(
            int(self.rect().width()), AUDIO_TRACK_HEIGHT,
            Qt.IgnoreAspectRatio, Qt.SmoothTransformation,
        )
        self.update()

    # backward-compat alias
    def set_image(self, qimage: QImage):
        self.set_spectrogram_image(qimage)

    def set_view_mode(self, mode: str):
        self._view_mode = mode
        self.update()

    def paint(self, painter, option, widget):
        super().paint(painter, option, widget)
        r = self.rect()
        mode = self._view_mode

        if mode == "spectrogram":
            if self._spec_image:
                painter.drawImage(r, self._spec_image)
            else:
                self._placeholder(painter, r)
        elif mode == "waveform":
            if self._wave_image:
                painter.drawImage(r, self._wave_image)
            else:
                self._placeholder(painter, r)
        elif mode == "both":
            if self._spec_image:
                painter.drawImage(r, self._spec_image)
            if self._wave_image:
                painter.setOpacity(0.65)
                painter.drawImage(r, self._wave_image)
                painter.setOpacity(1.0)
        # mode == "none": show only the dark background

    def _placeholder(self, painter, r):
        painter.setPen(QPen(QColor(70, 70, 90)))
        painter.setFont(QFont("Arial", 10))
        painter.drawText(r, Qt.AlignCenter, "Load audio  (File → Open Audio…)")


class ClipItem(QGraphicsRectItem):
    """
    Clip block. Left/right 8 px edges resize; middle drags.
    Y axis locked to lane. Selected state shows a thick gold border.
    Right-click is handled by TimelineWidget.contextMenuEvent.
    """

    COLORS = [
        QColor(140, 100, 200, 200),
        QColor(80,  160, 220, 200),
        QColor(80,  200, 130, 200),
        QColor(220, 160,  60, 200),
        QColor(220,  80,  80, 200),
    ]

    def __init__(self, clip_model, y_offset: float, color_index: int = 0,
                 on_selected=None):
        super().__init__()
        self.clip = clip_model
        self._locked_y = y_offset + 5
        self._on_selected = on_selected

        self._resize_edge: str | None = None
        self._drag_origin_x: float = 0.0
        self._drag_origin_start: float = 0.0
        self._drag_origin_dur: float = 0.0

        self._color = self.COLORS[color_index % len(self.COLORS)]
        self._update_rect()
        self.setPos(self.clip.start * PIXELS_PER_SECOND, self._locked_y)

        self.setFlag(QGraphicsItem.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.ItemSendsGeometryChanges, True)
        self.setAcceptHoverEvents(True)

        self.setBrush(QBrush(self._color))
        self.setPen(QPen(QColor(220, 220, 220), 1))

    def _update_rect(self):
        self.setRect(0, 0, max(0.1, self.clip.duration) * PIXELS_PER_SECOND, TRACK_HEIGHT - 10)

    # ---- drag -------------------------------------------------------

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionChange and self._resize_edge is None:
            return QPointF(max(0.0, value.x()), self._locked_y)
        if change == QGraphicsItem.ItemPositionHasChanged and self._resize_edge is None:
            self.clip.start = self.pos().x() / PIXELS_PER_SECOND
        return super().itemChange(change, value)

    # ---- resize handles ---------------------------------------------

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
                self.setSelected(True)
                if self._on_selected:
                    self._on_selected(self.clip)
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
            else:
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

    # ---- paint ------------------------------------------------------

    def paint(self, painter, option, widget):
        r = self.rect()

        # Base fill
        painter.fillRect(r, self._color)

        # Handle strip highlights
        painter.fillRect(QRectF(0, 0, HANDLE_WIDTH, r.height()), QColor(255, 255, 255, 30))
        painter.fillRect(QRectF(r.width() - HANDLE_WIDTH, 0, HANDLE_WIDTH, r.height()),
                         QColor(255, 255, 255, 30))

        # Duration label
        painter.setPen(QPen(QColor(255, 255, 255, 180)))
        painter.setFont(QFont("Arial", 8))
        painter.drawText(r.adjusted(HANDLE_WIDTH + 2, 2, -HANDLE_WIDTH - 2, -2),
                         Qt.AlignLeft | Qt.AlignTop,
                         f"{self.clip.duration:.2f}s")

        # Border: thick gold when selected, thin white otherwise
        if self.isSelected():
            painter.setPen(QPen(QColor(255, 215, 0), 3))
        else:
            painter.setPen(QPen(QColor(220, 220, 220), 1))
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(r.adjusted(1, 1, -1, -1))


class TimelineWidget(QGraphicsView):
    """
    DAW timeline.

    Signals:
      seek_requested(float)   — ruler click / scrub
      clip_selected(object)   — clip left-clicked
      project_changed()       — clip or track added / deleted
    """

    seek_requested  = Signal(float)
    clip_selected   = Signal(object)
    project_changed = Signal()

    SCENE_WIDTH = 5000

    def __init__(self, project):
        super().__init__()
        self.project = project
        self._seeking = False
        self._audio_item: AudioTrackItem | None = None
        self._bpm: float = 0.0
        self._show_bpm_grid: bool = False
        self._bpm_lines: list = []

        self.scene = QGraphicsScene(self)
        self.setScene(self.scene)
        self.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.setRenderHint(QPainter.Antialiasing)
        self.setBackgroundBrush(QBrush(QColor(25, 25, 25)))
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOn)

        self.playhead_line = None
        self._populate_scene()

    # ---- scene build ------------------------------------------------

    def _populate_scene(self):
        self.scene.clear()
        self._audio_item = None
        self._bpm_lines.clear()

        self.scene.addItem(TimeRulerItem(self.SCENE_WIDTH))

        self._audio_item = AudioTrackItem(self.SCENE_WIDTH)
        self.scene.addItem(self._audio_item)

        y = _LANES_Y
        for track_idx, track in enumerate(self.project.tracks):
            bg = QGraphicsRectItem(0, y, self.SCENE_WIDTH, TRACK_HEIGHT)
            bg.setBrush(QBrush(QColor(40, 40, 40) if track_idx % 2 == 0
                               else QColor(35, 35, 35)))
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

        if self._show_bpm_grid and self._bpm > 0:
            self._rebuild_bpm_grid()

    def refresh(self):
        """Rebuild scene, preserving audio images and BPM state."""
        spec  = self._audio_item._spec_image if self._audio_item else None
        wave  = self._audio_item._wave_image if self._audio_item else None
        vmode = self._audio_item._view_mode  if self._audio_item else "spectrogram"
        ph    = self.playhead_line.pos().x() if self.playhead_line else 0.0
        self._populate_scene()
        if self._audio_item:
            self._audio_item._spec_image = spec
            self._audio_item._wave_image = wave
            self._audio_item._view_mode  = vmode
        if self.playhead_line:
            self.playhead_line.setPos(ph, 0)

    # ---- audio image passthrough -----------------------------------

    def set_audio_image(self, qimage: QImage):
        if self._audio_item:
            self._audio_item.set_spectrogram_image(qimage)

    def set_spectrogram_image(self, qimage: QImage):
        if self._audio_item:
            self._audio_item.set_spectrogram_image(qimage)

    def set_waveform_image(self, qimage: QImage):
        if self._audio_item:
            self._audio_item.set_waveform_image(qimage)

    def set_audio_view_mode(self, mode: str):
        if self._audio_item:
            self._audio_item.set_view_mode(mode)

    # ---- playhead --------------------------------------------------

    def update_playhead(self, time_seconds: float):
        if self.playhead_line:
            self.playhead_line.setPos(time_seconds * PIXELS_PER_SECOND, 0)

    # ---- BPM grid --------------------------------------------------

    def set_bpm(self, bpm: float):
        self._bpm = bpm
        if self._show_bpm_grid:
            self._rebuild_bpm_grid()

    def set_bpm_grid_visible(self, visible: bool):
        self._show_bpm_grid = visible
        for line in self._bpm_lines:
            line.setVisible(visible)
        if visible and self._bpm > 0 and not self._bpm_lines:
            self._rebuild_bpm_grid()

    def _rebuild_bpm_grid(self):
        for line in self._bpm_lines:
            self.scene.removeItem(line)
        self._bpm_lines.clear()
        if not self._show_bpm_grid or self._bpm <= 0:
            return
        beat_px = (60.0 / self._bpm) * PIXELS_PER_SECOND
        scene_h = self.scene.sceneRect().height()
        beat_num = 1
        x = beat_px
        while x < self.SCENE_WIDTH:
            is_bar = (beat_num % 4 == 0)
            pen = QPen(QColor(255, 200, 0, 80 if is_bar else 35),
                       1.5 if is_bar else 1.0)
            line = self.scene.addLine(x, 0, x, scene_h, pen)
            line.setZValue(2)
            self._bpm_lines.append(line)
            x += beat_px
            beat_num += 1

    # ---- project mutations -----------------------------------------

    def _track_idx_at_y(self, scene_y: float) -> int | None:
        if scene_y < _LANES_Y:
            return None
        idx = int((scene_y - _LANES_Y) / TRACK_HEIGHT)
        return idx if 0 <= idx < len(self.project.tracks) else None

    def _add_clip_at(self, track_idx: int, start: float):
        track = self.project.tracks[track_idx]
        if not track.sub_tracks:
            track.sub_tracks.append(SubTrack())
        track.sub_tracks[0].clips.append(
            Clip(start=max(0.0, start), duration=2.0,
                 pixels=[VirtualPixel(x=0.5, width=0.5)])
        )
        self.refresh()
        self.project_changed.emit()

    def _add_track(self):
        new_track = Track(name=f"Track {len(self.project.tracks) + 1}")
        new_track.sub_tracks.append(SubTrack())
        self.project.tracks.append(new_track)
        self.refresh()
        self.project_changed.emit()

    def _delete_clip(self, clip):
        for track in self.project.tracks:
            for subtrack in track.sub_tracks:
                if clip in subtrack.clips:
                    subtrack.clips.remove(clip)
                    self.refresh()
                    self.project_changed.emit()
                    return

    def _duplicate_clip(self, clip):
        for track in self.project.tracks:
            for subtrack in track.sub_tracks:
                if clip in subtrack.clips:
                    new_clip = copy.deepcopy(clip)
                    new_clip.start += new_clip.duration
                    subtrack.clips.append(new_clip)
                    self.refresh()
                    self.project_changed.emit()
                    return

    # ---- context menu (view level handles all cases) ---------------

    def contextMenuEvent(self, event):
        scene_pos = self.mapToScene(event.pos())

        # Check for clip under cursor first
        clip_item = None
        for item in self.scene.items(scene_pos):
            if isinstance(item, ClipItem):
                clip_item = item
                break

        menu = QMenu()
        menu.setStyleSheet(_MENU_SS)

        if clip_item:
            del_act = menu.addAction("Delete Clip")
            dup_act = menu.addAction("Duplicate Clip")
            act = menu.exec(QCursor.pos())
            if act == del_act:
                self._delete_clip(clip_item.clip)
            elif act == dup_act:
                self._duplicate_clip(clip_item.clip)
        else:
            track_idx = self._track_idx_at_y(scene_pos.y())
            t = max(0.0, scene_pos.x() / PIXELS_PER_SECOND)
            if track_idx is not None:
                menu.addAction(f"Add Clip at {t:.2f}s")
            menu.addAction("Add Track")
            act = menu.exec(QCursor.pos())
            if act is None:
                return
            text = act.text()
            if text.startswith("Add Clip") and track_idx is not None:
                self._add_clip_at(track_idx, t)
            elif text == "Add Track":
                self._add_track()

        event.accept()

    # ---- ruler seek (view level) ------------------------------------

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

    # ---- zoom -------------------------------------------------------

    def wheelEvent(self, event):
        if event.modifiers() in (Qt.ControlModifier, Qt.MetaModifier):
            factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
            self.scale(factor, 1.0)
        else:
            super().wheelEvent(event)
