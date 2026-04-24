# Titan Engine v4 — Architecture Plan

## The Core Paradigm Shift

v3 is a flat `params` dict driving a single render pass. v4 is a **DAW**: a timeline of composited tracks, each with independent parameter cascades, driving the same DMX output layer.

The entire shift lives in the data model. Everything downstream — rendering, output, fixture patching — is an evolution of what already exists in v3.

---

## 1. Data Model

All parameters use `Optional[T]`. `None` means "inherit from parent." The first non-`None` value walking up the hierarchy wins.

```
Project
  ├── AudioReference        (file path, waveform cache, sample rate)
  ├── SpatialMap            (fixture → abstract 1D axis segments)
  ├── OutputConfig          (Art-Net/sACN — current engine params survive here)
  └── List[Track]
        ├── ParameterSet    (track-level defaults)
        ├── blending_mode   (Overwrite | Add | Multiply)
        ├── opacity: float
        ├── fixture_ids     (which DMX fixtures this track drives)
        └── List[SubTrack]
              ├── pitch: float        (MIDI note number)
              ├── pitch_ratio: float  (0–1 in track's pitch range)
              ├── ParameterSet        (sub-track overrides)
              └── List[Clip]
                    ├── start: float  (seconds)
                    ├── duration: float
                    ├── ParameterSet  (clip-level overrides — highest priority)
                    └── List[VirtualPixel]
                          ├── x: float    (0.0–1.0 on abstract axis)
                          └── width: float
```

### ParameterSet fields (all `Optional[float]`)

| Group | Fields |
|---|---|
| Color | `dim`, `r`, `g`, `b`, `w` |
| Spatial | `effect_width`, `x_position` |
| ADSR center | `atk_c`, `dec_c`, `sus_c`, `rel_c` |
| ADSR edge | `atk_e`, `dec_e`, `sus_e`, `rel_e` |
| FX | `glitch_digi`, `glitch_ana`, `overdrive`, `knee`, `eq_tilt` |

### SpatialMap — the key new concept

```python
@dataclass
class SpatialSegment:
    fixture_id: str      # maps to f{N}_uni, f{N}_addr, f{N}_pix from v3
    x_start: float       # where this fixture begins on the 0.0–1.0 axis
    x_end: float
    flip: bool = False   # reverse pixel order
```

This is the bridge from virtual positions to physical DMX channels. Everything else in `OutputConfig` survives from v3 intact.

---

## 2. Rendering Pipeline

Runs at ~44–60 Hz, driven by `PlaybackController`.

```
render_frame(T = playhead_seconds):

For each Track (bottom layer first):
  │
  ├─ Allocate raster_buffer[N_physical_pixels × 4]  (numpy float32)
  │
  ├─ For each SubTrack:
  │    ├─ Find active clips where start ≤ T < start + duration + max_release
  │    └─ For each active Clip:
  │         ├─ resolved = resolve_params(clip, subtrack, track)
  │         ├─ env_c = evaluate_ADSR(T, clip.start, clip.duration, resolved [center])
  │         ├─ env_e = evaluate_ADSR(T, clip.start, clip.duration, resolved [edge])
  │         ├─ For each VirtualPixel:
  │         │    ├─ physical_leds = mapper.get_physical_pixels_in_range(x, width)
  │         │    └─ For each LED:
  │         │         dist = abs(led.x - pixel.x) / half_width  (0.0 = center)
  │         │         final_env = lerp(env_c, env_e, dist)
  │         │         track_buffer[idx] += color * final_env
  │         └─ (vectorize the LED loop with numpy)
  │
  ├─ Composite sub-track buffers → track_buffer
  └─ Apply track opacity

Composite all track_buffers → master_buffer
  Overwrite: later track replaces earlier
  Add:       clamp(a + b, 0, 255)
  Multiply:  a * b / 255

Map master_buffer virtual positions → DMX channels via SpatialMapper
Send DMX packet
```

**The wave-propagation model (center-to-edge ripple) is kept from v3 RenderEngine** — it just moves from per-fixture to per-VirtualPixel and gets vectorized.

---

## 3. Component Inventory

### Keep / Port from v3

