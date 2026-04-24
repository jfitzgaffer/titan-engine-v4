from typing import List, Tuple, Dict
from models.project import SpatialSegment


class PhysicalFixture:
    """Represents the actual hardware patch of a real-world light."""

    def __init__(self, fixture_id: str, universe: int, start_address: int, pixel_count: int,
                 channels_per_pixel: int = 3):
        self.fixture_id = fixture_id
        self.universe = universe
        self.start_address = start_address
        self.pixel_count = pixel_count
        self.channels_per_pixel = channels_per_pixel


class SpatialMapper:
    """
    The Bridge: Maps virtual 1D coordinates (0.0 to 1.0)
    to physical DMX universe and address coordinates.
    """

    def __init__(self, hardware_patch: List[PhysicalFixture], layout: List[SpatialSegment]):
        self.hardware: Dict[str, PhysicalFixture] = {f.fixture_id: f for f in hardware_patch}
        self.layout: List[SpatialSegment] = layout

        # Pre-compute a lookup table so we aren't doing heavy math on every single frame
        self._pixel_map = self._build_lookup_table()

    def _build_lookup_table(self) -> List[dict]:
        """
        Creates a map of abstract X-coordinates to physical DMX channels.
        This runs ONLY ONCE when the project loads.
        """
        mapping = []

        for segment in self.layout:
            fixture = self.hardware.get(segment.fixture_id)
            if not fixture:
                continue

            # Calculate the physical width of this fixture in the virtual space
            segment_width = segment.x_end - segment.x_start
            step_size = segment_width / fixture.pixel_count

            for i in range(fixture.pixel_count):
                # Calculate the 1D physical location of this specific LED
                if segment.flip:
                    virtual_x = segment.x_end - (i * step_size) - (step_size / 2)
                else:
                    virtual_x = segment.x_start + (i * step_size) + (step_size / 2)

                # Calculate the exact DMX start channel for this LED
                addr = fixture.start_address + (i * fixture.channels_per_pixel)

                mapping.append({
                    "x": virtual_x,
                    "universe": fixture.universe,
                    "address": addr,
                    "channels": fixture.channels_per_pixel
                })

        # Sort left-to-right to make searching faster later
        return sorted(mapping, key=lambda m: m["x"])

    def get_physical_pixels_in_range(self, x_center: float, width: float) -> List[dict]:
        """
        The Compositor calls this. "Give me all real LEDs within this virtual bounding box."
        """
        half_width = width / 2.0
        min_x = x_center - half_width
        max_x = x_center + half_width

        # Return all DMX addresses that fall inside this virtual clip's width
        return [p for p in self._pixel_map if min_x <= p["x"] <= max_x]