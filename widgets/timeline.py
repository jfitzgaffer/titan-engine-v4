import copy
import uuid

import numpy as np
from PySide6.QtWidgets import (
    QGraphicsView, QGraphicsScene, QGraphicsRectItem, QGraphicsItem,
    QMenu, QInputDialog, QColorDialog,
)
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

# ── BPM grid subdivision definitions ────────────────────────────────
# (beats_per_line, color_rgba, line_width_px)
_GRID_SUBS = [
    (0.25, QColor(255, 200, 0,  8), 0.5),   # 16th notes
    (0.5,  QColor(255, 200, 0, 16), 0.5),   # 8th notes
    (1.0,  QColor(255, 200, 0, 40), 1.0),   # quarter notes (beats)
    (4.0,  QColor(255, 200, 0, 85), 1.5),   # bars (4/4)
]
_MIN_LINE_PX = 4   # don't draw subdivisions finer than this many px apart

# Stable colors for compound-clip groups (hashed from group_id)
_GROUP_COLORS = [
    QColor(255, 100, 100, 60),
    QColor(100, 200, 100, 60),
    QColor(100, 150, 255, 60),
    QColor(255, 200,  50, 60),
    QColor(200, 100, 255, 60),
    QColor(100, 220, 220, 60),
]


def _group_color(gid: str) -> QColor:
    return _GROUP_COLORS[hash(gid) % len(_GROUP_COLORS)]


# ──────────────────────────────────────────────────────────────────────
# Ruler
# ──────────────────────────────────────────────────────────────────────

class TimeRulerItem(QGraphicsItem):
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


# ──────────────────────────────────────────────────────────────────────
# Audio track
# ──────────────────────────────────────────────────────────────────────

