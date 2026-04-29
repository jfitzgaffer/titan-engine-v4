"""
MIDI → Titan timeline importer.

Hybrid mapping strategy
-----------------------
  MIDI channel (or track name)  →  Track
  unique pitch within channel   →  SubTrack   (SubTrack.pitch = MIDI note number,
                                               SubTrack.pitch_ratio = normalised 0-1
                                               within that channel's pitch range)
  note event                    →  Clip       (start = seconds, duration = seconds,
                                               params.dim = velocity / 127)

Usage
-----
    from midi_import import import_midi
    n = import_midi("/path/to/score.mid", project)   # appends Tracks
    # or replace=True to clear existing tracks first

Dependencies
------------
    pip install mido
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from models.project import Clip, ParameterSet, SubTrack, Track, VirtualPixel

if TYPE_CHECKING:
    from models.project import Project

# General MIDI channel-10 drum map (note → short name)
_DRUM_NAMES: dict[int, str] = {
    35: "Kick 1", 36: "Kick 2", 37: "Rim", 38: "Snare", 39: "Clap",
    40: "Snare 2", 41: "LT", 42: "HH Closed", 43: "HT", 44: "HH Pedal",
    45: "MT", 46: "HH Open", 47: "LMT", 48: "HMT", 49: "Crash 1",
    50: "HT 2", 51: "Ride 1", 52: "China", 53: "Ride Bell", 54: "Tambourine",
    55: "Splash", 56: "Cowbell", 57: "Crash 2", 59: "Ride 2",
}


def _build_tempo_map(mid) -> list[tuple[int, int]]:
    """Return sorted list of (abs_tick, tempo_µs) pairs from all tracks."""
    raw: dict[int, int] = {0: 500_000}   # default 120 BPM
    for track in mid.tracks:
        abs_tick = 0
        for msg in track:
            abs_tick += msg.time
            if msg.type == "set_tempo":
                raw[abs_tick] = msg.tempo
    return sorted(raw.items())


def _ticks_to_sec(tick: int, tmap: list[tuple[int, int]],
                  ticks_per_beat: int) -> float:
    """Convert an absolute tick count to wall-clock seconds."""
    elapsed = 0.0
    prev_tick, prev_tempo = 0, 500_000
    for map_tick, map_tempo in tmap:
        if map_tick >= tick:
            break
        elapsed += (map_tick - prev_tick) / ticks_per_beat * prev_tempo / 1_000_000
        prev_tick, prev_tempo = map_tick, map_tempo
    elapsed += (tick - prev_tick) / ticks_per_beat * prev_tempo / 1_000_000
    return elapsed


def import_midi(path: str | Path, project: "Project",
                replace: bool = False) -> int:
    """
    Parse *path* and append Tracks to *project*.

    Parameters
    ----------
    path:    path to a .mid / .midi file
    project: Project instance to mutate
    replace: if True, clear project.tracks before importing

    Returns
    -------
    Number of Tracks added.
    """
    try:
        import mido
    except ImportError:
        raise RuntimeError(
            "mido is required for MIDI import.\n"
            "Install with:  pip install mido"
        )

    mid = mido.MidiFile(str(path))
    tmap = _build_tempo_map(mid)
    tpb  = mid.ticks_per_beat or 480

    # ── Collect all note events, grouped by channel ──────────────────────
    # channels[ch] = {'name': str,
    #                 'notes': {pitch: [(start_sec, dur_sec, velocity), ...]}}
    channels: dict[int, dict] = {}

    def _ensure_channel(ch: int, name: str | None = None):
        if ch not in channels:
            channels[ch] = {
                "name": name or ("Drums" if ch == 9 else f"Ch {ch + 1}"),
                "notes": {},
            }
        elif name and channels[ch]["name"].startswith("Ch "):
            channels[ch]["name"] = name

    for midi_track in mid.tracks:
        abs_tick = 0
        track_name: str | None = None
        # pending[(ch, pitch)] = (start_tick, velocity)
        pending: dict[tuple[int, int], tuple[int, int]] = {}

        for msg in midi_track:
            abs_tick += msg.time

            if msg.type == "track_name":
                track_name = msg.name.strip() or None
                continue

            if msg.type not in ("note_on", "note_off"):
                continue

            ch    = msg.channel
            pitch = msg.note
            key   = (ch, pitch)

            _ensure_channel(ch, track_name)

            note_on  = (msg.type == "note_on" and msg.velocity > 0)
            note_off = (msg.type == "note_off") or (
                msg.type == "note_on" and msg.velocity == 0
            )

            if note_on:
                pending[key] = (abs_tick, msg.velocity)

            elif note_off and key in pending:
                start_tick, velocity = pending.pop(key)
                start_sec = _ticks_to_sec(start_tick, tmap, tpb)
                end_sec   = _ticks_to_sec(abs_tick,   tmap, tpb)
                dur_sec   = max(0.05, end_sec - start_sec)
                channels[ch]["notes"].setdefault(pitch, []).append(
                    (start_sec, dur_sec, velocity)
                )

        # Close any notes that never received a note-off
        for (ch, pitch), (start_tick, velocity) in pending.items():
            start_sec = _ticks_to_sec(start_tick, tmap, tpb)
            end_sec   = _ticks_to_sec(abs_tick,   tmap, tpb)
            dur_sec   = max(0.05, end_sec - start_sec)
            _ensure_channel(ch)
            channels[ch]["notes"].setdefault(pitch, []).append(
                (start_sec, dur_sec, velocity)
            )

    # ── Build Titan Tracks ────────────────────────────────────────────────
    if replace:
        project.tracks.clear()

    added = 0
    for ch in sorted(channels):
        ch_data = channels[ch]
        if not ch_data["notes"]:
            continue

        is_drums     = (ch == 9)
        all_pitches  = sorted(ch_data["notes"])
        pitch_min    = all_pitches[0]
        pitch_max    = all_pitches[-1]
        pitch_span   = max(1, pitch_max - pitch_min)
        blob_width   = max(0.04, min(0.25, 1.0 / max(1, len(all_pitches))))

        track = Track(
            name=ch_data["name"],
            blending_mode="Add",
            params=ParameterSet(dim=1.0),
        )

        for pitch in all_pitches:
            ratio = (pitch - pitch_min) / pitch_span   # 0 = lowest, 1 = highest

            if is_drums:
                st_name_hint = _DRUM_NAMES.get(pitch, f"Note {pitch}")
            else:
                note_names = ["C","C#","D","D#","E","F","F#","G","G#","A","A#","B"]
                st_name_hint = f"{note_names[pitch % 12]}{pitch // 12 - 1}"

            st = SubTrack(
                pitch=float(pitch),
                pitch_ratio=round(ratio, 4),
                params=ParameterSet(),
            )

            for start_sec, dur_sec, velocity in sorted(ch_data["notes"][pitch]):
                clip = Clip(
                    start=round(start_sec, 4),
                    duration=round(dur_sec, 4),
                    params=ParameterSet(dim=round(velocity / 127.0, 3)),
                    pixels=[VirtualPixel(x=round(ratio, 4), width=blob_width)],
                )
                st.clips.append(clip)

            track.sub_tracks.append(st)

        project.tracks.append(track)
        added += 1

    return added


def midi_duration_seconds(path: str | Path) -> float:
    """Return total playback duration of the MIDI file in seconds."""
    try:
        import mido
        mid  = mido.MidiFile(str(path))
        tmap = _build_tempo_map(mid)
        tpb  = mid.ticks_per_beat or 480
        max_tick = 0
        for track in mid.tracks:
            abs_tick = sum(msg.time for msg in track)
            max_tick = max(max_tick, abs_tick)
        return _ticks_to_sec(max_tick, tmap, tpb)
    except Exception:
        return 0.0
