import time
import threading
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

try:
    import sounddevice as sd
    import soundfile as sf
    _AUDIO_AVAILABLE = True
except ImportError:
    _AUDIO_AVAILABLE = False
    logger.warning("sounddevice/soundfile not installed — audio playback disabled, perf_counter clock active")


def load_audio_any(path: str):
    """
    Load audio from any supported format. Returns (float32_array, sample_rate).
    Tries soundfile first (WAV/FLAC/OGG/AIFF), falls back to pydub for MP3/AAC.
    Raises RuntimeError if both fail.
    """
    import numpy as np
    try:
        import soundfile as _sf
        data, sr = _sf.read(path, dtype='float32', always_2d=True)
        return data, sr
    except Exception as sf_err:
        pass

    try:
        from pydub import AudioSegment
        seg = AudioSegment.from_file(path)
        sr = seg.frame_rate
        raw = np.array(seg.get_array_of_samples(), dtype=np.float32)
        if seg.sample_width == 2:
            raw /= 32768.0
        elif seg.sample_width == 4:
            raw /= 2147483648.0
        channels = seg.channels
        data = raw.reshape(-1, channels) if channels > 1 else raw.reshape(-1, 1)
        return data, sr
    except ImportError:
        raise RuntimeError(
            f"MP3 / AAC support requires pydub + ffmpeg. "
            f"Install with: pip install pydub  (and brew install ffmpeg)"
        )
    except Exception as pd_err:
        raise RuntimeError(f"Audio load failed: {pd_err}")


class PlaybackController:
    """
    Timeline clock and render driver.

    Without audio: advances playhead via time.perf_counter.
    With audio loaded: the sounddevice stream callback drives the clock from
    the hardware sample position for sample-accurate sync.
    """

    def __init__(self, compositor, output_manager=None, target_fps: int = 44):
        self.compositor = compositor
        self.output_manager = output_manager
        self.target_fps = target_fps
        self.frame_duration = 1.0 / target_fps

        self.is_playing = False
        self.playhead_time: float = 0.0

        # Audio state
        self._audio_data = None
        self._audio_sr: int = 44100
        self._audio_path: str | None = None
        self._audio_pos: int = 0          # current sample index
        self._audio_lock = threading.Lock()
        self._stream = None               # sd.OutputStream or None

        self._stop_event = threading.Event()
        self._render_thread: threading.Thread | None = None

    # ------------------------------------------------------------------
    # Audio loading
    # ------------------------------------------------------------------

    def load_audio(self, path: str) -> bool:
        """Load any supported audio file (WAV/FLAC/OGG/MP3). Returns True on success."""
        if not _AUDIO_AVAILABLE:
            logger.warning("Cannot load audio: sounddevice not installed.")
            return False
        try:
            data, sr = load_audio_any(path)
            with self._audio_lock:
                self._audio_data = data
                self._audio_sr = sr
                self._audio_path = path
            logger.info(f"Audio loaded: {Path(path).name} ({sr} Hz, {len(data)/sr:.1f}s, {data.shape[1]}ch)")
            return True
        except Exception as e:
            logger.warning(f"Audio load failed '{path}': {e}")
            return False

    # ------------------------------------------------------------------
    # Transport
    # ------------------------------------------------------------------

    def play(self):
        if self.is_playing:
            return
        self.is_playing = True
        self._stop_event.clear()
        if _AUDIO_AVAILABLE and self._audio_data is not None:
            self._start_audio_stream()
        self._render_thread = threading.Thread(target=self._render_loop, daemon=True)
        self._render_thread.start()

    def pause(self):
        if not self.is_playing:
            return
        self.is_playing = False
        self._stop_event.set()
        self._stop_audio_stream()
        if self._render_thread:
            self._render_thread.join(timeout=1.0)

    def stop(self):
        self.pause()
        self.seek(0.0)

    def seek(self, t: float):
        self.playhead_time = max(0.0, t)
        with self._audio_lock:
            if self._audio_data is not None:
                self._audio_pos = int(t * self._audio_sr)

    # ------------------------------------------------------------------
    # Audio stream
    # ------------------------------------------------------------------

    def _start_audio_stream(self):
        def _callback(outdata, frames, time_info, status):
            with self._audio_lock:
                if self._audio_data is None:
                    outdata[:] = 0
                    return
                start = self._audio_pos
                end = start + frames
                chunk = self._audio_data[start:end]
                got = len(chunk)
                if got < frames:
                    outdata[:got] = chunk
                    outdata[got:] = 0
                else:
                    outdata[:] = chunk
                self._audio_pos = end
                # Drive playhead from the hardware sample clock
                self.playhead_time = self._audio_pos / self._audio_sr

        try:
            channels = self._audio_data.shape[1]
            self._stream = sd.OutputStream(
                samplerate=self._audio_sr,
                channels=channels,
                dtype='float32',
                callback=_callback,
                blocksize=512,
            )
            self._stream.start()
        except Exception as e:
            logger.warning(f"Audio stream failed to open: {e}")
            self._stream = None

    def _stop_audio_stream(self):
        if self._stream:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None

    # ------------------------------------------------------------------
    # Render loop
    # ------------------------------------------------------------------

    def _render_loop(self):
        last_t = time.perf_counter()
        while not self._stop_event.is_set():
            loop_start = time.perf_counter()

            # If no audio stream, advance clock manually
            if self._stream is None:
                now = time.perf_counter()
                self.playhead_time += now - last_t
                last_t = now

            universes = self.compositor.render_frame(self.playhead_time)

            if self.output_manager:
                self.output_manager.send(universes)

            self.on_frame_ready(self.playhead_time, universes)

            elapsed = time.perf_counter() - loop_start
            sleep_for = max(0.0, self.frame_duration - elapsed)
            if sleep_for > 0:
                time.sleep(sleep_for)

    def on_frame_ready(self, current_t: float, universes: dict):
        """Override or assign to receive rendered frames on the render thread."""
        pass
