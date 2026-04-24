# Titan Engine v4 — TODO

Build order follows the risk-first sequence from PLAN.md: data model → renderer → clock → output → GUI.

---

## Phase 1: Core Pipeline (no GUI)

- [x] **`models/project.py`** — `ParameterSet`, `resolve_params()` cascade, full hierarchy (`VirtualPixel`, `Clip`, `SubTrack`, `Track`, `Project`, `SpatialSegment`)
- [x] **`spatial.py`** — `SpatialMapper`, `PhysicalFixture`, `_build_lookup_table()`, `get_physical_pixels_in_range()`
- [x] **`compositor.py`** — `CompositorEngine`, `evaluate_envelope()`, `render_frame()` with per-track compositing
- [ ] **Vectorize compositor inner loop** — replace Python `for led in physical_leds` loop with numpy array operations (critical for >64 pixel fixtures)
- [ ] **`models/project.py` serialization** — implement `Project.to_dict()` / `Project.from_dict()` for `.titanproj` JSON round-trip; add `"version": 4` field
- [ ] **Unit tests for cascade** — verify `resolve_params()` priority: Clip > SubTrack > Track; verify `None` truly inherits

## Phase 2: Playback & Output

- [x] **`playback.py` — basic thread clock** — `play()`, `pause()`, `seek()`, `on_frame_ready` callback
- [ ] **`playback.py` — `sounddevice` integration** — replace `time.perf_counter` clock with `sounddevice` stream callback `stream.time` (PaTime) for sample-accurate sync; load audio file with `soundfile`
- [ ] **`output/output_manager.py`** — port Art-Net sender + sACN sender from v3 `main_v5.01.py`; keep packet layouts spec-exact; run on dedicated thread
- [ ] **End-to-end smoke test** — `test_arch.py` boots full stack → compositor renders → packet appears on UDP 6454

## Phase 3: GUI — Timeline

- [x] **`widgets/timeline.py` skeleton** — `QGraphicsView`, `TimeRulerItem` with second/sub-second ticks, `ClipItem` as draggable `QGraphicsRectItem`
- [x] **`widgets/track_header.py`** — left-side panel: track name, mute/solo, blending mode, opacity slider
- [x] **`widgets/visualizer.py`** — 1D LED strip, `QPainter.fillRect()` per pixel, 60 Hz via Qt signal
- [ ] **`widgets/timeline.py` — clip drag & resize** — drag-move changes `clip.start`; left/right resize handles change `clip.start` / `clip.duration`; snap to ruler grid
- [ ] **`widgets/timeline.py` — zoom & scroll** — horizontal zoom (Cmd+scroll), horizontal scroll; `PIXELS_PER_SECOND` is dynamic
- [ ] **`widgets/timeline.py` — playhead drag** — click/drag on ruler seeks `PlaybackController`
- [ ] **`widgets/timeline.py` — multi-track layout** — scroll area for > 4 tracks; track lanes expand/collapse
- [ ] **`widgets/timeline.py` — waveform underlay** — compute spectrogram with `librosa` at file-load time; render as `QImage` behind clips

## Phase 4: GUI — Properties & Editing

- [ ] **`widgets/properties.py` — PropertiesPanel** — context-sensitive form for selected Track/SubTrack/Clip/VirtualPixel; each `ParameterSet` field has a "Set / Inherit" toggle; grayed-out field shows inherited effective value
- [ ] **`widgets/visualizer.py` — pixel editor mode** — when a Clip is selected, clicking in the Visualizer adds/moves a `VirtualPixel`; mirrors piano-roll spatial metaphor
- [ ] **Transport bar** — Play/Pause/Stop buttons, time display (seconds + frames), BPM field

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

- [ ] **`compositor.py` — Python per-LED loop** — `for led in physical_leds` in `render_frame()` must be vectorized with numpy before the engine can scale
- [ ] **`playback.py` — clock jitter** — `time.perf_counter` loop has OS scheduling jitter; replace with `sounddevice` PaTime
- [ ] **`compositor.py` — LED index lookup** — `next(i for i, p in self.led_to_dmx.items() if p["address"] == led["address"])` is O(n) per LED per frame; pre-build a reverse address→index dict at `__init__` time
- [ ] **`models/project.py`** — `SpatialSegment` is defined but not yet part of `Project` dataclass (not linked to `Track.fixture_ids`)
- [ ] **`test_arch.py`** — playhead loops at 6 s but never stops cleanly; add proper `QApplication.quit()` path
