import sys
from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout, QHBoxLayout
from PySide6.QtCore import Signal

from models.project import Project, Track, SubTrack, Clip, ParameterSet, VirtualPixel, SpatialSegment
from spatial import PhysicalFixture, SpatialMapper
from compositor import CompositorEngine
from playback import PlaybackController
from widgets.visualizer import VisualizerWidget
from widgets.timeline import TimelineWidget
from widgets.track_header import TrackHeaderPanel


class MainAppWindow(QWidget):
    frame_received = Signal(float, bytearray)

    def __init__(self, project, mapper, compositor):
        super().__init__()
        self.setWindowTitle("Titan Engine V4 - DAW Mode")
        self.resize(1000, 300)  # Made the window slightly wider to fit the left panel

        # The main vertical layout
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(2)

        # --- TOP SECTION: DAW SPLIT VIEW ---
        daw_layout = QHBoxLayout()
        daw_layout.setContentsMargins(0, 0, 0, 0)
        daw_layout.setSpacing(0)

        # Left Side: Track Headers
        self.headers = TrackHeaderPanel(project)
        daw_layout.addWidget(self.headers)

        # Right Side: Timeline
        self.timeline = TimelineWidget(project)
        daw_layout.addWidget(self.timeline)

        # Add the horizontal split to the main vertical layout
        main_layout.addLayout(daw_layout, stretch=2)

        # --- BOTTOM SECTION: VISUALIZER ---
        self.visualizer = VisualizerWidget(mapper)
        main_layout.addWidget(self.visualizer, stretch=1)

        self.frame_received.connect(self.process_frame_ui)

        self.player = PlaybackController(compositor, target_fps=60)
        self.player.on_frame_ready = lambda t, p: self.frame_received.emit(t, p)
        self.player.play()

    def process_frame_ui(self, current_t, packet):
        self.visualizer.update_frame(packet)
        self.timeline.update_playhead(current_t)

        if current_t > 6.0:
            self.player.seek(0.0)


def run_tests():
    app = QApplication(sys.argv)

    fixture = PhysicalFixture(fixture_id="BAR_1", universe=1, start_address=1, pixel_count=10, channels_per_pixel=4)
    segment = SpatialSegment(fixture_id="BAR_1", x_start=0.0, x_end=1.0)
    mapper = SpatialMapper(hardware_patch=[fixture], layout=[segment])

    clip = Clip(
        start=1.0,
        duration=3.0,
        params=ParameterSet(dim=1.0, b=255, atk_c=1.0, atk_e=1.0, rel_c=1.0, rel_e=1.0),
        pixels=[VirtualPixel(x=0.5, width=0.2)]
    )
    subtrack = SubTrack(params=ParameterSet(g=128), clips=[clip])
    track = Track(params=ParameterSet(dim=1.0, r=255), sub_tracks=[subtrack])
    project = Project(tracks=[track])

    compositor = CompositorEngine(project, mapper)

    window = MainAppWindow(project, mapper, compositor)
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    run_tests()