class AudioTrackItem(QGraphicsRectItem):
    """Audio reference row — four view modes: spectrogram | waveform | both | none."""

    def __init__(self, width: float):
        super().__init__(0, 0, width, AUDIO_TRACK_HEIGHT)
        self.setPos(0, RULER_HEIGHT)
        self.setZValue(1)
        self.setAcceptedMouseButtons(Qt.NoButton)
        self._spec_image: QImage | None = None
        self._wave_image: QImage | None = None     # legacy / fallback
        self._waveform_rms: np.ndarray | None = None   # raw RMS data (sharp rendering)
        self._waveform_hop_sec: float = 0.01
        self._waveform_cache: QImage | None = None     # rendered at current rect width
        self._view_mode: str = "spectrogram"
        self.setBrush(QBrush(QColor(15, 15, 30)))
        self.setPen(QPen(QColor(40, 40, 60), 1))

    def set_spectrogram_image(self, img: QImage):
        self._spec_image = img.scaled(int(self.rect().width()), AUDIO_TRACK_HEIGHT,
                                      Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        self.update()

    def set_waveform_image(self, img: QImage):
        """Legacy: store a pre-rendered QImage (used as fallback)."""
        self._wave_image = img.scaled(int(self.rect().width()), AUDIO_TRACK_HEIGHT,
                                      Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        self.update()

    def set_waveform_data(self, rms: np.ndarray, hop_sec: float = 0.01):
        """
        Store raw normalized RMS data for pixel-perfect procedural rendering.
        Invalidates the cache so the next paint() re-renders at the correct width.
        """
        self._waveform_rms = np.asarray(rms, dtype=np.float32)
        self._waveform_hop_sec = hop_sec
        self._waveform_cache = None
        self.update()

    def _get_waveform_image(self) -> QImage | None:
        """
        Return a sharp QImage of the waveform at the item's exact pixel width.
        Renders from raw RMS data if available; falls back to legacy _wave_image.
        Caches the result — only re-renders when data changes or width changes.
        """
        if self._waveform_rms is None:
            return self._wave_image

        w = int(self.rect().width())
        h = int(self.rect().height())
        if w <= 0 or h <= 0:
            return None

        # Return cached image if width hasn't changed
        if self._waveform_cache is not None and self._waveform_cache.width() == w:
            return self._waveform_cache

        rms      = self._waveform_rms
        hop_sec  = self._waveform_hop_sec
        n        = len(rms)
        mid      = h // 2

        # Map each pixel column to the nearest RMS sample
        px_per_sample = max(hop_sec * PIXELS_PER_SECOND, 1e-6)
        xs            = np.arange(w, dtype=np.float32)
        sample_idx    = (xs / px_per_sample).astype(np.int32)
        in_range      = sample_idx < n
        vals          = np.where(in_range, rms[np.clip(sample_idx, 0, n - 1)], 0.0)
        halves        = np.clip((vals * mid * 0.92).astype(np.int32), 0, mid)

        img_arr = np.zeros((h, w, 3), dtype=np.uint8)
        ys  = np.arange(h)[:, np.newaxis]       # (h, 1)
        y0s = (mid - halves)[np.newaxis, :]     # (1, w)
        y1s = (mid + halves + 1)[np.newaxis, :] # (1, w)
        mask = (ys >= y0s) & (ys <= y1s)        # (h, w)
        img_arr[mask] = [0, 210, 110]

        img = QImage(img_arr.tobytes(), w, h, w * 3, QImage.Format_RGB888)
        self._waveform_cache = img.copy()
        return self._waveform_cache

    def set_image(self, img: QImage):   # backward-compat
        self.set_spectrogram_image(img)

    def set_view_mode(self, mode: str):
        self._view_mode = mode
        self.update()

    def paint(self, painter, option, widget):
        super().paint(painter, option, widget)
        r, mode = self.rect(), self._view_mode
        wave_img = self._get_waveform_image()
        if mode == "spectrogram":
            if self._spec_image: painter.drawImage(r, self._spec_image)
            else: self._placeholder(painter, r)
        elif mode == "waveform":
            if wave_img: painter.drawImage(r, wave_img)
            else: self._placeholder(painter, r)
        elif mode == "both":
            if self._spec_image: painter.drawImage(r, self._spec_image)
            if wave_img:
                painter.setOpacity(0.65)
                painter.drawImage(r, wave_img)
                painter.setOpacity(1.0)
        # "none": dark background only

    def _placeholder(self, painter, r):
        painter.setPen(QPen(QColor(70, 70, 90)))
        painter.setFont(QFont("Arial", 10))
        painter.drawText(r, Qt.AlignCenter, "Load audio  (File → Open Audio…)")


# ──────────────────────────────────────────────────────────────────────
# Marker
# ──────────────────────────────────────────────────────────────────────

class MarkerItem(QGraphicsItem):
    """
    Draggable vertical marker line + labeled flag at the top.
    Right-click to rename, change color, or delete.
    """

    def __init__(self, time_sec: float, name: str, color: QColor,
                 scene_height: float, on_changed, on_delete_requested):
        super().__init__()
        self.time_sec = time_sec
        self.name = name
        self.color = color
        self._scene_height = scene_height
        self._on_changed = on_changed
        self._on_delete = on_delete_requested

        self.setFlag(QGraphicsItem.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.ItemSendsGeometryChanges, True)
        self.setPos(time_sec * PIXELS_PER_SECOND, 0)
        self.setZValue(9)
        self.setCursor(Qt.SizeHorCursor)

    def _flag_width(self) -> int:
        return max(32, len(self.name) * 6 + 10)

    def boundingRect(self) -> QRectF:
        return QRectF(-2, 0, self._flag_width() + 4, self._scene_height)

    def paint(self, painter, option, widget):
        # Marker line
        painter.setPen(QPen(self.color, 2))
        painter.drawLine(0, 0, 0, int(self._scene_height))
        # Flag background
        fw = self._flag_width()
        flag_rect = QRectF(0, 2, fw, 16)
        painter.fillRect(flag_rect, self.color)
        # Label
        painter.setPen(QPen(QColor(0, 0, 0)))
        painter.setFont(QFont("Arial", 8, QFont.Bold))
        painter.drawText(flag_rect.adjusted(3, 0, -3, 0),
                         Qt.AlignLeft | Qt.AlignVCenter, self.name)

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionChange:
            new_x = max(0.0, value.x())
            self.time_sec = new_x / PIXELS_PER_SECOND
            return QPointF(new_x, 0)
        if change == QGraphicsItem.ItemPositionHasChanged:
            if self._on_changed:
                self._on_changed(self)
        return super().itemChange(change, value)

    def contextMenuEvent(self, event):
        menu = QMenu()
        menu.setStyleSheet(_MENU_SS)
        rename_act  = menu.addAction("Rename…")
        color_act   = menu.addAction("Change Color…")
        menu.addSeparator()
        delete_act  = menu.addAction("Delete Marker")
        chosen = menu.exec(QCursor.pos())
        if chosen == rename_act:
            text, ok = QInputDialog.getText(None, "Rename Marker", "Name:", text=self.name)
            if ok:
                self.name = text
                self.update()
                if self._on_changed: self._on_changed(self)
        elif chosen == color_act:
            c = QColorDialog.getColor(self.color, None, "Marker Color")
            if c.isValid():
                self.color = c
                self.update()
                if self._on_changed: self._on_changed(self)
        elif chosen == delete_act:
            if self._on_delete: self._on_delete(self)
        event.accept()


# ──────────────────────────────────────────────────────────────────────
# Clip item
# ──────────────────────────────────────────────────────────────────────

class ClipItem(QGraphicsRectItem):
    """
    Clip block.  Left/right 8 px edges resize; middle drags (select mode).
    In blade mode, clicks are handled at view level — this item ignores them.
    Selected state draws a thick gold border.
    Grouped clips (same group_id) move together via a class-level sync lock.
    """

    COLORS = [
        QColor(140, 100, 200, 200),
        QColor(80,  160, 220, 200),
        QColor(80,  200, 130, 200),
        QColor(220, 160,  60, 200),
        QColor(220,  80,  80, 200),
    ]

    _group_sync_active: bool = False   # class-level drag-sync guard

    def __init__(self, clip_model, y_offset: float, color_index: int = 0,
                 on_selected=None, timeline=None):
        super().__init__()
        self.clip = clip_model
        self._locked_y = y_offset + 5
        self._on_selected = on_selected
        self._timeline = timeline
        self._resize_edge: str | None = None
        self._drag_origin_x = self._drag_origin_start = self._drag_origin_dur = 0.0
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

    # ── drag / resize ─────────────────────────────────────────────────

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionChange and self._resize_edge is None:
            x = max(0.0, value.x())
            # Snap to grid
            if self._timeline and self._timeline._snap_enabled:
                x = self._timeline._snap_x(x)
            new_pos = QPointF(x, self._locked_y)

            # Sync group members
            if (not ClipItem._group_sync_active
                    and self.clip.group_id
                    and self._timeline):
                delta_x = x - self.pos().x()
                if abs(delta_x) > 0.001:
                    ClipItem._group_sync_active = True
                    try:
                        for item in self._timeline.scene.items():
                            if (isinstance(item, ClipItem)
                                    and item is not self
                                    and item.clip.group_id == self.clip.group_id):
                                nx = max(0.0, item.pos().x() + delta_x)
                                item.setPos(nx, item._locked_y)
                                item.clip.start = nx / PIXELS_PER_SECOND
                    finally:
                        ClipItem._group_sync_active = False
            return new_pos

        if change == QGraphicsItem.ItemPositionHasChanged and self._resize_edge is None:
            self.clip.start = self.pos().x() / PIXELS_PER_SECOND
        return super().itemChange(change, value)

    def _edge_at(self, local_x: float) -> str | None:
        w = self.rect().width()
        if local_x <= HANDLE_WIDTH: return "left"
        if local_x >= w - HANDLE_WIDTH: return "right"
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
                if self._on_selected: self._on_selected(self.clip)
                event.accept()
                return
            if self._on_selected: self._on_selected(self.clip)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._resize_edge:
            dx = (event.scenePos().x() - self._drag_origin_x) / PIXELS_PER_SECOND
            if self._resize_edge == "right":
                self.clip.duration = max(0.1, self._drag_origin_dur + dx)
            else:
                new_end   = self._drag_origin_start + self._drag_origin_dur
                new_start = min(new_end - 0.1, max(0.0, self._drag_origin_start + dx))
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

    # ── paint ─────────────────────────────────────────────────────────

    def paint(self, painter, option, widget):
        r = self.rect()
        # Group tint under clip body
        if self.clip.group_id:
            painter.fillRect(r, _group_color(self.clip.group_id))
        painter.fillRect(r, self._color)
        painter.fillRect(QRectF(0, 0, HANDLE_WIDTH, r.height()), QColor(255, 255, 255, 30))
        painter.fillRect(QRectF(r.width()-HANDLE_WIDTH, 0, HANDLE_WIDTH, r.height()),
                         QColor(255, 255, 255, 30))
        painter.setPen(QPen(QColor(255, 255, 255, 180)))
        painter.setFont(QFont("Arial", 8))
        label = self.clip.duration_label if hasattr(self.clip, 'duration_label') else f"{self.clip.duration:.2f}s"
        painter.drawText(r.adjusted(HANDLE_WIDTH+2, 2, -HANDLE_WIDTH-2, -2),
                         Qt.AlignLeft | Qt.AlignTop, f"{self.clip.duration:.2f}s")
        # Group badge
        if self.clip.group_id:
            badge_rect = QRectF(r.width() - HANDLE_WIDTH - 12, 2, 10, 10)
            painter.fillRect(badge_rect, _group_color(self.clip.group_id).darker(120))
            painter.setPen(QPen(QColor(255, 255, 255, 200)))
            painter.setFont(QFont("Arial", 6, QFont.Bold))
            painter.drawText(badge_rect, Qt.AlignCenter, "G")
        # Selection / default border
        painter.setPen(QPen(QColor(255, 215, 0), 3) if self.isSelected()
                       else QPen(QColor(220, 220, 220), 1))
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(r.adjusted(1, 1, -1, -1))


# ──────────────────────────────────────────────────────────────────────
# Timeline widget
# ──────────────────────────────────────────────────────────────────────

class TimelineWidget(QGraphicsView):
    """
    DAW timeline — DaVinci Resolve-inspired controls.

    Key bindings (when focused):
      V / B           select / blade tool
      M               place marker at playhead
      S               toggle snap-to-BPM-grid
      Delete          delete selected clips
      Ctrl+A          select all clips
      Ctrl+G          group selected clips into compound clip
      Ctrl+Shift+G    ungroup selected
      Ctrl+D          duplicate selected clips
      Home / End      jump to start / end edit point
      ← / →           previous / next edit point
      Shift+← / →     nudge selected clips ±0.1 s
      + / =           zoom in      −  zoom out      \  reset zoom
    """

    seek_requested  = Signal(float)
    clip_selected   = Signal(object)
    project_changed = Signal()
    tool_changed    = Signal(str)

    SCENE_WIDTH = 5000     # mutable instance variable, extended by set_scene_duration()

    def __init__(self, project):
        super().__init__()
        self.project = project
        self._seeking = False
        self._audio_item: AudioTrackItem | None = None
        self._bpm: float = 0.0
        self._tempo_map: list = []
        self._show_bpm_grid: bool = False
        self._bpm_lines: list = []
        self._tool: str = "select"
        self._playhead_time: float = 0.0
        self._snap_enabled: bool = False
        self._marker_items: list = []   # MarkerItem instances in scene

        self.scene = QGraphicsScene(self)
        self.setScene(self.scene)
        self.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.setRenderHint(QPainter.Antialiasing)
        self.setBackgroundBrush(QBrush(QColor(25, 25, 25)))
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.setDragMode(QGraphicsView.RubberBandDrag)
        self.setFocusPolicy(Qt.StrongFocus)

        self.playhead_line = None
        self._populate_scene()

    # ── scene build ───────────────────────────────────────────────────

    def _populate_scene(self):
        self.scene.clear()
        self._audio_item = None
        self._bpm_lines.clear()
        self._marker_items.clear()

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
                        timeline=self,
                    ))
            y += TRACK_HEIGHT

        total_h = max(y, _LANES_Y + TRACK_HEIGHT)
        self.scene.setSceneRect(0, 0, self.SCENE_WIDTH, total_h)
        self.playhead_line = self.scene.addLine(
            0, 0, 0, total_h, QPen(QColor(255, 50, 50), 2))
        self.playhead_line.setZValue(10)

        # Restore markers from project
        for m in self.project.markers:
            self._add_marker_item(m.time_sec, m.name,
                                  QColor(m.color_hex), total_h)

        if self._show_bpm_grid:
            self._rebuild_bpm_grid()

    def refresh(self):
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

    # ── audio image passthrough ───────────────────────────────────────

    def set_audio_image(self, img):
        if self._audio_item: self._audio_item.set_spectrogram_image(img)

    def set_spectrogram_image(self, img):
        if self._audio_item: self._audio_item.set_spectrogram_image(img)

    def set_waveform_image(self, img):
        if self._audio_item: self._audio_item.set_waveform_image(img)

    def set_waveform_data(self, rms, hop_sec: float = 0.01):
        if self._audio_item: self._audio_item.set_waveform_data(rms, hop_sec)

    def set_audio_view_mode(self, mode: str):
        if self._audio_item: self._audio_item.set_view_mode(mode)

    # ── dynamic scene width ───────────────────────────────────────────

    def set_scene_duration(self, seconds: float):
        """Extend the scene to cover at least this many seconds of audio."""
        needed = seconds * PIXELS_PER_SECOND + 500   # 5 s padding
        if needed > self.SCENE_WIDTH:
            self.SCENE_WIDTH = needed
            self.refresh()

    # ── playhead + autoscroll ─────────────────────────────────────────

    def update_playhead(self, time_seconds: float):
        self._playhead_time = time_seconds
        if not self.playhead_line:
            return
        x = time_seconds * PIXELS_PER_SECOND
        self.playhead_line.setPos(x, 0)

        # Autoscroll: keep playhead in the middle 70 % of the viewport
        vr  = self.viewport().rect()
        vpx = self.mapFromScene(QPointF(x, 0)).x()
        left_margin  = vr.width() * 0.15
        right_margin = vr.width() * 0.80
        if vpx < left_margin or vpx > right_margin:
            target = x - vr.width() * 0.25
            self.horizontalScrollBar().setValue(int(max(0, target)))

    # ── BPM / tempo map grid ──────────────────────────────────────────

    def set_bpm(self, bpm: float):
        self._bpm = bpm
        if not self._tempo_map:
            self._tempo_map = [(0.0, bpm)]
        if self._show_bpm_grid:
            self._rebuild_bpm_grid()

    def set_tempo_map(self, tempo_map: list):
        self._tempo_map = tempo_map
        if tempo_map:
            self._bpm = tempo_map[0][1]
        if self._show_bpm_grid:
            self._rebuild_bpm_grid()

    def set_bpm_grid_visible(self, visible: bool):
        self._show_bpm_grid = visible
        for line in self._bpm_lines:
            line.setVisible(visible)
        if visible and not self._bpm_lines:
            self._rebuild_bpm_grid()

    def _rebuild_bpm_grid(self):
        for line in self._bpm_lines:
            self.scene.removeItem(line)
        self._bpm_lines.clear()
        if not self._show_bpm_grid:
            return

        tmap = self._tempo_map if self._tempo_map else ([(0.0, self._bpm)] if self._bpm > 0 else [])
        if not tmap:
            return

        scene_h = self.scene.sceneRect().height()
        segments = []
        for i, (t_start, bpm) in enumerate(tmap):
            t_end = tmap[i + 1][0] if i + 1 < len(tmap) else self.SCENE_WIDTH / PIXELS_PER_SECOND
            segments.append((t_start, t_end, bpm))

        for (seg_start, seg_end, bpm) in segments:
            if bpm <= 0:
                continue
            beat_sec = 60.0 / bpm
            beat_px  = beat_sec * PIXELS_PER_SECOND
            x0 = seg_start * PIXELS_PER_SECOND
            x1 = min(seg_end * PIXELS_PER_SECOND, self.SCENE_WIDTH)

            for div_beats, color, lw in _GRID_SUBS:
                div_px = beat_px * div_beats
                if div_px < _MIN_LINE_PX:
                    continue
                n = max(0, int(x0 / div_px))
                x = n * div_px
                if x < x0:
                    x += div_px
                while x <= x1:
                    line = self.scene.addLine(x, 0, x, scene_h, QPen(color, lw))
                    line.setZValue(2)
                    self._bpm_lines.append(line)
                    x += div_px

    # ── snap ─────────────────────────────────────────────────────────

    def _snap_x(self, x: float) -> float:
        """Snap an X pixel position to the nearest 16th-note grid line."""
        bpm = self._bpm
        if bpm <= 0:
            return x
        # Find the bpm segment for this time
        t = x / PIXELS_PER_SECOND
        for seg_t, seg_bpm in reversed(self._tempo_map or [(0.0, bpm)]):
            if t >= seg_t:
                bpm = seg_bpm
                break
        beat_sec = 60.0 / bpm
        snap_sec = beat_sec / 4.0           # 16th-note resolution
        snapped  = round(t / snap_sec) * snap_sec
        return snapped * PIXELS_PER_SECOND

    # ── markers ──────────────────────────────────────────────────────

    def add_marker(self, time_sec: float, name: str = "Marker",
                   color: QColor = None):
        """Add a marker at time_sec and sync to project.markers."""
        if color is None:
            color = QColor(255, 220, 50)
        scene_h = self.scene.sceneRect().height()
        item = self._add_marker_item(time_sec, name, color, scene_h)
        # Persist to project
        from models.project import TimelineMarker
        self.project.markers.append(
            TimelineMarker(time_sec=time_sec, name=name,
                           color_hex=color.name())
        )
        return item

    def _add_marker_item(self, time_sec: float, name: str,
                         color: QColor, scene_h: float) -> MarkerItem:
        item = MarkerItem(
            time_sec, name, color, scene_h,
            on_changed=self._on_marker_changed,
            on_delete_requested=self._on_marker_delete,
        )
        self.scene.addItem(item)
        self._marker_items.append(item)
        return item

    def _on_marker_changed(self, item: MarkerItem):
        """Sync a moved/renamed/recolored marker back to project.markers."""
        for pm in self.project.markers:
            # Match by approximate original position — use list index via item list
            mi = self._marker_items.index(item) if item in self._marker_items else -1
            if mi >= 0 and mi < len(self.project.markers):
                self.project.markers[mi].time_sec   = item.time_sec
                self.project.markers[mi].name       = item.name
                self.project.markers[mi].color_hex  = item.color.name()
                break

    def _on_marker_delete(self, item: MarkerItem):
        mi = self._marker_items.index(item) if item in self._marker_items else -1
        if mi >= 0:
            self._marker_items.pop(mi)
            if mi < len(self.project.markers):
                self.project.markers.pop(mi)
        self.scene.removeItem(item)

    # ── tool mode ────────────────────────────────────────────────────

    def set_tool(self, tool: str):
        self._tool = tool
        if tool == "blade":
            self.setCursor(Qt.CrossCursor)
            self.setDragMode(QGraphicsView.NoDrag)
        else:
            self.unsetCursor()
            self.setDragMode(QGraphicsView.RubberBandDrag)
        self.tool_changed.emit(tool)

    # ── project mutations ─────────────────────────────────────────────

    def _track_idx_at_y(self, scene_y: float) -> int | None:
        if scene_y < _LANES_Y:
            return None
        idx = int((scene_y - _LANES_Y) / TRACK_HEIGHT)
        return idx if 0 <= idx < len(self.project.tracks) else None

    def _all_edit_points(self) -> list:
        pts = set()
        for track in self.project.tracks:
            for st in track.sub_tracks:
                for clip in st.clips:
                    pts.add(clip.start)
                    pts.add(clip.start + clip.duration)
        return sorted(pts)

    def _add_clip_at(self, track_idx: int, start: float):
        track = self.project.tracks[track_idx]
        if not track.sub_tracks:
            track.sub_tracks.append(SubTrack())
        if self._snap_enabled:
            start_x = self._snap_x(start * PIXELS_PER_SECOND)
            start = start_x / PIXELS_PER_SECOND
        track.sub_tracks[0].clips.append(
            Clip(start=max(0.0, start), duration=2.0,
                 pixels=[VirtualPixel(x=0.5, width=0.5)]))
        self.refresh()
        self.project_changed.emit()

    def _add_track(self):
        t = Track(name=f"Track {len(self.project.tracks) + 1}")
        t.sub_tracks.append(SubTrack())
        self.project.tracks.append(t)
        self.refresh()
        self.project_changed.emit()

    def _delete_clip(self, clip):
        for track in self.project.tracks:
            for st in track.sub_tracks:
                if clip in st.clips:
                    st.clips.remove(clip)
                    self.refresh()
                    self.project_changed.emit()
                    return

    def _delete_selected_clips(self):
        clips = [i.clip for i in self.scene.selectedItems() if isinstance(i, ClipItem)]
        if not clips:
            return
        for track in self.project.tracks:
            for st in track.sub_tracks:
                st.clips = [c for c in st.clips if c not in clips]
        self.refresh()
        self.project_changed.emit()

    def _select_all(self):
        for item in self.scene.items():
            if isinstance(item, ClipItem):
                item.setSelected(True)

    def _duplicate_clip(self, clip):
        for track in self.project.tracks:
            for st in track.sub_tracks:
                if clip in st.clips:
                    nc = copy.deepcopy(clip)
                    nc.start += nc.duration
                    st.clips.append(nc)
                    self.refresh()
                    self.project_changed.emit()
                    return

    def _duplicate_selected(self):
        """Duplicate all selected clips, preserving relative positions and group IDs."""
        selected = [i.clip for i in self.scene.selectedItems() if isinstance(i, ClipItem)]
        if not selected:
            return
        min_start = min(c.start for c in selected)
        max_end   = max(c.start + c.duration for c in selected)
        offset    = max_end - min_start
        group_map: dict[str, str] = {}   # old_gid → new_gid
        for track in self.project.tracks:
            for st in track.sub_tracks:
                new_clips = []
                for clip in st.clips:
                    if clip in selected:
                        nc = copy.deepcopy(clip)
                        nc.start += offset
                        if nc.group_id:
                            if nc.group_id not in group_map:
                                group_map[nc.group_id] = str(uuid.uuid4())[:8]
                            nc.group_id = group_map[nc.group_id]
                        new_clips.append(nc)
                st.clips.extend(new_clips)
        self.refresh()
        self.project_changed.emit()

    def _group_selected(self):
        """Assign a shared group_id to all selected clips (compound clip)."""
        items = [i for i in self.scene.selectedItems() if isinstance(i, ClipItem)]
        if len(items) < 2:
            return
        gid = str(uuid.uuid4())[:8]
        for item in items:
            item.clip.group_id = gid
        self.refresh()
        self.project_changed.emit()

    def _ungroup_selected(self):
        """Remove group_id from selected clips."""
        items = [i for i in self.scene.selectedItems() if isinstance(i, ClipItem)]
        for item in items:
            item.clip.group_id = ""
        self.refresh()
        self.project_changed.emit()

    def _split_clip_at(self, clip, split_time: float):
        if split_time <= clip.start or split_time >= clip.start + clip.duration:
            return
        left  = copy.deepcopy(clip)
        left.duration  = split_time - clip.start
        right = copy.deepcopy(clip)
        right.start    = split_time
        right.duration = (clip.start + clip.duration) - split_time
        for track in self.project.tracks:
            for st in track.sub_tracks:
                if clip in st.clips:
                    idx = st.clips.index(clip)
                    st.clips[idx:idx+1] = [left, right]
                    self.refresh()
                    self.project_changed.emit()
                    return

    def _nudge_selected(self, delta_sec: float):
        for item in self.scene.selectedItems():
            if isinstance(item, ClipItem):
                item.clip.start = max(0.0, item.clip.start + delta_sec)
        self.refresh()
        self.project_changed.emit()

    # ── keyboard shortcuts ─────────────────────────────────────────────

    def keyPressEvent(self, event):
        key  = event.key()
        mods = event.modifiers()
        ctrl  = bool(mods & Qt.ControlModifier)
        shift = bool(mods & Qt.ShiftModifier)

        if key == Qt.Key_V:
            self.set_tool("select")
        elif key == Qt.Key_B:
            self.set_tool("blade")
        elif key == Qt.Key_M:
            self.add_marker(self._playhead_time)
        elif key == Qt.Key_S:
            self._snap_enabled = not self._snap_enabled
            snap_state = "ON" if self._snap_enabled else "OFF"
            # Brief visual feedback via tooltip-style (no dialog needed)
            self.setToolTip(f"Snap: {snap_state}")
        elif key in (Qt.Key_Delete, Qt.Key_Backspace):
            self._delete_selected_clips()
        elif ctrl and key == Qt.Key_A:
            self._select_all()
        elif ctrl and shift and key == Qt.Key_G:
            self._ungroup_selected()
        elif ctrl and key == Qt.Key_G:
            self._group_selected()
        elif ctrl and key == Qt.Key_D:
            self._duplicate_selected()
        elif key == Qt.Key_Home:
            self.seek_requested.emit(0.0)
        elif key == Qt.Key_End:
            pts = self._all_edit_points()
            if pts: self.seek_requested.emit(pts[-1])
        elif key == Qt.Key_Left:
            if shift:
                self._nudge_selected(-0.1)
            else:
                t = self._playhead_time
                pts = [p for p in self._all_edit_points() if p < t - 0.01]
                if pts: self.seek_requested.emit(pts[-1])
        elif key == Qt.Key_Right:
            if shift:
                self._nudge_selected(0.1)
            else:
                t = self._playhead_time
                pts = [p for p in self._all_edit_points() if p > t + 0.01]
                if pts: self.seek_requested.emit(pts[0])
        elif key in (Qt.Key_Plus, Qt.Key_Equal):
            self.scale(1.25, 1.0)
        elif key == Qt.Key_Minus:
            self.scale(0.8, 1.0)
        elif key == Qt.Key_Backslash:
            self.resetTransform()
        else:
            super().keyPressEvent(event)

    # ── context menu ──────────────────────────────────────────────────

    def contextMenuEvent(self, event):
        scene_pos = self.mapToScene(event.pos())

        clip_item = next(
            (i for i in self.scene.items(scene_pos) if isinstance(i, ClipItem)),
            None,
        )

        menu = QMenu()
        menu.setStyleSheet(_MENU_SS)

        if clip_item:
            del_act = menu.addAction("Delete Clip")
            dup_act = menu.addAction("Duplicate Clip")
            spl_act = menu.addAction(f"Split at {self._playhead_time:.2f}s")
            menu.addSeparator()
            if clip_item.clip.group_id:
                ug_act  = menu.addAction("Ungroup")
                grp_act = None
            else:
                grp_act = menu.addAction("Group with Selected")
                ug_act  = None
            act = menu.exec(QCursor.pos())
            if act == del_act:
                self._delete_clip(clip_item.clip)
            elif act == dup_act:
                self._duplicate_clip(clip_item.clip)
            elif act == spl_act:
                self._split_clip_at(clip_item.clip, self._playhead_time)
            elif act is not None and act == grp_act:
                if not clip_item.isSelected():
                    clip_item.setSelected(True)
                self._group_selected()
            elif act is not None and act == ug_act:
                if not clip_item.isSelected():
                    clip_item.setSelected(True)
                self._ungroup_selected()
        else:
            track_idx = self._track_idx_at_y(scene_pos.y())
            t = max(0.0, scene_pos.x() / PIXELS_PER_SECOND)
            mark_act = menu.addAction(f"Add Marker at {t:.2f}s")
            if track_idx is not None:
                menu.addAction(f"Add Clip at {t:.2f}s")
            menu.addAction("Add Track")
            sel_items = [i for i in self.scene.selectedItems() if isinstance(i, ClipItem)]
            if sel_items:
                menu.addSeparator()
                menu.addAction("Delete Selected")
                menu.addAction("Group Selected")
                menu.addAction("Duplicate Selected")
            act = menu.exec(QCursor.pos())
            if act is None:
                return
            text = act.text()
            if act == mark_act:
                self.add_marker(t)
            elif text.startswith("Add Clip") and track_idx is not None:
                self._add_clip_at(track_idx, t)
            elif text == "Add Track":
                self._add_track()
            elif text == "Delete Selected":
                self._delete_selected_clips()
            elif text == "Group Selected":
                self._group_selected()
            elif text == "Duplicate Selected":
                self._duplicate_selected()

        event.accept()

    # ── ruler seek (view level) ───────────────────────────────────────

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            scene_y = self.mapToScene(event.pos()).y()
            # Ruler seek
            if 0 <= scene_y <= RULER_HEIGHT:
                self._seeking = True
                t = max(0.0, self.mapToScene(event.pos()).x() / PIXELS_PER_SECOND)
                self.seek_requested.emit(t)
                event.accept()
                return
            # Blade tool: split clip under cursor
            if self._tool == "blade":
                t = max(0.0, self.mapToScene(event.pos()).x() / PIXELS_PER_SECOND)
                for item in self.scene.items(self.mapToScene(event.pos())):
                    if isinstance(item, ClipItem):
                        self._split_clip_at(item.clip, t)
                        break
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

    # ── zoom ──────────────────────────────────────────────────────────

    def wheelEvent(self, event):
        if event.modifiers() in (Qt.ControlModifier, Qt.MetaModifier):
            factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
            self.scale(factor, 1.0)
        else:
            super().wheelEvent(event)
