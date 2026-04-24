import sys
from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout
from PySide6.QtCore import Signal

from models.project import Project, Track, SubTrack, Clip, ParameterSet, VirtualPixel, SpatialSegment
from spatial import PhysicalFixture, SpatialMapper
from compositor import CompositorEngine
from playback import PlaybackController
from widgets.visualizer import VisualizerWidget
from widgets.timeline import TimelineWidget


class MainAppWindow(QWidget):
    # This Signal is our thread-safe bridge!
    frame_received = Signal(float, bytearray)

    def __init__(self, project, mapper, compositor):
        super().__init__()
        self.setWindowTitle("Titan Engine V4 - DAW Mode")

        # Make the window much smaller and sleeker
        self.resize(800, 250)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        self.timeline = TimelineWidget(project)
        layout.addWidget(self.timeline, stretch=2)

        self.visualizer = VisualizerWidget(mapper)
        layout.addWidget(self.visualizer, stretch=1)

        # Connect our safe signal to the UI update function
        self.frame_received.connect(self.process_frame_ui)

        self.player = PlaybackController(compositor, target_fps=60)

        # The background thread EMITS the signal, instead of touching the UI directly
        self.player.on_frame_ready = lambda t, p: self.frame_received.emit(t, p)

        self.player.play()

    def process_frame_ui(self, current_t, packet):
        # Because this is triggered by a Signal, it safely runs on the main UI thread
        self.visualizer.update_frame(packet)
        self.timeline.update_playhead(current_t)

        # Loop the playhead
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