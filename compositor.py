import numpy as np
from models.project import Project, resolve_params
from spatial import SpatialMapper


def evaluate_envelope(t: float, duration: float, atk, dec, sus, rel) -> float:
    """ADSR amplitude multiplier (0.0–1.0) for a moment in time."""
    atk = atk or 0.0
    dec = dec or 0.0
    sus = sus if sus is not None else 1.0
    rel = rel or 0.0

    if t < 0:
        return 0.0
    if t < atk:
        return t / atk if atk > 0 else 1.0
    if t < atk + dec:
        return 1.0 - (1.0 - sus) * ((t - atk) / dec) if dec > 0 else sus
    if t < duration:
        return sus
    if t < duration + rel:
        return sus * (1.0 - (t - duration) / rel) if rel > 0 else 0.0
    return 0.0


class CompositorEngine:
    def __init__(self, project: Project, mapper: SpatialMapper):
        self.project = project
        self.mapper = mapper
        self.num_leds = len(mapper._pixel_map)

        # Pre-bake numpy arrays from the pixel map (built once, read every frame)
        self._led_xs = np.array([p["x"] for p in mapper._pixel_map], dtype=np.float32)
        self._led_addrs = np.array([p["address"] for p in mapper._pixel_map], dtype=np.int32)
        self._led_channels = np.array([p["channels"] for p in mapper._pixel_map], dtype=np.int32)
        self._led_universes = np.array([p["universe"] for p in mapper._pixel_map], dtype=np.int32)

    def render_frame(self, playhead_time: float) -> dict:
        """
        Render one frame. Returns {universe_int: bytearray(512)}.
        All inner loops are numpy-vectorized — no per-LED Python iteration.
        """
        master_buffer = np.zeros((self.num_leds, 4), dtype=np.float32)

        for track in self.project.tracks:
            track_buffer = np.zeros((self.num_leds, 4), dtype=np.float32)

            for subtrack in track.sub_tracks:
                for clip in subtrack.clips:
                    params = resolve_params(clip, subtrack, track)
                    max_rel = max(params.rel_c or 0.0, params.rel_e or 0.0)

                    if not (clip.start <= playhead_time < clip.start + clip.duration + max_rel):
                        continue

                    color = np.array([
                        params.r or 0.0, params.g or 0.0,
                        params.b or 0.0, params.w or 0.0,
                    ], dtype=np.float32) * (params.dim or 1.0)

                    t_clip = playhead_time - clip.start
                    env_c = evaluate_envelope(t_clip, clip.duration,
                                              params.atk_c, params.dec_c,
                                              params.sus_c, params.rel_c)
                    env_e = evaluate_envelope(t_clip, clip.duration,
                                              params.atk_e, params.dec_e,
                                              params.sus_e, params.rel_e)

                    for v_pixel in clip.pixels:
                        width = params.effect_width or v_pixel.width
                        half_width = width / 2.0

                        # Vectorized range query — no Python loop over LEDs
                        mask = ((self._led_xs >= v_pixel.x - half_width) &
                                (self._led_xs <= v_pixel.x + half_width))
                        indices = np.where(mask)[0]
                        if len(indices) == 0:
                            continue

                        # Distance from center → per-LED envelope blend
                        if half_width > 0:
                            dists = np.clip(
                                np.abs(self._led_xs[indices] - v_pixel.x) / half_width,
                                0.0, 1.0
                            ).astype(np.float32)
                        else:
                            dists = np.zeros(len(indices), dtype=np.float32)

                        # (N,1) envs broadcast against (1,4) color → (N,4) contribution
                        envs = (env_c * (1.0 - dists) + env_e * dists)[:, np.newaxis]
                        track_buffer[indices] += color[np.newaxis, :] * envs

            # Apply opacity and blend into master
            track_buffer *= track.opacity
            if track.blending_mode == "Overwrite":
                active = np.any(track_buffer > 0, axis=1)
                master_buffer[active] = track_buffer[active]
            elif track.blending_mode == "Multiply":
                # Only darken pixels where this track has content; 0 = no effect
                active = np.any(track_buffer > 0, axis=1)
                if active.any():
                    master_buffer[active] = master_buffer[active] * np.clip(
                        track_buffer[active] / 255.0, 0.0, 1.0
                    )
            else:  # Add (default)
                master_buffer += track_buffer

        final = np.clip(master_buffer, 0, 255).astype(np.uint8)

        # Assemble per-universe 512-byte DMX packets (vectorized per-channel write)
        universes = np.unique(self._led_universes)
        packets = {int(u): bytearray(512) for u in universes}

        for u in universes:
            u_int = int(u)
            u_mask = self._led_universes == u
            led_idx = np.where(u_mask)[0]
            addrs = self._led_addrs[led_idx] - 1    # DMX is 1-indexed
            channels = self._led_channels[led_idx]
            colors = final[led_idx]                  # shape (N, 4)

            buf = np.frombuffer(packets[u_int], dtype=np.uint8).copy()
            for ch in range(4):
                ch_mask = channels > ch
                if ch_mask.any():
                    buf[addrs[ch_mask] + ch] = colors[ch_mask, ch]
            packets[u_int] = bytearray(buf)

        return packets
