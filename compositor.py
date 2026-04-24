import numpy as np
from models.project import Project, resolve_params
from spatial import SpatialMapper


def evaluate_envelope(t: float, duration: float, atk: float, dec: float, sus: float, rel: float) -> float:
    """
    Calculates the exact amplitude multiplier (0.0 to 1.0) for a given moment in time.
    """
    # Safe defaults
    atk = atk or 0.0
    dec = dec or 0.0
    sus = sus if sus is not None else 1.0
    rel = rel or 0.0

    if t < 0:
        return 0.0
    if t < atk:  # Attack phase (fading in)
        return t / atk if atk > 0 else 1.0
    elif t < atk + dec:  # Decay phase (dropping to sustain level)
        return 1.0 - (1.0 - sus) * ((t - atk) / dec) if dec > 0 else sus
    elif t < duration:  # Sustain phase (holding steady)
        return sus
    elif t < duration + rel:  # Release phase (fading out after clip ends)
        return sus * (1.0 - ((t - duration) / rel)) if rel > 0 else 0.0
    else:
        return 0.0


class CompositorEngine:
    def __init__(self, project: Project, mapper: SpatialMapper):
        self.project = project
        self.mapper = mapper
        self.num_leds = len(self.mapper._pixel_map)
        self.led_to_dmx = {i: p for i, p in enumerate(self.mapper._pixel_map)}

    def render_frame(self, playhead_time: float) -> bytearray:
        master_buffer = np.zeros((self.num_leds, 4), dtype=np.float32)

        for track in self.project.tracks:
            track_buffer = np.zeros((self.num_leds, 4), dtype=np.float32)

            for subtrack in track.sub_tracks:
                for clip in subtrack.clips:
                    params = resolve_params(clip, subtrack, track)

                    # Calculate the maximum release tail so the clip stays active while fading out
                    max_rel = max(params.rel_c or 0.0, params.rel_e or 0.0)

                    if clip.start <= playhead_time < (clip.start + clip.duration + max_rel):

                        target_color = np.array([
                            params.r or 0, params.g or 0, params.b or 0, params.w or 0
                        ], dtype=np.float32) * (params.dim or 1.0)

                        # Time relative to the start of this specific clip
                        t_clip = playhead_time - clip.start

                        # Calculate the temporal envelope for the center AND the edge
                        env_c = evaluate_envelope(t_clip, clip.duration, params.atk_c, params.dec_c, params.sus_c,
                                                  params.rel_c)
                        env_e = evaluate_envelope(t_clip, clip.duration, params.atk_e, params.dec_e, params.sus_e,
                                                  params.rel_e)

                        for v_pixel in clip.pixels:
                            width = params.effect_width or v_pixel.width
                            physical_leds = self.mapper.get_physical_pixels_in_range(v_pixel.x, width)

                            for led in physical_leds:
                                idx = next(i for i, p in self.led_to_dmx.items() if p["address"] == led["address"])

                                # Calculate spatial distance from the center (0.0 = center, 1.0 = absolute edge)
                                half_width = width / 2.0
                                dist = min(1.0, abs(led["x"] - v_pixel.x) / half_width) if half_width > 0 else 0.0

                                # Crossfade between the center and edge envelopes based on distance
                                final_env = (env_c * (1.0 - dist)) + (env_e * dist)

                                track_buffer[idx] += target_color * final_env

            # Composite and Blend
            track_buffer *= track.opacity
            if track.blending_mode == "Overwrite":
                mask = np.any(track_buffer > 0, axis=1)
                master_buffer[mask] = track_buffer[mask]
            elif track.blending_mode == "Multiply":
                master_buffer = (master_buffer * track_buffer) / 255.0
            else:
                master_buffer += track_buffer

        master_buffer = np.clip(master_buffer, 0, 255).astype(np.uint8)
        dmx_packet = bytearray(512)
        for idx, color_data in enumerate(master_buffer):
            dmx_info = self.led_to_dmx[idx]
            addr = dmx_info["address"] - 1
            dmx_packet[addr:addr + 4] = bytes(color_data)

        return dmx_packet