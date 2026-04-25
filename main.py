"""
Titan Engine v4 — application entry point.

Pipeline: ProjectModel → SpatialMapper → CompositorEngine
        → OutputManager → PlaybackController → Qt GUI
"""
import sys
import logging

import numpy as np
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget,
    QVBoxLayout, QHBoxLayout, QSplitter,
    QFileDialog, QMessageBox,
)
from PySide6.QtCore import Qt, Signal, QObject, QThread
from PySide6.QtGui import QKeySequence, QAction, QImage, QShortcut

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
    frame_ready = Signal(float, object)


# ------------------------------------------------------------------
# Audio spectrogram worker
# ------------------------------------------------------------------
class AudioAnalysisWorker(QThread):
    """
    Computes a colored spectrogram from an audio file in a background thread.
    Emits result(QImage) when done. Uses only numpy — no librosa required.
    """
    result = Signal(object)   # QImage

    def __init__(self, audio_path: str, target_width: int = 2000, target_height: int = 80):
        super().__init__()
        self._path = audio_path
        self._w = target_width
        self._h = target_height

    def run(self):
        try:
            qimg = self._compute()
            if qimg is not None:
                self.result.emit(qimg)
        except Exception as e:
            logger.warning(f"Audio analysis failed: {e}")

    def _compute(self) -> QImage | None:
        try:
            import soundfile as sf
        except ImportError:
            logger.warning("soundfile not installed — spectrogram unavailable")
            return None

        data, sr = sf.read(self._path, dtype='float32', always_2d=True)
        mono = data.mean(axis=1)

        n_fft  = 2048
        n_freq = n_fft // 2 + 1
        hop    = max(1, len(mono) // self._w)

        # Build STFT column by column
        window = np.hanning(n_fft).astype(np.float32)
        n_frames = self._w
        spec = np.zeros((n_freq, n_frames), dtype=np.float32)
        for i in range(n_frames):
            start = i * hop
            chunk = mono[start: start + n_fft]
            if len(chunk) < n_fft:
                chunk = np.pad(chunk, (0, n_fft - len(chunk)))
            spec[:, i] = np.abs(np.fft.rfft(chunk * window))

        # Log amplitude, keep lower 60% of frequencies (musical range)
        cutoff = int(n_freq * 0.60)
        spec = np.log1p(spec[:cutoff, :])

        # Resize vertically to target_height via linear interpolation
        y_src = np.linspace(0, cutoff - 1, self._h).astype(int)
        spec = spec[y_src, :]

        # Flip so low frequencies are at the bottom
        spec = np.flipud(spec)

        # Normalize to [0, 1]
        s_min, s_max = spec.min(), spec.max()
        if s_max > s_min:
            spec = (spec - s_min) / (s_max - s_min)
        else:
            spec = np.zeros_like(spec)

        # Colorize: black→purple→blue→cyan→green→yellow→red
        r = np.clip(spec * 3 - 1.5, 0, 1)
        g = np.clip(spec * 3 - 0.5, 0, 1) * np.clip(2.5 - spec * 3, 0, 1)
        b = np.clip(1.5 - spec * 3, 0, 1) + np.clip(spec * 3 - 2, 0, 1)

        rgb = np.stack([
            (r * 255).astype(np.uint8),
            (g * 255).astype(np.uint8),
            (b * 255).astype(np.uint8),
        ], axis=2)

        h, w = rgb.shape[:2]
        img = QImage(rgb.tobytes(), w, h, w * 3, QImage.Format_RGB888)
        return img.copy()   # detach from the numpy buffer


# ------------------------------------------------------------------
# Demo project
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
                 params=ParameterSet(atk_c=0.1, rel_c=1.2, sus_c=0.8,
                                     atk_e=0.5, rel_e=0.3),
                 pixels=[VirtualPixel(x=0.25, width=0.35),
                         VirtualPixel(x=0.75, width=0.35)]),
            Clip(start=4.0, duration=1.0,
                 params=ParameterSet(atk_c=0.2, rel_c=0.5, sus_c=1.0),
                 pixels=[VirtualPixel(x=0.5, width=0.8)]),
        ])],
    )
    project = Project(name="Demo Project", spatial_map=[segment],
                      tracks=[track_a, track_b])
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
        self.resize(1400, 720)
        self.setStyleSheet("QMainWindow { background: #1a1a1a; } QWidget { color: white; }")

        self._save_path: str | None = None
        self._analysis_worker: AudioAnalysisWorker | None = None

        # Pipeline
        self.compositor = CompositorEngine(project, mapper)
        self.output_manager = OutputManager(project.output_config)
        self.controller = PlaybackController(
            compositor=self.compositor,
            output_manager=self.output_manager,
            target_fps=44,
        )

        self._bridge = FrameBridge()
        self._bridge.frame_ready.connect(self._on_frame)
        self.controller.on_frame_ready = lambda t, u: self._bridge.frame_ready.emit(t, u)

        self._build_menu()
        self._build_ui()
        self._wire_signals()

        logger.info("MainWindow ready — click ▶ or press Space to start playback")

    # ------------------------------------------------------------------
    # Menu
    # ------------------------------------------------------------------
    def _build_menu(self):
        mb = self.menuBar()
        mb.setStyleSheet(
            "QMenuBar { background: #1a1a1a; color: white; }"
            "QMenuBar::item:selected { background: #333; }"
            "QMenu { background: #2a2a2a; color: white; border: 1px solid #444; }"
            "QMenu::item:selected { background: #3a3a3a; }"
        )
        file_menu = mb.addMenu("File")

        def act(label, shortcut=None, slot=None):
            a = QAction(label, self)
            if shortcut:
                a.setShortcut(QKeySequence(shortcut))
            if slot:
                a.triggered.connect(slot)
            file_menu.addAction(a)
            return a

        act("New Project",    "Ctrl+N",       self._action_new)
        act("Open Project…",  "Ctrl+O",       self._action_open)
        act("Save Project",   "Ctrl+S",       self._action_save)
        act("Save Project As…","Ctrl+Shift+S", self._action_save_as)
        file_menu.addSeparator()
        act("Open Audio…",    slot=lambda: self.transport.btn_open_audio.click())

    # ------------------------------------------------------------------
    # UI layout
    # ------------------------------------------------------------------
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Transport bar (full width)
        self.transport = TransportBar(self.controller)
        root.addWidget(self.transport)

        # Main area: horizontal split [properties | DAW+visualizer]
        h_split = QSplitter(Qt.Horizontal)
        h_split.setStyleSheet("QSplitter::handle { background: #333; width: 2px; }")

        # Left: properties panel (always visible, shows "no selection" state)
        self.properties = PropertiesPanel()
        self.properties.setMinimumWidth(200)
        self.properties.setMaximumWidth(320)
        h_split.addWidget(self.properties)

        # Right: vertical split [headers+timeline | visualizer]
        right = QWidget()
        right.setStyleSheet("background: #1a1a1a;")
        right_vbox = QVBoxLayout(right)
        right_vbox.setContentsMargins(0, 0, 0, 0)
        right_vbox.setSpacing(0)

        daw_row = QHBoxLayout()
        daw_row.setContentsMargins(0, 0, 0, 0)
        daw_row.setSpacing(0)

        self.headers  = TrackHeaderPanel(self.project)
        self.timeline = TimelineWidget(self.project)
        daw_row.addWidget(self.headers)
        daw_row.addWidget(self.timeline, stretch=1)

        daw_widget = QWidget()
        daw_widget.setLayout(daw_row)

        self.visualizer = VisualizerWidget(self.mapper)
        self.visualizer.setMinimumHeight(60)

        v_split = QSplitter(Qt.Vertical)
        v_split.setStyleSheet("QSplitter::handle { background: #333; height: 2px; }")
        v_split.addWidget(daw_widget)
        v_split.addWidget(self.visualizer)
        v_split.setSizes([520, 100])

        right_vbox.addWidget(v_split)
        h_split.addWidget(right)
        h_split.setSizes([240, 1160])

        root.addWidget(h_split, stretch=1)

    # ------------------------------------------------------------------
    # Signal wiring
    # ------------------------------------------------------------------
    def _wire_signals(self):
        self.timeline.seek_requested.connect(self.controller.seek)
        self.timeline.clip_selected.connect(self._on_clip_selected)
        self.transport.audio_loaded.connect(self._on_audio_loaded)
        self.properties.params_changed.connect(self._render_current_frame)

        # Spacebar = play/pause (global shortcut)
        space = QShortcut(QKeySequence(Qt.Key_Space), self)
        space.activated.connect(self.transport.toggle_play_pause)

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------
    def _on_frame(self, current_t: float, universes: dict):
        if universes:
            self.visualizer.update_frame(next(iter(universes.values())))
        self.timeline.update_playhead(current_t)

    def _on_clip_selected(self, clip):
        for track in self.project.tracks:
            for subtrack in track.sub_tracks:
                if clip in subtrack.clips:
                    self.properties.show_clip(clip, subtrack, track)
                    return
        self.properties.show_clip(clip)

    def _render_current_frame(self):
        """Live preview: re-render at current playhead position and push to visualizer."""
        try:
            universes = self.compositor.render_frame(self.controller.playhead_time)
            if universes:
                self.visualizer.update_frame(next(iter(universes.values())))
        except Exception as e:
            logger.warning(f"Live preview error: {e}")

    def _on_audio_loaded(self, path: str):
        """Start background spectrogram analysis when audio is loaded."""
        from pathlib import Path
        self.headers.audio_header.set_filename(Path(path).name)

        # Cancel any previous analysis
        if self._analysis_worker and self._analysis_worker.isRunning():
            self._analysis_worker.terminate()

        self._analysis_worker = AudioAnalysisWorker(path, target_width=2000, target_height=80)
        self._analysis_worker.result.connect(self.timeline.set_audio_image)
        self._analysis_worker.start()
        logger.info(f"Spectrogram analysis started for {Path(path).name}")

    # ------------------------------------------------------------------
    # File menu actions
    # ------------------------------------------------------------------
    def _action_new(self):
        if QMessageBox.question(
            self, "New Project", "Discard current project and start fresh?",
            QMessageBox.Yes | QMessageBox.Cancel,
        ) == QMessageBox.Yes:
            self.controller.stop()
            self._reload_project(*build_demo_project())

    def _action_open(self):
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
        fixtures = [
            PhysicalFixture(seg.fixture_id, universe=1, start_address=1,
                            pixel_count=20, channels_per_pixel=4)
            for seg in project.spatial_map
        ]
        mapper = SpatialMapper(hardware_patch=fixtures, layout=project.spatial_map)
        self._save_path = path
        self._reload_project(project, mapper)

    def _action_save(self):
        if self._save_path:
            self._save_to(self._save_path)
        else:
            self._action_save_as()

    def _action_save_as(self):
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
        self.setWindowTitle(f"Titan Engine v4 — {project.name}")
        self._wire_signals()

    def closeEvent(self, event):
        self.controller.stop()
        self.output_manager.close()
        if self._analysis_worker and self._analysis_worker.isRunning():
            self._analysis_worker.terminate()
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