| Component | Action | Notes |
|---|---|---|
| RenderEngine DSP core | Port | Move to stateless functions in `compositor.py`. Vectorize all pixel loops. |
| DMX output (Art-Net/sACN) | Port intact | Move to `output/output_manager.py`. Zero logic change. |
| TitanWatchdog + Pure Data | Keep for live mode | Add a `librosa`-based offline analysis path alongside it. |
| AudioCalibrator | Keep | Moves to a Settings panel. Unchanged. |
| FixturePatchWidget | Port | Becomes the Stage Setup / Spatial Map editor. |
| Preset system (JSON) | Migrate | New format: `.titanproj` (JSON). Write a one-shot importer from v3 flat format. |
| FX catalog | Expand | All current FX become entries in a FXNode registry. Chases/strobes added alongside them. |

### Retire

| Component | Reason |
|---|---|
| `titan_gui.py` (148 KB) | Ground-up rewrite. Output config, fixture patch, and calibration dialogs can be extracted as floating panels. |

---

## 4. New Components Required

### 4.1 `models/project.py` — ProjectModel
Pure dataclasses + `resolve_params()` cascade logic. No Qt dependencies. Serializes to/from `.titanproj` JSON. **Build and unit-test this first** — it is the center of everything.

**Status: Started.** `ParameterSet`, `resolve_params`, `VirtualPixel`, `Clip`, `SubTrack`, `Track`, `Project`, `SpatialSegment` all defined.

### 4.2 `compositor.py` — CompositorEngine
Replaces `RenderEngine`. Runs the frame-render pipeline. Uses numpy arrays throughout. Stateless per call. Runs on a dedicated thread at ~44 Hz.

**Status: Started.** `evaluate_envelope()` and `render_frame()` exist. Inner LED loop is still Python — needs vectorization.

### 4.3 `spatial.py` — SpatialMapper
Converts virtual pixel positions (0.0–1.0) → `(universe, dmx_address)` pairs. One-time computation per project; invalidates on fixture patch change.

**Status: Started.** `PhysicalFixture`, `SpatialMapper`, `_build_lookup_table()`, `get_physical_pixels_in_range()` all implemented.

### 4.4 `playback.py` — PlaybackController
- Owns `playhead_position` (float, seconds)
- Drives audio playback via `sounddevice` + `soundfile` (replace Pure Data for DAW mode)
- Provides `play()`, `pause()`, `seek(t)`, `get_position()` — thread-safe
- Fires a Qt signal on each frame tick that `CompositorEngine` consumes
- For live mode: continues to receive from PD/OSC as today

**Status: Started.** Basic `time.perf_counter` clock loop works. `sounddevice` sample-clock integration not yet done.

### 4.5 `widgets/timeline.py` — TimelineWidget
Custom `QWidget` drawn with `QPainter`. Sub-widgets:

- `TimeRulerWidget` — time ruler (seconds or bars/beats), zoom-aware
- `TrackHeaderPanel` — left fixed panel: name, mute/solo, blending, opacity, expand/collapse
- `ClipCanvas` — right scrollable panel: clips as colored rectangles, waveform background, playhead line
- `ClipItem` — individual clip; drag-move, resize handles on left/right edges
- `PlayheadWidget` — vertical line, draggable, synced to `PlaybackController`

**Performance:** Clip items are **not Qt widgets** — they are painted regions on the canvas. Only the canvas widget exists in Qt's widget tree. This is mandatory for scalability.

**Status: Started.** `QGraphicsView`-based skeleton with `ClipItem` and `TimeRulerItem`. Interaction not yet wired.

### 4.6 `widgets/visualizer.py` — VisualizerWidget
A `QWidget` that paints a horizontal 1D strip showing the current compositor output. 60 Hz refresh via `QTimer`. One `QPainter.fillRect()` per pixel group.

**Status: Started.** Basic painter working.

### 4.7 `widgets/properties.py` — PropertiesPanel
Context-sensitive form panel. Shows `ParameterSet` fields for whatever is selected (Track / SubTrack / Clip / VirtualPixel). Each field has a "Set / Inherit" toggle — `None` shows as grayed-out with the inherited effective value displayed.

**Status: Not started.**

### 4.8 `importers/midi.py` — MidiImporter
Uses `pretty_midi`. Parses `.mid` files → mapping dialog lets user assign MIDI tracks → Lighting tracks and pitch ranges → Sub-tracks. Outputs `List[Clip]` per sub-track, positioned to MIDI note timings.

**Status: Not started.**

### 4.9 `output/output_manager.py` — OutputManager
Port of the Art-Net/sACN sender from `main_v5.01.py`. Runs on a dedicated thread. Receives a `bytearray(512)` per universe from the compositor and sends UDP packets.

**Status: Not started.**

