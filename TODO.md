# Titan Engine v4 — TODO

Build order follows the risk-first sequence from PLAN.md: data model → renderer → clock → output → GUI.

---

## Phase 1: Core Pipeline (no GUI)

- [x] **`models/project.py`** — `ParameterSet`, `resolve_params()` cascade, full hierarchy (`VirtualPixel`, `Clip`, `SubTrack`, `Track`, `Project`, `SpatialSegment`)
- [x] **`spatial.py`** — `SpatialMapper`, `PhysicalFixture`, `_build_lookup_table()`, `get_physical_pixels_in_range()`
- [x] **`compositor.py`** — `CompositorEngine`, `evaluate_envelope()`, `render_frame()` with per-track compositing
- [x] **Vectorize compositor inner loop** — numpy boolean range queries + broadcast envelope/color multiply; no Python per-LED iteration
- [x] **`models/project.py` serialization** — `save_to_file()` / `load_from_file()` with full hierarchy rebuild; `version: 4` field; expanded `OutputConfig`
- [x] **Unit tests for cascade** — `TestCascade` in `test_arch.py` verifies Clip > SubTrack > Track priority and `None`-inherits behaviour

## Phase 2: Playback & Output

- [x] **`playback.py` — basic thread clock** — `play()`, `pause()`, `seek()`, `on_frame_ready` callback
- [x] **`playback.py` — `sounddevice` integration** — `load_audio()` with `soundfile`; stream callback drives playhead from hardware sample clock; graceful fallback to `perf_counter` when no audio loaded
- [x] **`output/output_manager.py`** — spec-exact Art-Net + sACN packet builders ported from v3; queue-based sender thread; non-blocking `send()` drops oldest frame if behind
- [x] **End-to-end smoke test** — `test_arch.py` headless tests verify dark/lit/dark lifecycle; `python test_arch.py --gui` opens full Qt window

## Phase 3: GUI — Timeline

- [x] **`widgets/timeline.py` skeleton** — `QGraphicsView`, `TimeRulerItem` with second/sub-second ticks, `ClipItem` as draggable `QGraphicsRectItem`
- [x] **`widgets/track_header.py`** — left-side panel: track name, blending mode, opacity slider with % readout
- [x] **`widgets/visualizer.py`** — 1D LED strip, `QPainter.fillRect()` per pixel, 60 Hz via Qt signal
- [x] **`widgets/constants.py`** — shared `TRACK_HEIGHT`, `RULER_HEIGHT`, `PIXELS_PER_SECOND` so timeline and headers never drift out of sync
- [x] **`widgets/transport.py`** — Play/Pause/Stop bar with live `M:SS.mmm` time display at 30 Hz
- [x] **`main.py`** — proper app entry point: builds demo project, wires pipeline, opens `MainWindow` with transport + DAW + visualizer
- [x] **`widgets/timeline.py` — Y-axis lock bug** — `ClipItem` now locks Y to its track lane; dragging can no longer pull clips off their track
- [x] **`widgets/timeline.py` — zoom & scroll** — horizontal zoom (Cmd/Meta + scroll); horizontal scroll bar always visible
- [x] **`widgets/timeline.py` — clip resize handles** — left/right 8 px edge handles; left handle moves `clip.start` and adjusts `clip.duration`; right handle stretches `clip.duration`; Y-lock preserved during resize; resize cursor on hover
- [x] **`widgets/timeline.py` — ruler click-to-seek** — seek handling moved to view level (`mousePressEvent`) with scrub flag; `TimeRulerItem` uses `Qt.NoButton` to avoid event conflicts; `seek_requested` signal wired to `controller.seek()`
- [x] **`widgets/timeline.py` — `clip_selected` signal** — clicking a clip emits `clip_selected(clip)`; wired to `PropertiesPanel.show_clip()` in `main.py`
- [x] **`widgets/timeline.py` — audio spectrogram row** — `AudioTrackItem` paints `QImage` spectrogram (or placeholder); `set_audio_image()` receives result from `AudioAnalysisWorker`; row is above all clip lanes
- [x] **`widgets/track_header.py` — audio track header** — `AudioTrackHeader` matches audio row height; `set_filename()` changes label color from gray to blue
- [x] **`widgets/transport.py` — combined play/pause toggle** — single checkable button (▶ / ⏸); `toggle_play_pause()` for spacebar; `_refresh_display()` syncs state from controller
- [x] **`main.py` — spacebar shortcut** — `QShortcut(Qt.Key_Space)` wired to `transport.toggle_play_pause()`
- [x] **`main.py` — left properties sidebar** — `PropertiesPanel` in fixed 240 px left panel always visible; `QSplitter(Qt.Horizontal)` separates it from timeline area
- [x] **`main.py` — live parameter preview** — `properties.params_changed` → `_render_current_frame()` re-renders at current playhead position even when stopped
- [x] **`main.py` — `AudioAnalysisWorker`** — numpy-only spectrogram (no librosa): STFT with Hanning window, log-scale, lower-60% frequency crop, vertical resize, flip, colorize; emits `QImage`
- [ ] **`widgets/timeline.py` — multi-track vertical scroll** — scroll area for > 6 tracks; track lanes expand/collapse
- [ ] **`widgets/timeline.py` — waveform underlay on clip lanes** — optional per-track audio waveform behind clips

