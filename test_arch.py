"""
Integration test / dev harness.

python test_arch.py          — run unit tests (headless)
python test_arch.py --gui    — open the Qt window for visual verification
"""
import sys
import unittest

from models.project import (
    Project, Track, SubTrack, Clip, ParameterSet, VirtualPixel, SpatialSegment,
)
from spatial import PhysicalFixture, SpatialMapper
from compositor import CompositorEngine


# ------------------------------------------------------------------
# Shared test fixture factory
# ------------------------------------------------------------------
def _build_test_stack():
    fixture = PhysicalFixture(
        fixture_id="BAR_1", universe=1, start_address=1,
        pixel_count=10, channels_per_pixel=4,
    )
    segment = SpatialSegment(fixture_id="BAR_1", x_start=0.0, x_end=1.0)
    mapper = SpatialMapper(hardware_patch=[fixture], layout=[segment])

    clip = Clip(
        start=1.0,
        duration=3.0,
        params=ParameterSet(dim=1.0, b=255.0, atk_c=1.0, atk_e=1.0, rel_c=1.0, rel_e=1.0),
        pixels=[VirtualPixel(x=0.5, width=0.2)],
    )
    subtrack = SubTrack(params=ParameterSet(g=128.0), clips=[clip])
    track = Track(params=ParameterSet(dim=1.0, r=255.0), sub_tracks=[subtrack])
    project = Project(tracks=[track])
    compositor = CompositorEngine(project, mapper)
    return project, mapper, compositor


# ------------------------------------------------------------------
# Unit tests
# ------------------------------------------------------------------
class TestCompositor(unittest.TestCase):

    def setUp(self):
        _, _, self.compositor = _build_test_stack()

    def test_render_returns_dict(self):
        result = self.compositor.render_frame(0.0)
        self.assertIsInstance(result, dict)

    def test_packet_length_512(self):
        result = self.compositor.render_frame(1.5)
        for u, packet in result.items():
            self.assertIsInstance(packet, bytearray)
            self.assertEqual(len(packet), 512, f"Universe {u} packet must be 512 bytes")

    def test_dark_before_clip(self):
        result = self.compositor.render_frame(0.4)
        for packet in result.values():
            self.assertEqual(max(packet), 0, "Should be dark before clip starts")

    def test_lit_during_clip(self):
        result = self.compositor.render_frame(2.5)
        for packet in result.values():
            self.assertGreater(max(packet), 0, "Should be lit during clip playback")

    def test_dark_after_release(self):
        result = self.compositor.render_frame(10.0)
        for packet in result.values():
            self.assertEqual(max(packet), 0, "Should be dark after release tail ends")


class TestCascade(unittest.TestCase):

    def _make_stack(self, track_params, sub_params, clip_params):
        fixture = PhysicalFixture("F1", universe=1, start_address=1, pixel_count=4, channels_per_pixel=4)
        segment = SpatialSegment(fixture_id="F1", x_start=0.0, x_end=1.0)
        mapper = SpatialMapper([fixture], [segment])
        clip = Clip(start=0.0, duration=5.0, params=clip_params,
                    pixels=[VirtualPixel(x=0.5, width=1.0)])
        subtrack = SubTrack(params=sub_params, clips=[clip])
        track = Track(params=track_params, sub_tracks=[subtrack])
        project = Project(tracks=[track])
        return CompositorEngine(project, mapper)

    def test_clip_overrides_track(self):
        compositor = self._make_stack(
            track_params=ParameterSet(dim=1.0, r=100.0),
            sub_params=ParameterSet(),
            clip_params=ParameterSet(r=200.0),   # clip wins
        )
        result = compositor.render_frame(2.5)
        packet = list(result.values())[0]
        self.assertGreater(packet[0], 100, "Clip-level r=200 should dominate track-level r=100")

    def test_none_inherits_from_track(self):
        compositor = self._make_stack(
            track_params=ParameterSet(dim=1.0, r=180.0),
            sub_params=ParameterSet(),
            clip_params=ParameterSet(),   # r=None → inherits r=180 from track
        )
        result = compositor.render_frame(2.5)
        packet = list(result.values())[0]
        self.assertGreater(packet[0], 0, "Inherited r=180 should produce light")


class TestSerialization(unittest.TestCase):

    def test_round_trip(self):
        import tempfile, os
        project = Project(tracks=[
            Track(name="Test", params=ParameterSet(dim=1.0, r=200.0))
        ])
        with tempfile.NamedTemporaryFile(suffix=".titanproj", delete=False) as f:
            path = f.name
        try:
            project.save_to_file(path)
            loaded = Project.load_from_file(path)
            self.assertEqual(loaded.tracks[0].name, "Test")
            self.assertEqual(loaded.tracks[0].params.r, 200.0)
            self.assertEqual(loaded.version, 4)
        finally:
            os.unlink(path)


# ------------------------------------------------------------------
# GUI test harness (python test_arch.py --gui)
# ------------------------------------------------------------------
def run_gui():
    from PySide6.QtWidgets import QApplication
    from main import MainWindow, build_demo_project

    app = QApplication(sys.argv)
    project, mapper = build_demo_project()
    window = MainWindow(project, mapper)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    if "--gui" in sys.argv:
        run_gui()
    else:
        unittest.main(verbosity=2, argv=[sys.argv[0]])
