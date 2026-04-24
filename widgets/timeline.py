from PySide6.QtWidgets import QGraphicsView, QGraphicsScene, QGraphicsRectItem, QGraphicsItem
from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import QColor, QBrush, QPen, QPainter

# We need a scale: How many pixels represent 1 second of time?
PIXELS_PER_SECOND = 100
TRACK_HEIGHT = 60


class ClipItem(QGraphicsRectItem):
    """The interactive block you drag around the timeline."""

    def __init__(self, clip_model, y_offset):
        super().__init__()
        self.clip = clip_model

        # Translate math time into screen pixels
        x = self.clip.start * PIXELS_PER_SECOND
        width = self.clip.duration * PIXELS_PER_SECOND

        self.setRect(0, 0, width, TRACK_HEIGHT - 10)
        self.setPos(x, y_offset + 5)  # 5px padding so it sits nicely inside the track lane

        # The magic flags that make QGraphicsScene amazing
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.ItemSendsGeometryChanges, True)

        # Styling
        self.setBrush(QBrush(QColor(140, 100, 200, 200)))  # Nice translucent purple
        self.setPen(QPen(QColor(200, 200, 200), 1))

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionChange:
            # Clamp the X value so you can't drag it into negative time
            new_x = max(0.0, value.x())
            # Safely pass the locked Y and clamped X to the graphics framework
            return super().itemChange(change, QPointF(new_x, self.y()))

        if change == QGraphicsItem.ItemPositionHasChanged:
            # Update our project data model when the drag finishes
            self.clip.start = self.pos().x() / PIXELS_PER_SECOND

        return super().itemChange(change, value)


from PySide6.QtWidgets import QGraphicsView, QGraphicsScene, QGraphicsRectItem, QGraphicsItem
from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import QColor, QBrush, QPen, QPainter

PIXELS_PER_SECOND = 100
TRACK_HEIGHT = 60


# ... (Keep your ClipItem class exactly as it is up here) ...

class TimelineWidget(QGraphicsView):
    """The main view window for the DAW timeline."""

    def __init__(self, project):
        super().__init__()
        self.project = project

        self.scene = QGraphicsScene(self)
        self.setScene(self.scene)

        # View behavior
        self.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.setRenderHint(QPainter.Antialiasing)
        self.setBackgroundBrush(QBrush(QColor(25, 25, 25)))

        # We only want the vertical scrollbar if we have a ton of tracks
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        self.playhead_line = None
        self._populate_scene()

    def _populate_scene(self):
        y_offset = 0

        for track in self.project.tracks:
            # Draw the dark background lane for the track
            track_bg = QGraphicsRectItem(0, y_offset, 3000, TRACK_HEIGHT)
            track_bg.setBrush(QBrush(QColor(40, 40, 40)))
            track_bg.setPen(QPen(QColor(20, 20, 20), 0))
            self.scene.addItem(track_bg)

            # Spawn the clips
            for subtrack in track.sub_tracks:
                for clip in subtrack.clips:
                    clip_item = ClipItem(clip, y_offset)
                    self.scene.addItem(clip_item)

            y_offset += TRACK_HEIGHT

        # DYNAMIC HEIGHT: Set the scene height to exactly match our tracks!
        # (We keep 3000 width so you can scroll horizontally through time)
        self.scene.setSceneRect(0, 0, 3000, max(y_offset, 100))

        # Add the bright red playhead line
        self.playhead_line = self.scene.addLine(0, 0, 0, y_offset, QPen(QColor(255, 50, 50), 2))
        self.playhead_line.setZValue(10)  # Keeps it drawn on top of the clips

    def update_playhead(self, time_seconds: float):
        """Moves the red line across the screen based on the clock."""
        if self.playhead_line:
            x_pos = time_seconds * PIXELS_PER_SECOND
            self.playhead_line.setPos(x_pos, 0)

    def wheelEvent(self, event):
        """Handles mouse wheel scrolling and DAW-style zooming."""
        # Check if the user is holding Ctrl (Windows) or Cmd (Mac)
        if event.modifiers() == Qt.ControlModifier or event.modifiers() == Qt.MetaModifier:

            # Determine zoom direction based on the scroll wheel delta
            if event.angleDelta().y() > 0:
                zoom_factor = 1.15  # Zoom in
            else:
                zoom_factor = 1 / 1.15  # Zoom out

            # We ONLY scale the X-axis! Tracks should not get taller when we zoom into time.
            self.scale(zoom_factor, 1.0)

        else:
            # If they aren't holding Cmd/Ctrl, just scroll left/right/up/down normally
            super().wheelEvent(event)