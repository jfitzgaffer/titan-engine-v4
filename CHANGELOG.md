# Changelog

## [2026-04-24] - Core pipeline vectorization, DMX output, audio clock, transport UI, main entry point

### Added
- `output/output_manager.py` — queue-based DMX sender with spec-exact Art-Net and sACN packet builders ported from v3; non-blocking `send()` drops oldest frame when sender thread falls behind; handles broadcast/unicast/multicast routing; QLC+ `artnet_offset` compatibility preserved
- `output/__init__.py` — output package marker
- `playback.py` — `load_audio(path)` method using `soundfile`; `sounddevice` output stream callback drives `playhead_time` from the hardware sample clock for sample-accurate sync; graceful fallback to `time.perf_counter` when no audio file is loaded; `output_manager` parameter wires render loop directly to DMX sender
- `widgets/constants.py` — single source of truth for `TRACK_HEIGHT`, `RULER_HEIGHT`, `PIXELS_PER_SECOND`; both `timeline.py` and `track_header.py` now import from here
- `widgets/transport.py` — `TransportBar` widget: Play/Pause/Stop buttons + live `M:SS.mmm` clock display updating at 30 Hz via `QTimer`
- `main.py` — proper application entry point; builds a two-track demo project; wires `CompositorEngine → OutputManager → PlaybackController`; uses a `FrameBridge(QObject)` with a Qt signal as the thread-safe handoff from the render thread to the GUI thread; `MainWindow` with transport bar, DAW split view (headers + timeline), and LED visualizer in a `QSplitter`

### Changed
- `compositor.py` — **fully vectorized**: inner LED loop replaced with numpy boolean range queries + broadcast multiply; pre-baked `_led_xs`, `_led_addrs`, `_led_channels`, `_led_universes` numpy arrays built once in `__init__`; `render_frame()` now returns `dict[int, bytearray]` (one 512-byte packet per universe) instead of a flat `bytearray`; DMX packet assembly uses numpy channel-wise write, no per-LED Python loop
- `models/project.py` — `OutputConfig` expanded with `art_net`, `art_sub`, `artnet_offset`, `sacn_priority`, `sacn_source_name`, `sacn_preview`, `active` fields; `Project` gains `version: int = 4` field; `SpatialSegment.fixture_id` given default `""` so `load_from_file` never raises on partial data
- `widgets/timeline.py` — imports constants from `widgets/constants.py`; `ClipItem` now locks Y-axis during drag (was a bug: clips could be dragged off their track lane); clip duration label painted inside each clip; alternating track lane shading; `SCENE_WIDTH` increased to 5000 px; `QScrollBar` always visible on horizontal axis; `refresh()` method for programmatic rebuild
- `widgets/track_header.py` — imports constants from `widgets/constants.py`; opacity slider shows live `%` readout; alternating row background shading matches timeline; `QSlider` styled with neon green handle
- `test_arch.py` — rewritten as a proper `unittest` suite (`TestCompositor`, `TestCascade`, `TestSerialization`); tests `render_frame()` dict return type, 512-byte packet length, dark/lit/dark clip lifecycle, cascade priority, `None`-inherits behaviour, and `.titanproj` round-trip; `--gui` flag opens `MainWindow` for visual verification

### Fixed
- `ClipItem` Y-axis drift — clips were free to move vertically during drag; now locked to their original track lane Y position
- O(n) address→index lookup — removed the `next(i for i, p in self.led_to_dmx.items() if ...)` scan that ran once per LED per frame; replaced with pre-baked numpy arrays and direct boolean indexing
- `TRACK_HEIGHT` / `RULER_HEIGHT` duplication — previously defined separately in `timeline.py` and `track_header.py`; now both import from `widgets/constants.py`
