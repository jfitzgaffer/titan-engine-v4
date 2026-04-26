# Changelog

## [2026-04-24] - MP3 support, audio crash fix, markers, snap, compound clips, dynamic timeline

### Added
- `playback.py` — `load_audio_any(path)`: tries soundfile first, falls back to pydub for MP3/AAC; raises with install instructions if both fail
- `widgets/transport.py` — `*.mp3` added to file dialog filter; `set_audio_state(name, ok)` method so MainWindow controls the label; loading delegated entirely to `_on_audio_loaded` in main.py
- `models/project.py` — `TimelineMarker` dataclass (`time_sec`, `name`, `color_hex`); `group_id: str` field on `Clip`; `markers: List[TimelineMarker]` on `Project`; both persisted via `asdict()` and restored in `load_from_file()`
- `widgets/timeline.py` — `MarkerItem(QGraphicsItem)`: draggable vertical flag line; right-click to rename, change color (QColorDialog), or delete; synced to `project.markers`
- `widgets/timeline.py` — `set_scene_duration(seconds)`: extends `SCENE_WIDTH` if audio is longer than 50 s; called from `_on_audio_duration` signal
- `widgets/timeline.py` — Snap-to-grid (16th-note resolution): toggle with `S` key; applies to clip drag and new clip placement
- `widgets/timeline.py` — Compound clips: `Ctrl+G` groups selected clips (shared `group_id`); grouped clips move together; `Ctrl+Shift+G` ungroup; gold `G` badge drawn on grouped clips
- `widgets/timeline.py` — `Ctrl+D` duplicates all selected clips preserving relative positions and re-mapping group IDs
- `main.py` — `_stop_analysis_worker()`: graceful `quit()+wait(2s)` before `terminate()` fallback; used in `_on_audio_loaded` and `closeEvent`
- `main.py` — `_on_audio_duration(seconds)` signal handler: calls `timeline.set_scene_duration()`
- `main.py` — `_reconnect_controller()`: reconnects only `seek_requested → controller.seek` after a project reload (fixes double-connect crash)
- `main.py` — `M` key global shortcut: places a marker at the current playhead time
- `AudioAnalysisWorker` — `duration_ready = Signal(float)` emitted before analysis; uses `load_audio_any` instead of `sf.read` directly; `target_width` increased from 2000 → 4000 for higher waveform resolution