### 4.10 `analysis/stems.py` — StemSeparator (stretch goal)
Wraps `demucs` (optional install). Runs in a `QThread` with a progress dialog. Produces 4–6 audio stems as `.wav` files, each loadable as a separate `AudioReference` on its own track.

**Status: Not started.**

### 4.11 `analysis/spectrum.py` — SpectrumUnderlay
Toggleable semi-transparent FFT waterfall rendered behind the clip canvas. `librosa` computes the spectrogram offline at load time; stored as a numpy array; displayed as a `QImage` texture during playback.

**Status: Not started.**

---

## 5. Risk Assessment

| Risk | Severity | Mitigation |
|---|---|---|
| **Timeline widget paint performance** | High | Never use `QGraphicsScene` for clip layer. Single `QPainter` canvas with manual culling. Use `QOpenGLWidget` if pure Python painting can't hit 30 fps at 50 tracks. |
| **Audio-timeline synchronization** | High | Use `sounddevice` stream callback's `stream.time` (PaTime) as the clock source, not `time.time()`. Implement latency compensation as a user-adjustable offset. |
| **Compositor performance at scale** | Medium | Every inner loop must be numpy-vectorized. Current `compositor.py` has Python per-LED loops — must be rewritten before v4 can scale. Profile after initial port; use `numba` JIT if still slow. |
| **Parameter cache performance** | Medium | Cache `resolve_params()` per clip; invalidate only when a `ParameterSet` is mutated (rare in human editing). Brings per-frame cost to near zero. |
| **Proportional pitch scaling** | Medium | Use MIDI-log pitch normalization. Store `pitch_ratio` on `SubTrack`. Apply as multiplier to time-based params. Preview in `PropertiesPanel` before committing. |
| **Demucs dependency size** | Medium | Optional install (`pip install demucs` in extras). Fall back gracefully. Run in background `QThread`. Offer `spleeter` as lighter alternative. |
| **Virtual pixel UX** | Low-Medium | Visualizer doubles as pixel editor for selected clip. Click in Visualizer while clip selected → add/move virtual pixel. Mirrors DAW piano-roll spatial metaphor. |
| **MIDI import complexity** | Low | Two-step wizard: (1) assign MIDI tracks to lighting tracks; (2) define pitch → sub-track range. `pretty_midi` API is reliable. |

---

## 6. Build Order

Highest-leverage sequence that de-risks the hardest parts first:

1. **`models/`** — `ProjectModel` + `ParameterSet` cascade (no GUI, pure unit-testable) ✅ Started
2. **`compositor.py` + `spatial.py`** — numpy-vectorized rendering pipeline, verified against v3 output ✅ Started
3. **`playback.py`** — audio file playback with sample-accurate `sounddevice` clock 🔄 Partial
4. **`output/output_manager.py`** — port Art-Net/sACN from v3 ⬜
5. **`widgets/timeline.py` skeleton** — ruler + scrollable track lanes + static clip painting (no interaction yet) 🔄 Partial
6. **`widgets/visualizer.py`** — simple pixel strip driven by compositor output 🔄 Partial
7. **Clip interaction** — drag, resize, select, properties panel binding ⬜
8. **`widgets/properties.py`** — ParameterSet editor with Set/Inherit toggles ⬜
9. **MIDI importer** — brings real content into the timeline fast ⬜
10. **FX expansion** — port current effects, add chase/strobe ⬜
11. **Live mode** — re-integrate Pure Data/OSC path via `TitanWatchdog` ⬜
12. **Stem separator** (if time permits) ⬜

---

## 7. New Dependencies

| Package | Purpose | Risk |
|---|---|---|
| `sounddevice` | Audio playback + sample-accurate clock | Low |
| `soundfile` | Audio file decoding (WAV/FLAC/OGG) | Low |
| `librosa` | Offline FFT, onset detection, beat tracking | Low |
| `pretty_midi` | MIDI file parsing | Low |
| `numpy` | Already present — expand use everywhere | None |
| `numba` | JIT for hot compositor loops (if needed) | Low |
| `demucs` + `torch` | AI stem separation | High (optional install) |

Keep from v3: `python-osc`, `pyqtgraph`, `PySide6`

---

## TL;DR

The biggest reusable asset is the **DMX output layer and FX math** — port it, don't rewrite it. The biggest new build is the **TimelineWidget and ProjectModel** — those are the architectural center of gravity and should be designed and tested independently before the GUI wraps around them. The hardest technical bets are timeline paint performance and audio-visual sync; both have established solutions in DAW literature, but they require discipline to implement correctly in Python.
