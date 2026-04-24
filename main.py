"""
Titan Engine v4 — application entry point.

Wires together: ProjectModel → SpatialMapper → CompositorEngine
→ OutputManager → PlaybackController → Qt GUI.
"""
import sys
import logging

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget,
    QVBoxLayout, QHBoxLayout, QSplitter,
)
from PySide6.QtCore import Qt, Signal, QObject

from models.project import (
    Project, Track, SubTrack, Clip,
    ParameterSet, VirtualPixel, SpatialSegment,
)
from spatial import PhysicalFixture, SpatialMapper
from compositor import CompositorEngine
from playback import PlaybackController
from output.output_manager import OutputManager
from widgets.transport import TransportBar
from widgets.timeline import TimelineWidget
from widgets.track_header import TrackHeaderPanel
from widgets.visualizer import VisualizerWidget

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# Thread-safe bridge: render thread → Qt main thread
# ------------------------------------------------------------------
class FrameBridge(QObject):
    frame_ready = Signal(float, object)   # (playhead_time, {universe: bytearray})


# ------------------------------------------------------------------
# Demo project
# ------------------------------------------------------------------
def build_demo_project() -> tuple:
    """Build a minimal project for development testing."""
    fixture = PhysicalFixture(
        fixture_id="BAR_1",
        universe=1,
        start_address=1,
        pixel_count=20,
        channels_per_pixel=4,
    )
    segment = SpatialSegment(fixture_id="BAR_1", x_start=0.0, x_end=1.0)
    mapper = SpatialMapper(hardware_patch=[fixture], layout=[segment])

    track_a = Track(
        name="Red Pulse",
        blending_mode="Add",
        params=ParameterSet(dim=1.0, r=255.0),
        sub_tracks=[SubTrack(clips=[
            Clip(
                start=0.5, duration=2.0,
                params=ParameterSet(atk_c=0.3, dec_c=0.1, sus_c=0.8, rel_c=1.0),
                pixels=[VirtualPixel(x=0.5, width=0.7)],
            ),
            Clip(
                start=3.5, duration=1.5,
                params=ParameterSet(atk_c=0.05, rel_c=0.6, sus_c=1.0),
                pixels=[VirtualPixel(x=0.5, width=0.4)],
            ),
        ])],
    )

    track_b = Track(
        name="Blue Ripple",
        blending_mode="Add",
        params=ParameterSet(dim=0.8, b=200.0),
        sub_tracks=[SubTrack(clips=[
            Clip(
                start=1.0, duration=1.5,
                params=ParameterSet(atk_c=0.1, rel_c=1.2, sus_c=0.8,
                                     atk_e=0.5, rel_e=0.3),
                pixels=[
                    VirtualPixel(x=0.25, width=0.35),
                    VirtualPixel(x=0.75, width=0.35),
                ],
            ),
            Clip(
                start=4.0, duration=1.0,
                params=ParameterSet(atk_c=0.2, rel_c=0.5, sus_c=1.0),
                pixels=[VirtualPixel(x=0.5, width=0.8)],
            ),
        ])],
    )

    project = Project(
        name="Demo Project",
        spatial_map=[segment],
        tracks=[track_a, track_b],
    )
    return project, mapper


# ------------------------------------------------------------------
# Main window
# ------------------------------------------------------------------
class MainWindow(QMainWindow):
    def __init__(self, project: Project, mapper: SpatialMapper):
        super().__init__()
        self.project = project
        self.mapper = mapper

        self.setWindowTitle(f"Titan Engine v4 — {project.name}")
        self.resize(1280, 640)
        self.setStyleSheet("QMainWindow { background: #1a1a1a; } QWidget { color: white; }")

        # Pipeline
        self.compositor = CompositorEngine(project, mapper)
        self.output_manager = OutputManager(project.output_config)
        self.controller = PlaybackController(
            compositor=self.compositor,
            output_manager=self.output_manager,
            target_fps=44,
        )

        # Thread-safe signal bridge
        self._bridge = FrameBridge()
        self._bridge.frame_ready.connect(self._on_frame)
        self.controller.on_frame_ready = (
            lambda t, u: self._bridge.frame_ready.emit(t, u)
        )

        # UI
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Transport bar
        self.transport = TransportBar(self.controller)
        root.addWidget(self.transport)

        # DAW row: headers | timeline
        daw_row = QHBoxLayout()
        daw_row.setContentsMargins(0, 0, 0, 0)
        daw_row.setSpacing(0)

        self.headers = TrackHeaderPanel(project)
        self.timeline = TimelineWidget(project)

        daw_row.addWidget(self.headers)
        daw_row.addWidget(self.timeline, stretch=1)

        daw_widget = QWidget()
        daw_widget.setLayout(daw_row)

        # Visualizer strip
        self.visualizer = VisualizerWidget(mapper)
        self.visualizer.setMinimumHeight(80)

        # Splitter: DAW on top, LED strip on bottom
        splitter = QSplitter(Qt.Vertical)
        splitter.addWidget(daw_widget)
        splitter.addWidget(self.visualizer)
        splitter.setSizes([460, 100])
        splitter.setStyleSheet("QSplitter::handle { background: #333; height: 2px; }")

        root.addWidget(splitter, stretch=1)

        logger.info("MainWindow ready — click ▶ to start playback")

    def _on_frame(self, current_t: float, universes: dict):
        # Feed the visualizer with the first available universe packet
        if universes:
            first_packet = next(iter(universes.values()))
            self.visualizer.update_frame(first_packet)
        self.timeline.update_playhead(current_t)

    def closeEvent(self, event):
        self.controller.stop()
        self.output_manager.close()
        logger.info("Shutdown complete")
        super().closeEvent(event)


# ------------------------------------------------------------------
# Entry point
# ------------------------------------------------------------------
def main():
    app = QApplication(sys.argv)
    project, mapper = build_demo_project()
    window = MainWindow(project, mapper)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