### Fixed
- Crash when loading audio after a project is opened: `_wire_signals()` was called in both `__init__` and `_reload_project()`, creating duplicate `transport.audio_loaded → _on_audio_loaded` connections; second call to `terminate()` on a running QThread caused macOS segfault. Fix: `_wire_signals()` is called only once; `_reload_project` uses `_reconnect_controller()` instead
- `closeEvent` used `terminate()` on a running worker; now uses `_stop_analysis_worker()` (graceful quit + wait)
- MP3 files were grayed out in the file dialog (soundfile doesn't decode MP3); now handled via pydub fallback

### Changed
- `_on_audio_loaded`: copies audio file to `media/` directory for project portability; sets `project.audio.file_path`; project open auto-loads saved audio if the file still exists
- `_reload_project`: no longer calls `_wire_signals()` — uses `_reconnect_controller()` for the one signal that references the new controller object

## [2026-04-24] - Ruler seek, left properties panel, live preview, combined play/pause, spacebar, audio spectrogram track

### Added
- `widgets/constants.py` — `AUDIO_TRACK_HEIGHT = 80` constant used by both timeline and track header
- `main.py` — `AudioAnalysisWorker(QThread)`: loads mono audio with `soundfile`, computes STFT with numpy `rfft` + Hanning window, log-scales, crops lower 60% of frequency range, resizes vertically, flips (low freq at bottom), colorizes with r/g/b channel math, emits `QImage`; `_on_audio_loaded()` starts the worker and updates `headers.audio_header.set_filename()`
- `main.py` — `QShortcut(Qt.Key_Space)` global shortcut wired to `transport.toggle_play_pause()`
- `main.py` — `_render_current_frame()` re-renders at current playhead position via `compositor.render_frame()` and pushes to visualizer; connected to `properties.params_changed` for live preview while stopped

### Changed
- `widgets/transport.py` — combined Play + Pause into a single checkable `btn_play_pause` toggle (▶ / ⏸); `toggle_play_pause()` public method for spacebar and any external caller; `_refresh_display()` syncs button visual state from `controller.is_playing`
- `widgets/timeline.py` — ruler seek moved to **view level** (`TimelineWidget.mousePressEvent/mouseMoveEvent/mouseReleaseEvent`) with `_seeking` scrub flag; `TimeRulerItem` now uses `setAcceptedMouseButtons(Qt.NoButton)` to avoid event conflicts; added `AudioTrackItem` class (paints spectrogram `QImage` or placeholder text); `_LANES_Y = RULER_HEIGHT + AUDIO_TRACK_HEIGHT` shifts all clip lanes below the audio row; `set_audio_image(qimage)` wires into analysis worker
- `widgets/track_header.py` — added `AudioTrackHeader` (dark-blue theme, `set_filename()` method, height = `AUDIO_TRACK_HEIGHT`); `TrackHeaderPanel` inserts it between ruler spacer and clip track rows
- `widgets/properties.py` — `_ParamRow` gains `changed = Signal()` emitted on both checkbox toggle and spinbox value write; `PropertiesPanel` gains `params_changed = Signal()` forwarded from all rows; wired in `main.py` for live preview
- `main.py` — layout restructured: transport bar full-width; `QSplitter(Qt.Horizontal)` splits `[PropertiesPanel 240 px | right area]`; right area is `QSplitter(Qt.Vertical)` splitting `[DAW headers+timeline | visualizer]`

### Fixed
- Ruler click had no effect — item-level `mousePressEvent` was being consumed by the scene before it reached the ruler; fixed by moving seek handling to the view level
- Properties panel was below the timeline — moved to a fixed-width left sidebar that is always visible
- Parameter changes while stopped had no visual feedback — live preview re-render now fires on every `params_changed` emission
- Play and Pause were separate buttons — merged into one checkable toggle

## [2026-04-24] - Clip resize handles, ruler seek, properties panel, audio loader, file menu

### Added
- `widgets/properties.py` — `PropertiesPanel`: checkbox + spinbox per `ParameterSet` field; unchecked = None (inherit from track), spinbox disabled and shows resolved inherited value in gray; fields grouped Color / Spatial / Envelope Center / Envelope Edge / FX; collapsible bottom panel in `main.py`, shown on clip select, hidden on clear
- `widgets/transport.py` — "Open Audio…" button opens `QFileDialog`; loaded filename shown in green; failure shown in red; pauses/resumes playback around load; emits `audio_loaded` signal
- `main.py` — File menu with New Project, Open Project…, Save, Save As…, Open Audio… (Cmd+N/O/S/Shift+S shortcuts); `_reload_project()` hot-swaps compositor/output/controller without recreating the window; project loaded from `.titanproj` via `Project.load_from_file()`

### Changed
- `widgets/timeline.py` — `ClipItem` left/right 8 px edge handles: left handle adjusts `clip.start` + `clip.duration` together; right handle stretches duration; resize cursor on hover; `ItemIsMovable` flag disabled during resize to prevent position-change conflicts; resize handle hints painted as subtle bright strips; `TimeRulerItem` now responds to mouse press and calls `on_seek` callback; `TimelineWidget` exposes `seek_requested = Signal(float)` and `clip_selected = Signal(object)`; `main.py` wires both
- `main.py` — properties panel wired: `clip_selected` signal looks up owning subtrack+track so `PropertiesPanel.show_clip()` receives full cascade context for resolved-value hints; panel collapses automatically on new project load

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
