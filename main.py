"""
Titan Engine v4 — application entry point.

Pipeline: ProjectModel → SpatialMapper → CompositorEngine
        → OutputManager → PlaybackController → Qt GUI
"""
import sys
import logging
import shutil
from pathlib import Path

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
from playback import PlaybackController, load_audio_any
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

_MEDIA_DIR = Path(__file__).parent / "media"


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
    Background audio analysis: spectrogram, waveform, BPM, and duration.
    Uses load_audio_any so MP3 files are supported.
    """
    spectrogram_ready = Signal(object)   # QImage
    waveform_ready    = Signal(object)   # QImage
    bpm_ready         = Signal(float)
    tempo_map_ready   = Signal(object)   # list[(time_sec, bpm)]
    duration_ready    = Signal(float)    # total audio length in seconds

    def __init__(self, audio_path: str, target_width: int = 4000, target_height: int = 80):
        super().__init__()
        self._path = audio_path
        self._w = target_width
        self._h = target_height

    def run(self):
        try:
            data, sr = load_audio_any(self._path)
            mono = data.mean(axis=1)
        except Exception as e:
            logger.warning(f"Audio analysis: could not load '{self._path}': {e}")
            return
        try:
            duration_secs = len(data) / sr
            self.duration_ready.emit(duration_secs)

            spec_img  = self._spectrogram(mono, sr)
            wave_img  = self._waveform(mono)
            tempo_map = self._build_tempo_map(mono, sr)
            bpm       = tempo_map[0][1] if tempo_map else self._detect_bpm(mono, sr)

            if spec_img:  self.spectrogram_ready.emit(spec_img)
            if wave_img:  self.waveform_ready.emit(wave_img)
            if tempo_map: self.tempo_map_ready.emit(tempo_map)
            if bpm > 0:   self.bpm_ready.emit(bpm)
        except Exception as e:
            logger.warning(f"Audio analysis failed: {e}")

    # ---- spectrogram ------------------------------------------------

    def _spectrogram(self, mono, sr) -> QImage | None:
        n_fft  = 2048
        n_freq = n_fft // 2 + 1
        hop    = max(1, len(mono) // self._w)
        window = np.hanning(n_fft).astype(np.float32)
        spec   = np.zeros((n_freq, self._w), dtype=np.float32)
        for i in range(self._w):
            chunk = mono[i * hop: i * hop + n_fft]
            if len(chunk) < n_fft:
                chunk = np.pad(chunk, (0, n_fft - len(chunk)))
            spec[:, i] = np.abs(np.fft.rfft(chunk * window))

        cutoff = int(n_freq * 0.60)
        spec   = np.log1p(spec[:cutoff, :])
        y_src  = np.linspace(0, cutoff - 1, self._h).astype(int)
        spec   = np.flipud(spec[y_src, :])

        s_min, s_max = spec.min(), spec.max()
        spec = (spec - s_min) / (s_max - s_min) if s_max > s_min else np.zeros_like(spec)

        r = np.clip(spec * 3 - 1.5, 0, 1)
        g = np.clip(spec * 3 - 0.5, 0, 1) * np.clip(2.5 - spec * 3, 0, 1)
        b = np.clip(1.5 - spec * 3, 0, 1) + np.clip(spec * 3 - 2, 0, 1)
        rgb = np.stack([(r * 255).astype(np.uint8),
                        (g * 255).astype(np.uint8),
                        (b * 255).astype(np.uint8)], axis=2)
        h, w = rgb.shape[:2]
        img = QImage(rgb.tobytes(), w, h, w * 3, QImage.Format_RGB888)
        return img.copy()

    # ---- waveform ---------------------------------------------------

    def _waveform(self, mono) -> QImage | None:
        bucket = max(1, len(mono) // self._w)
        n = (len(mono) // bucket) * bucket
        rms = np.sqrt(np.mean(
            mono[:n].reshape(-1, bucket) ** 2, axis=1
        ))
        xs = np.linspace(0, len(rms) - 1, self._w)
        rms = rms[xs.astype(int)]
        peak = rms.max()
        if peak > 0:
            rms /= peak

        img_arr = np.zeros((self._h, self._w, 3), dtype=np.uint8)
        mid = self._h // 2
        for x in range(self._w):
            half = int(rms[x] * mid)
            y0 = max(0, mid - half)
            y1 = min(self._h, mid + half + 1)
            img_arr[y0:y1, x] = [0, 180, 100]

        img = QImage(img_arr.tobytes(), self._w, self._h,
                     self._w * 3, QImage.Format_RGB888)
        return img.copy()

    # ---- BPM detection (autocorrelation on onset envelope) ----------

    def _detect_bpm(self, mono, sr) -> float:
        hop = 512
        n_frames = len(mono) // hop
        if n_frames < 8:
            return 0.0

        env = np.sqrt(np.mean(
            mono[: n_frames * hop].reshape(n_frames, hop) ** 2, axis=1
        ))
        env -= env.mean()

        fps = sr / hop
        min_p = max(1, int(fps * 60 / 200))
        max_p = int(fps * 60 / 60)

        if max_p >= len(env):
            return 0.0

        ac = np.correlate(env, env, mode='full')
        ac = ac[len(ac) // 2:]
        if max_p >= len(ac):
            return 0.0

        peak = np.argmax(ac[min_p: max_p + 1]) + min_p
        return fps * 60.0 / peak if peak > 0 else 0.0

    # ---- variable tempo map -----------------------------------------

    def _build_tempo_map(self, mono, sr) -> list:
        win_sec = 4.0
        hop_sec = 2.0
        win_n   = int(win_sec * sr)
        hop_n   = int(hop_sec * sr)

        raw = []
        i = 0
        t = 0.0
        while i + win_n <= len(mono):
            bpm = self._detect_bpm(mono[i: i + win_n], sr)
            if bpm > 0:
                raw.append((t + win_sec / 2.0, bpm))
            i += hop_n
            t += hop_sec

        if not raw:
            return []

        merged = [(0.0, raw[0][1])]
        for time_sec, bpm in raw[1:]:
            if abs(bpm - merged[-1][1]) / merged[-1][1] > 0.02:
                merged.append((time_sec, bpm))

        return merged


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
        self._selected_clip = None

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

        act("New Project",     "Ctrl+N",        self._action_new)
        act("Open Project…",   "Ctrl+O",        self._action_open)
        act("Save Project",    "Ctrl+S",        self._action_save)
        act("Save Project As…","Ctrl+Shift+S",  self._action_save_as)
        file_menu.addSeparator()
        act("Open Audio…",     slot=lambda: self.transport.btn_open_audio.click())

    # ------------------------------------------------------------------
    # UI layout
    # ------------------------------------------------------------------
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.transport = TransportBar(self.controller)
        root.addWidget(self.transport)

        h_split = QSplitter(Qt.Horizontal)
        h_split.setStyleSheet("QSplitter::handle { background: #333; width: 2px; }")

        self.properties = PropertiesPanel()
        self.properties.setMinimumWidth(200)
        self.properties.setMaximumWidth(320)
        h_split.addWidget(self.properties)

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
    # Signal wiring  (called once from __init__ only)
    # ------------------------------------------------------------------
    def _wire_signals(self):
        self.timeline.seek_requested.connect(self.controller.seek)
        self.timeline.seek_requested.connect(self.timeline.update_playhead)
        self.timeline.seek_requested.connect(self._render_current_frame)
        self.timeline.clip_selected.connect(self._on_clip_selected)
        self.timeline.project_changed.connect(self._on_project_changed)
        self.transport.audio_loaded.connect(self._on_audio_loaded)
        self.properties.params_changed.connect(self._render_current_frame)
        self.properties.clip_layout_changed.connect(self.timeline.refresh)
        self.properties.clip_layout_changed.connect(self._render_current_frame)
        self.headers.audio_header.view_mode_changed.connect(self.timeline.set_audio_view_mode)
        self.headers.audio_header.bpm_grid_toggled.connect(self.timeline.set_bpm_grid_visible)

        # Global shortcuts (work regardless of which widget has focus)
        for key, slot in [
            (Qt.Key_Space, self.transport.toggle_play_pause),
            (Qt.Key_J,     self.controller.pause),
            (Qt.Key_K,     self.controller.stop),
            (Qt.Key_L,     self.controller.play),
            (Qt.Key_V,     lambda: self.timeline.set_tool("select")),
            (Qt.Key_B,     lambda: self.timeline.set_tool("blade")),
            (Qt.Key_M,     lambda: self.timeline.add_marker(self.controller.playhead_time)),
        ]:
            s = QShortcut(QKeySequence(key), self)
            s.activated.connect(slot)

    def _reconnect_controller(self):
        """Reconnect seek_requested to the new self.controller after a project reload."""
        try:
            self.timeline.seek_requested.disconnect()
        except RuntimeError:
            pass
        self.timeline.seek_requested.connect(self.controller.seek)
        self.timeline.seek_requested.connect(self.timeline.update_playhead)
        self.timeline.seek_requested.connect(self._render_current_frame)

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------
    def _on_frame(self, current_t: float, universes: dict):
        if universes:
            self.visualizer.update_frame(next(iter(universes.values())))
        self.timeline.update_playhead(current_t)

    def _on_clip_selected(self, clip):
        self._selected_clip = clip
        for track in self.project.tracks:
            for subtrack in track.sub_tracks:
                if clip in subtrack.clips:
                    self.properties.show_clip(clip, subtrack, track)
                    return
        self.properties.show_clip(clip)

    def _render_current_frame(self, *_):
        """
        Re-render at the current playhead position and push to the visualizer.
        Falls back to the selected clip's midpoint when playhead is outside the clip.
        """
        t = self.controller.playhead_time
        if self._selected_clip is not None:
            c = self._selected_clip
            if not (c.start <= t <= c.start + c.duration):
                t = c.start + c.duration * 0.5
        try:
            universes = self.compositor.render_frame(t)
            if universes:
                self.visualizer.update_frame(next(iter(universes.values())))
        except Exception as e:
            logger.warning(f"Live preview error: {e}")

    def _on_audio_loaded(self, path: str):
        """
        Handle audio file selection:
        1. Copy file into media/ for project portability
        2. Load into playback controller
        3. Save path in project model
        4. Start background analysis (spectrogram, waveform, BPM, duration)
        """
        src = Path(path)
        _MEDIA_DIR.mkdir(exist_ok=True)
        dest = _MEDIA_DIR / src.name

        # Copy if not already in media/
        try:
            if src.resolve() != dest.resolve():
                shutil.copy2(src, dest)
            dest_str = str(dest)
        except Exception as e:
            logger.warning(f"Could not copy audio to media/: {e}")
            dest_str = path   # fall back to original path

        # Load into playback controller
        was_playing = self.controller.is_playing
        if was_playing:
            self.controller.pause()
        ok = self.controller.load_audio(dest_str)
        self.transport.set_audio_state(src.name, ok)
        if was_playing and ok:
            self.controller.play()

        if not ok:
            return

        # Persist in project
        self.project.audio.file_path = dest_str

        # Update header label
        self.headers.audio_header.set_filename(src.name)

        # Stop any running analysis worker gracefully
        self._stop_analysis_worker()

        # Start fresh analysis
        self._analysis_worker = AudioAnalysisWorker(dest_str, target_width=4000, target_height=80)
        self._analysis_worker.spectrogram_ready.connect(self.timeline.set_spectrogram_image)
        self._analysis_worker.waveform_ready.connect(self.timeline.set_waveform_image)
        self._analysis_worker.bpm_ready.connect(self._on_bpm_detected)
        self._analysis_worker.tempo_map_ready.connect(self.timeline.set_tempo_map)
        self._analysis_worker.duration_ready.connect(self._on_audio_duration)
        self._analysis_worker.start()
        logger.info(f"Audio analysis started for {src.name}")

    def _on_audio_duration(self, seconds: float):
        self.timeline.set_scene_duration(seconds)
        logger.info(f"Audio duration: {seconds:.1f}s — timeline extended")

    def _on_bpm_detected(self, bpm: float):
        bpm_rounded = round(bpm, 1)
        self.headers.audio_header.set_bpm(bpm_rounded)
        self.timeline.set_bpm(bpm_rounded)
        logger.info(f"BPM detected: {bpm_rounded}")

    def _on_project_changed(self):
        """Rebuild track header panel when tracks are added or removed."""
        old_headers = self.headers
        self.headers = TrackHeaderPanel(self.project)
        layout = old_headers.parentWidget().layout()
        layout.replaceWidget(old_headers, self.headers)
        old_headers.deleteLater()
        self.headers.audio_header.view_mode_changed.connect(self.timeline.set_audio_view_mode)
        self.headers.audio_header.bpm_grid_toggled.connect(self.timeline.set_bpm_grid_visible)

    def _stop_analysis_worker(self):
        """Gracefully stop any running analysis worker."""
        if not self._analysis_worker:
            return
        if self._analysis_worker.isRunning():
            self._analysis_worker.quit()
            if not self._analysis_worker.wait(2000):
                self._analysis_worker.terminate()
                self._analysis_worker.wait(500)
        self._analysis_worker = None

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

        # Auto-load saved audio if still accessible
        audio_path = project.audio.file_path
        if audio_path and Path(audio_path).exists():
            self._on_audio_loaded(audio_path)
        elif audio_path:
            logger.warning(f"Saved audio not found: {audio_path}")

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
        """Replace the active project without re-running full _wire_signals()."""
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
        # Reconnect only the signals that reference self.controller
        self._reconnect_controller()

    def closeEvent(self, event):
        self.controller.stop()
        self.output_manager.close()
        self._stop_analysis_worker()
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
