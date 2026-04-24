"""
Titan Engine v4 — application entry point.

Pipeline: ProjectModel → SpatialMapper → CompositorEngine
        → OutputManager → PlaybackController → Qt GUI
"""
import sys
import logging

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget,
    QVBoxLayout, QHBoxLayout, QSplitter,
    QMenuBar, QFileDialog, QMessageBox,
)
from PySide6.QtCore import Qt, Signal, QObject
from PySide6.QtGui import QKeySequence, QAction

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
from widgets.properties import PropertiesPanel

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
# Demo project (used until a real .titanproj is loaded)
# ------------------------------------------------------------------
def build_demo_project() -> tuple:
    fixture = PhysicalFixture(
        fixture_id="BAR_1", universe=1,
        start_address=1, pixel_count=20, channels_per_pixel=4,
    )
    segment = SpatialSegment(fixture_id="BAR_1", x_start=0.0, x_end=1.0)
    mapper = SpatialMapper(hardware_patch=[fixture], layout=[segment])

    track_a = Track(
        name="Red Pulse", blending_mode="Add",
        params=ParameterSet(dim=1.0, r=255.0),
        sub_tracks=[SubTrack(clips=[
            Clip(start=0.5, duration=2.0,
                 params=ParameterSet(atk_c=0.3, dec_c=0.1, sus_c=0.8, rel_c=1.0),
                 pixels=[VirtualPixel(x=0.5, width=0.7)]),
            Clip(start=3.5, duration=1.5,
                 params=ParameterSet(atk_c=0.05, rel_c=0.6, sus_c=1.0),
                 pixels=[VirtualPixel(x=0.5, width=0.4)]),
        ])],
    )
    track_b = Track(
        name="Blue Ripple", blending_mode="Add",
        params=ParameterSet(dim=0.8, b=200.0),
        sub_tracks=[SubTrack(clips=[
            Clip(start=1.0, duration=1.5,
                 params=ParameterSet(atk_c=0.1, rel_c=1.2, sus_c=0.8, atk_e=0.5, rel_e=0.3),
                 pixels=[VirtualPixel(x=0.25, width=0.35), VirtualPixel(x=0.75, width=0.35)]),
            Clip(start=4.0, duration=1.0,
                 params=ParameterSet(atk_c=0.2, rel_c=0.5, sus_c=1.0),
                 pixels=[VirtualPixel(x=0.5, width=0.8)]),
        ])],
    )
    project = Project(name="Demo Project", spatial_map=[segment], tracks=[track_a, track_b])
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
        self.resize(1280, 720)
        self.setStyleSheet("QMainWindow { background: #1a1a1a; } QWidget { color: white; }")

        # Pipeline
        self.compositor = CompositorEngine(project, mapper)
        self.output_manager = OutputManager(project.output_config)
        self.controller = PlaybackController(
            compositor=self.compositor,
            output_manager=self.output_manager,
            target_fps=44,
        )

        # Frame bridge (render thread → Qt thread)
        self._bridge = FrameBridge()
        self._bridge.frame_ready.connect(self._on_frame)
        self.controller.on_frame_ready = lambda t, u: self._bridge.frame_ready.emit(t, u)

        self._build_menu()
        self._build_ui()
        self._wire_signals()

        logger.info("MainWindow ready — click ▶ to start playback")

    # ------------------------------------------------------------------
    # Menu bar
    # ------------------------------------------------------------------
    def _build_menu(self):
        menubar = self.menuBar()
        menubar.setStyleSheet(
            "QMenuBar { background: #1a1a1a; color: white; }"
            "QMenuBar::item:selected { background: #333; }"
            "QMenu { background: #2a2a2a; color: white; border: 1px solid #444; }"
            "QMenu::item:selected { background: #3a3a3a; }"
        )

        file_menu = menubar.addMenu("File")

        act_new = QAction("New Project", self)
        act_new.setShortcut(QKeySequence.New)
        act_new.triggered.connect(self._action_new_project)
        file_menu.addAction(act_new)

        act_open = QAction("Open Project…", self)
        act_open.setShortcut(QKeySequence.Open)
        act_open.triggered.connect(self._action_open_project)
        file_menu.addAction(act_open)

        act_save = QAction("Save Project", self)
        act_save.setShortcut(QKeySequence.Save)
        act_save.triggered.connect(self._action_save_project)
        file_menu.addAction(act_save)

        act_save_as = QAction("Save Project As…", self)
        act_save_as.setShortcut(QKeySequence.SaveAs)
        act_save_as.triggered.connect(self._action_save_project_as)
        file_menu.addAction(act_save_as)

        file_menu.addSeparator()

        act_open_audio = QAction("Open Audio…", self)
        act_open_audio.triggered.connect(lambda: self.transport.btn_open_audio.click())
        file_menu.addAction(act_open_audio)

        self._save_path: str | None = None

    # ------------------------------------------------------------------
    # UI layout
    # ------------------------------------------------------------------
    def _build_ui(self):
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

        self.headers = TrackHeaderPanel(self.project)
        self.timeline = TimelineWidget(self.project)
        daw_row.addWidget(self.headers)
        daw_row.addWidget(self.timeline, stretch=1)

        daw_widget = QWidget()
        daw_widget.setLayout(daw_row)

        # LED visualizer strip
        self.visualizer = VisualizerWidget(self.mapper)
        self.visualizer.setMinimumHeight(60)

        # Properties panel (collapses when nothing selected)
        self.properties = PropertiesPanel()
        self.properties.setMaximumHeight(200)
        self.properties.setMinimumHeight(0)
        self.properties.hide()

        # Vertical splitter: DAW / visualizer / properties
        self._splitter = QSplitter(Qt.Vertical)
        self._splitter.addWidget(daw_widget)
        self._splitter.addWidget(self.visualizer)
        self._splitter.setSizes([460, 100])
        self._splitter.setStyleSheet(
            "QSplitter::handle { background: #333; height: 2px; }"
        )

        root.addWidget(self._splitter, stretch=1)
        root.addWidget(self.properties)

    # ------------------------------------------------------------------
    # Signal wiring
    # ------------------------------------------------------------------
    def _wire_signals(self):
        # Ruler click → seek
        self.timeline.seek_requested.connect(self.controller.seek)

        # Clip click → properties panel
        self.timeline.clip_selected.connect(self._on_clip_selected)

        # Click on empty area → clear properties
        # (handled by deselecting in the scene — see _on_frame background clear)

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------
    def _on_frame(self, current_t: float, universes: dict):
        if universes:
            self.visualizer.update_frame(next(iter(universes.values())))
        self.timeline.update_playhead(current_t)

    def _on_clip_selected(self, clip):
        # Find the subtrack and track that own this clip so the panel can
        # show resolved (inherited) values alongside clip-level overrides.
        for track in self.project.tracks:
            for subtrack in track.sub_tracks:
                if clip in subtrack.clips:
                    self.properties.show_clip(clip, subtrack, track)
                    self.properties.show()
                    return
        # Fallback: show with no cascade context
        self.properties.show_clip(clip)
        self.properties.show()

    # ------------------------------------------------------------------
    # File menu actions
    # ------------------------------------------------------------------
    def _action_new_project(self):
        reply = QMessageBox.question(
            self, "New Project",
            "Discard current project and start fresh?",
            QMessageBox.Yes | QMessageBox.Cancel,
        )
        if reply == QMessageBox.Yes:
            self.controller.stop()
            project, mapper = build_demo_project()
            self._reload_project(project, mapper)

    def _action_open_project(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Project", "",
            "Titan Project (*.titanproj);;All Files (*)",
        )
        if not path:
            return
        try:
            project = Project.load_from_file(path)
        except Exception as e:
            QMessageBox.critical(self, "Open failed", str(e))
            return
        # Rebuild mapper from project's spatial_map + a placeholder fixture list
        # (full fixture patch editor is a future feature — use project data as-is)
        fixture_map = {seg.fixture_id: seg for seg in project.spatial_map}
        fixtures = [
            PhysicalFixture(
                fixture_id=seg.fixture_id,
                universe=1,
                start_address=1,
                pixel_count=20,
                channels_per_pixel=4,
            )
            for seg in project.spatial_map
        ]
        mapper = SpatialMapper(hardware_patch=fixtures, layout=project.spatial_map)
        self._save_path = path
        self._reload_project(project, mapper)

    def _action_save_project(self):
        if self._save_path:
            self._save_to(self._save_path)
        else:
            self._action_save_project_as()

    def _action_save_project_as(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Project As", "",
            "Titan Project (*.titanproj);;All Files (*)",
        )
        if path:
            self._save_path = path
            self._save_to(path)

    def _save_to(self, path: str):
        try:
            self.project.save_to_file(path)
            self.setWindowTitle(f"Titan Engine v4 — {self.project.name}")
            logger.info(f"Project saved: {path}")
        except Exception as e:
            QMessageBox.critical(self, "Save failed", str(e))

    def _reload_project(self, project: Project, mapper: SpatialMapper):
        """Swap in a new project without recreating the window."""
        self.controller.stop()
        self.project = project
        self.mapper = mapper
        self.compositor = CompositorEngine(project, mapper)
        self.output_manager.close()
        self.output_manager = OutputManager(project.output_config)
        self.controller = PlaybackController(
            compositor=self.compositor,
            output_manager=self.output_manager,
            target_fps=44,
        )
        self.controller.on_frame_ready = lambda t, u: self._bridge.frame_ready.emit(t, u)
        self.transport.set_controller(self.controller)
        self.timeline.project = project
        self.timeline.refresh()
        self.properties.clear()
        self.properties.hide()
        self.setWindowTitle(f"Titan Engine v4 — {project.name}")
        self._wire_signals()

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
