import time
import threading
from compositor import CompositorEngine


class PlaybackController:
    """
    The main timeline clock. Runs on a dedicated background thread.
    Calculates time delta, drives the Compositor, and triggers network output.
    """

    def __init__(self, compositor: CompositorEngine, target_fps: int = 60):
        self.compositor = compositor
        self.target_fps = target_fps
        self.frame_duration = 1.0 / target_fps

        self.is_playing = False
        self.playhead_time = 0.0
        self._last_system_time = 0.0

        self._playback_thread = None

    def play(self):
        if not self.is_playing:
            self.is_playing = True
            self._last_system_time = time.perf_counter()
            self._playback_thread = threading.Thread(target=self._render_loop, daemon=True)
            self._playback_thread.start()

    def pause(self):
        self.is_playing = False
        if self._playback_thread:
            self._playback_thread.join()

    def stop(self):
        self.pause()
        self.seek(0.0)

    def seek(self, target_time: float):
        self.playhead_time = max(0.0, target_time)

    def _render_loop(self):
        while self.is_playing:
            loop_start = time.perf_counter()

            # 1. Calculate how much real time passed since the last loop
            current_time = time.perf_counter()
            delta = current_time - self._last_system_time
            self._last_system_time = current_time

            # 2. Advance the playhead
            self.playhead_time += delta

            # 3. Render the frame!
            dmx_packet = self.compositor.render_frame(self.playhead_time)

            # 4. Do something with the frame (Send to network, update UI, etc.)
            self.on_frame_ready(self.playhead_time, dmx_packet)

            # 5. Sleep exactly enough to maintain 60 FPS
            processing_time = time.perf_counter() - loop_start
            sleep_time = max(0.0, self.frame_duration - processing_time)
            time.sleep(sleep_time)

    def on_frame_ready(self, current_t: float, packet: bytearray):
        """
        Callback function. In the real app, this will push to your Art-Net/sACN sender.
        For now, we can override it in our test script.
        """
        pass