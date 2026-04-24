# Titan Engine v4 — Project Context & Agent Rules

## What This Project Is

Titan Engine v4 is a **DAW-style audio-reactive DMX lighting engine** for film and stage. It is a ground-up architectural rewrite of [Titan Engine v3](https://github.com/jfitzgaffer/titan-engine-v3), which used a flat `params` dict, a monolithic GUI, and a Pure Data subprocess for audio analysis.

v4 replaces that flat model with a **5-level hierarchy** (Project → Track → SubTrack → Clip → VirtualPixel), a compositing pipeline borrowed from video editing, and a timeline-based UI modeled after a DAW. The result is a tool a gaffer can use to design complex multi-fixture lighting shows — both triggered live from audio and composed offline against a backing track.

**Primary user: a gaffer, not a programmer.** Favor clarity, safety rails, and graceful failure over clever abstractions. Any change that could blackout a live show must have a user-visible confirmation.

## Technology Stack

| Layer | Tool |
|---|---|
| Language | Python 3.12+ |
| GUI | PySide6 (Qt) |
| Audio (DAW mode) | `sounddevice` + `soundfile` |
| Audio (live mode) | Pure Data subprocess via `TitanWatchdog` (ported from v3) |
| DSP analysis | `librosa` (offline FFT, onset detection, beat tracking) |
| Rendering math | `numpy` (vectorized — no per-pixel Python loops) |
| MIDI import | `pretty_midi` |
| DMX output | Native `socket` — Art-Net (UDP 6454) and sACN (UDP 5568) |
| Stem separation | `demucs` + PyTorch (optional install) |

## Current File Map

| File / Folder | Status | Role |
|---|---|---|
| `models/project.py` | ✅ Started | `ProjectModel`, `ParameterSet`, cascade logic (`resolve_params`), full 5-level dataclass hierarchy |
| `compositor.py` | ✅ Started | `CompositorEngine` — frame-render pipeline; evaluates ADSR envelopes, composites track buffers via numpy |
| `spatial.py` | ✅ Started | `SpatialMapper` — builds a one-time lookup table mapping virtual X coords (0–1) → `(universe, dmx_address)` pairs |
| `playback.py` | 🔄 In progress | `PlaybackController` — clock thread, play/pause/seek; currently uses `time.perf_counter`; needs `sounddevice` sample-clock |
| `widgets/timeline.py` | 🔄 In progress | `TimelineWidget` — QGraphicsView with `ClipItem`, `TimeRulerItem`; interactive drag/resize not yet wired |
| `widgets/visualizer.py` | 🔄 In progress | `VisualizerWidget` — paints a 1D LED strip from the current DMX packet at 60 Hz |
| `widgets/track_header.py` | 🔄 In progress | Left-side track header panel (name, mute, blending mode, opacity) |
| `test_arch.py` | 🔄 In progress | Integration test / dev harness — boots full stack with a dummy project |
| `importers/` | ⬜ Not started | MIDI importer (`pretty_midi`), v3 preset importer |
| `analysis/` | ⬜ Not started | Offline audio analysis, stem separation (`demucs`) |
| `output/` | ⬜ Not started | `OutputManager` — Art-Net/sACN sender (ported from v3 `main_v5.01.py`) |
| `main.py` | ⬜ Not started | App entry point, wires together all components |

## Architecture: The 5-Level Hierarchy

```
Project
  ├── AudioReference        (file path, waveform cache, sample rate)
  ├── SpatialMap            (fixture → abstract 1D axis segments)
  ├── OutputConfig          (Art-Net/sACN settings)
  └── List[Track]
        ├── ParameterSet    (track-level defaults — None = inherit)
        ├── blending_mode   (Overwrite | Add | Multiply)
        ├── opacity: float
        └── List[SubTrack]
              ├── pitch: float        (MIDI note number)
              ├── pitch_ratio: float  (0–1 normalized in track range)
              ├── ParameterSet        (sub-track overrides)
              └── List[Clip]
                    ├── start: float  (seconds)
                    ├── duration: float
                    ├── ParameterSet  (clip-level overrides — highest priority)
                    └── List[VirtualPixel]
                          ├── x: float    (0.0–1.0 on abstract axis)
                          └── width: float
```

**Cascade rule:** `None` means inherit. Walking up Clip → SubTrack → Track, the first non-`None` value wins. This is implemented in `models/project.py::resolve_params()`.

**`SpatialMap` is the bridge to physical DMX.** It maps virtual axis positions to `(fixture_id, universe, start_address)` tuples. This is the one concept v3 entirely lacked — everything else in the output stack survives.

## Frame Render Pipeline (compositor.py)

```
render_frame(playhead_time T):
  For each Track (bottom → top):
    Allocate numpy float32 raster_buffer[N_pixels × 4]
    For each SubTrack:
      For each active Clip (start ≤ T < start + duration + max_release_tail):
        resolved = resolve_params(clip, subtrack, track)
        env_c = evaluate_ADSR(T, center ADSR params)
        env_e = evaluate_ADSR(T, edge ADSR params)
        For each VirtualPixel:
          physical_leds = mapper.get_physical_pixels_in_range(x, width)
          For each LED:
            dist = spatial distance from center (0.0 = center, 1.0 = edge)
            final_env = lerp(env_c, env_e, dist)
            track_buffer[led_idx] += color * final_env
    Composite track_buffer → master_buffer (Overwrite | Add | Multiply)
  Map master_buffer → DMX channels via SpatialMapper
  Return dmx_packet as bytearray
```

**Performance rule: no per-pixel Python loops.** All inner loops must be numpy array operations. The current `compositor.py` still has a Python `for led in physical_leds` loop — this must be vectorized before v4 can scale to 64+ pixel fixtures.

## What Survives from v3

| v3 Component | v4 Fate |
|---|---|
| DMX output (Art-Net/sACN packet building + sender thread) | Port intact to `output/output_manager.py` |
| Per-pixel wave model, ADSR math, glitch/overdrive/knee FX | Port to stateless functions in `compositor.py`; vectorize |
| `TitanWatchdog` + Pure Data OSC sidecar | Keep for live mode; add a separate librosa offline analysis path |
| `AudioCalibrator` | Keep; moves to a Settings panel |
| `FixturePatchWidget` | Port; becomes the Stage Setup / Spatial Map editor |
| Preset system (JSON) | Migrate; new project format is `.titanproj`. Write a one-shot importer from the v3 flat format |
| `titan_gui.py` (148 KB monolith) | Retire; ground-up rewrite |

## Coding Standards

### numpy everywhere
- All inner rendering loops must be vectorized. If you write `for pixel in pixels:`, stop and rewrite it as an array operation.
- Keep a pre-allocated zero buffer for the raster; don't allocate inside the render loop.

### Stateless compositor
- `CompositorEngine.render_frame()` must be a pure function of `(project, mapper, playhead_time)`. All mutable state lives in `ProjectModel`, not in the compositor.

### Thread safety
- The render thread writes DMX buffers; the Qt thread reads them. Use a single `threading.Lock` around the handoff (same `buf_lock` pattern as v3).
- Use Qt signals (`Signal(bytearray)`) as the bridge from background threads to the GUI thread. Never call Qt widget methods from a non-Qt thread.

### Dark mode UI
- Background: `#1a1a1a` / `#2b2b2b`. Track lanes: `#1e1e1e`. Clip accent colors per-track.
- Neon accents: Green `#00ff66`, Yellow `#ffff00`, Red `#ff5555`, Blue `#4488ff`.
- Playhead: `#ff4444` (bright red, always on top, Z-value > all clips).

### Parameter cascade
- `None` always means "inherit from parent". Never use `0` as a sentinel for "not set".
- When adding a new parameter to `ParameterSet`, add it to `models/project.py` and ensure it round-trips through `.titanproj` JSON serialization.

### No bare excepts
- Never use a bare `except:` without a `logger.warning(...)`. Silent swallowing is worse than crashing.

## Project File Format (.titanproj)

A `.titanproj` file is a JSON object matching the `Project` dataclass hierarchy (via `dataclasses.asdict()`). Loading uses `Project.from_dict()`. Saving uses `json.dump(dataclasses.asdict(project))`.

Keep a `"version": 4` field at the top level so future migrations can detect old formats.

## What NOT to Change Without Discussion

- The Art-Net and sACN packet layouts (ported from v3 — spec-correct).
- The 18-channel global + 13-per-fixture control-universe mapping (users have QLC+ show files built against this).
- The `preset_ch` slot-thresholds (standard lighting convention).

## CRITICAL AGENT RULES: CODE MODIFICATION

- **Mandatory Self-Review:** After editing any file, run `git diff` before declaring the task finished.
- **The Retention Rule:** Check the red `-` lines. If you removed classes, imports, or functions the user didn't ask you to remove, immediately restore them.
- **No Lazy Truncation:** Never use `# ... rest of code here ...` to skip writing the full file.
- **No New Files Without Reason:** Prefer editing existing files. Only create new modules when the architecture explicitly calls for them.

## CRITICAL AGENT RULES: VERSION CONTROL & DOCUMENTATION

- **Main Branch Default:** All edits land directly on `main` unless the user explicitly says otherwise.
- **The Changelog Mandate:** Before any `git commit`, update `CHANGELOG.md`. If it doesn't exist, create it.
- **Changelog Format:** Use "Keep a Changelog" format. Header: `### [YYYY-MM-DD] - Task Summary`. Bullets under `Added`, `Changed`, `Fixed`, `Removed`.
- **Print the Changelog Entry:** Always print the new entry verbatim in chat so the user can read it without opening the file.
- **Exhaustive Commit Messages:** First line = concise summary. Following lines = bulleted list of every change analyzed from `git diff --cached`.
- **Mandatory Testing Protocol:** After committing, provide a step-by-step manual test guide specifying exactly which widgets to interact with and which outputs to monitor.