## Phase 4: GUI — Properties & Editing

- [x] **`widgets/properties.py` — PropertiesPanel** — checkbox (own) + spinbox per `ParameterSet` field; unchecked = None (inherit), spinbox disabled and shows resolved inherited value; grouped Color / Spatial / Envelope Center / Envelope Edge / FX; collapsible bottom panel in `main.py`
- [x] **`widgets/transport.py` — Open Audio button** — `QFileDialog` picker; filename shown in transport bar; calls `controller.load_audio()`; pauses and resumes playback around load; failure shown in red
- [x] **`main.py` — File menu** — New Project, Open Project, Save, Save As, Open Audio; Cmd+N/O/S/Shift+S shortcuts; project open/save via `.titanproj`; `_reload_project()` hot-swaps pipeline without recreating window
- [ ] **`widgets/visualizer.py` — pixel editor mode** — when a Clip is selected, clicking in the Visualizer adds/moves a `VirtualPixel`; mirrors piano-roll spatial metaphor

## Phase 5: Import & Content

- [ ] **`importers/midi.py` — MidiImporter** — parse `.mid` with `pretty_midi`; two-step wizard: (1) assign MIDI tracks → Lighting tracks; (2) pitch → sub-track range mapping; output `List[Clip]` per sub-track at MIDI note timings
- [ ] **`importers/v3_preset.py`** — one-shot importer: v3 flat JSON preset → single-track `.titanproj` project
- [ ] **File menu** — New Project, Open `.titanproj`, Save, Save As, Import MIDI, Import v3 Preset

## Phase 6: FX & Live Mode

- [ ] **FX expansion** — port `glitch_digi`, `glitch_ana`, `overdrive`, `knee`, `eq_tilt` from v3 `titan_engine.py` as stateless numpy functions; register in a `FXNode` catalog
- [ ] **Chase / strobe FX** — add to FXNode catalog alongside existing effects
- [ ] **Live mode — Pure Data sidecar** — port `TitanWatchdog` from v3; OSC listener on UDP 5005 feeds a synthetic `Clip` stream instead of a static timeline
- [ ] **Live mode — librosa real-time fallback** — if Pure Data is unavailable, use `librosa.stream` for live onset detection

## Phase 7: Polish & Stretch Goals

- [ ] **Audio calibration** — port `AudioCalibrator` from v3; expose in Settings panel
- [ ] **Fixture patch editor** — port `FixturePatchWidget` from v3; wire to `SpatialMapper` rebuild
- [ ] **Autosave** — write `.titanproj` every 60 s; on next launch offer to restore if autosave is newer than last manual save
- [ ] **Keyboard shortcuts** — Space = play/pause, B = blackout, 1–9 = preset slot, Cmd-Z = undo last clip edit
- [ ] **Undo / redo** — `QUndoStack` around all clip mutations
- [ ] **`analysis/stems.py` — StemSeparator** — wrap `demucs` (optional install) in a `QThread` with progress dialog; each stem → separate `AudioReference` on its own track
- [ ] **Network Health panel** — pps sent, pps received, last error per destination, rolling latency graph

---

## Known Issues / Bugs to Fix

- [x] **`compositor.py` — Python per-LED loop** — vectorized with numpy boolean range queries + broadcast multiply; no per-LED Python iteration
- [x] **`playback.py` — clock jitter** — `sounddevice` PaTime drives playhead when audio loaded; `perf_counter` fallback otherwise
- [x] **`compositor.py` — LED index lookup** — pre-baked `_led_xs`, `_led_addrs`, `_led_channels`, `_led_universes` arrays built in `__init__`; O(1) boolean indexing per frame
- [ ] **`models/project.py`** — `SpatialSegment` is defined but not yet part of `Project` dataclass (not linked to `Track.fixture_ids`)
- [ ] **`test_arch.py`** — playhead loops at 6 s but never stops cleanly; add proper `QApplication.quit()` path
