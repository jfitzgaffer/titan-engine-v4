import json
from dataclasses import dataclass, field, asdict, fields
from typing import List, Optional, Dict, Any


# ---------------------------------------------------------
# 1. PARAMETER SET & CASCADE LOGIC
# ---------------------------------------------------------

@dataclass
class ParameterSet:
    """Holds all automatable parameters. None means 'inherit from parent'."""
    # Color
    dim: Optional[float] = None
    r: Optional[float] = None
    g: Optional[float] = None
    b: Optional[float] = None
    w: Optional[float] = None

    # Spatial
    effect_width: Optional[float] = None
    x_position: Optional[float] = None

    # Envelope (Center)
    atk_c: Optional[float] = None
    dec_c: Optional[float] = None
    sus_c: Optional[float] = None
    rel_c: Optional[float] = None

    # Envelope (Edge)
    atk_e: Optional[float] = None
    dec_e: Optional[float] = None
    sus_e: Optional[float] = None
    rel_e: Optional[float] = None

    # FX
    glitch_digi: Optional[float] = None
    glitch_ana: Optional[float] = None
    overdrive: Optional[float] = None
    knee: Optional[float] = None
    eq_tilt: Optional[float] = None


def resolve_params(clip: 'Clip', subtrack: 'SubTrack', track: 'Track') -> ParameterSet:
    """
    The core cascade logic. Walks up the hierarchy: Clip -> SubTrack -> Track.
    Returns a fully hydrated ParameterSet for the rendering engine.
    """
    resolved = ParameterSet()

    # Iterate through every field defined in the ParameterSet
    for f in fields(ParameterSet):
        attr_name = f.name

        # 1. Check Clip Level (Highest Priority)
        val = getattr(clip.params, attr_name)

        # 2. Check SubTrack Level
        if val is None:
            val = getattr(subtrack.params, attr_name)

        # 3. Check Track Level (Base Default)
        if val is None:
            val = getattr(track.params, attr_name)

        # Set the winning value
        setattr(resolved, attr_name, val)

    return resolved


# ---------------------------------------------------------
# 2. TIMELINE HIERARCHY
# ---------------------------------------------------------

@dataclass
class VirtualPixel:
    x: float = 0.5  # 0.0 to 1.0 on the abstract axis
    width: float = 0.1  # Width of the pixel segment


@dataclass
class Clip:
    start: float  # Start time in seconds
    duration: float  # Duration in seconds
    params: ParameterSet = field(default_factory=ParameterSet)
    pixels: List[VirtualPixel] = field(default_factory=lambda: [VirtualPixel()])


@dataclass
class SubTrack:
    pitch: float = 60.0  # Default to middle C (MIDI 60)
    pitch_ratio: float = 0.5  # 0.0 (lowest note on track) to 1.0 (highest)
    params: ParameterSet = field(default_factory=ParameterSet)
    clips: List[Clip] = field(default_factory=list)


@dataclass
class Track:
    name: str = "New Track"
    blending_mode: str = "Add"  # "Overwrite", "Add", "Multiply"
    opacity: float = 1.0
    fixture_ids: List[str] = field(default_factory=list)
    params: ParameterSet = field(default_factory=ParameterSet)
    sub_tracks: List[SubTrack] = field(default_factory=list)


# ---------------------------------------------------------
# 3. PROJECT & CONFIGURATION
# ---------------------------------------------------------

@dataclass
class AudioReference:
    file_path: str = ""
    sample_rate: int = 44100


@dataclass
class SpatialSegment:
    fixture_id: str
    x_start: float = 0.0
    x_end: float = 1.0
    flip: bool = False


@dataclass
class OutputConfig:
    # Retain your existing Art-Net/sACN network settings here
    universe: int = 1
    protocol: str = "sACN"
    target_ip: str = "127.0.0.1"


@dataclass
class Project:
    name: str = "Untitled Titan Project"
    audio: AudioReference = field(default_factory=AudioReference)
    spatial_map: List[SpatialSegment] = field(default_factory=list)
    output_config: OutputConfig = field(default_factory=OutputConfig)
    tracks: List[Track] = field(default_factory=list)

    # --- Serialization Methods ---

    def save_to_file(self, filepath: str):
        """Serializes the entire project state to a JSON file."""
        with open(filepath, 'w') as f:
            json.dump(asdict(self), f, indent=4)

    @classmethod
    def load_from_file(cls, filepath: str) -> 'Project':
        """Deserializes a JSON file back into the nested dataclass objects."""
        with open(filepath, 'r') as f:
            data = json.load(f)

        # Rebuild hierarchy from nested dictionaries
        project = cls(
            name=data.get('name', 'Untitled'),
            audio=AudioReference(**data.get('audio', {})),
            output_config=OutputConfig(**data.get('output_config', {})),
            spatial_map=[SpatialSegment(**seg) for seg in data.get('spatial_map', [])]
        )

        # Rebuild Tracks, SubTracks, Clips, and Params
        for t_data in data.get('tracks', []):
            track = Track(
                name=t_data.get('name', ''),
                blending_mode=t_data.get('blending_mode', 'Add'),
                opacity=t_data.get('opacity', 1.0),
                fixture_ids=t_data.get('fixture_ids', []),
                params=ParameterSet(**t_data.get('params', {}))
            )

            for st_data in t_data.get('sub_tracks', []):
                subtrack = SubTrack(
                    pitch=st_data.get('pitch', 60.0),
                    pitch_ratio=st_data.get('pitch_ratio', 0.5),
                    params=ParameterSet(**st_data.get('params', {}))
                )

                for c_data in st_data.get('clips', []):
                    clip = Clip(
                        start=c_data.get('start', 0.0),
                        duration=c_data.get('duration', 1.0),
                        params=ParameterSet(**c_data.get('params', {})),
                        pixels=[VirtualPixel(**p) for p in c_data.get('pixels', [])]
                    )
                    subtrack.clips.append(clip)
                track.sub_tracks.append(subtrack)
            project.tracks.append(track)

        return project