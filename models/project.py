import json
from dataclasses import dataclass, field, asdict, fields
from typing import List, Optional


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
    Cascade logic: Clip → SubTrack → Track. First non-None value wins.
    Returns a fully hydrated ParameterSet for the compositor.
    """
    resolved = ParameterSet()
    for f in fields(ParameterSet):
        name = f.name
        val = getattr(clip.params, name)
        if val is None:
            val = getattr(subtrack.params, name)
        if val is None:
            val = getattr(track.params, name)
        setattr(resolved, name, val)
    return resolved


# ---------------------------------------------------------
# 2. TIMELINE HIERARCHY
# ---------------------------------------------------------

@dataclass
class VirtualPixel:
    x: float = 0.5       # 0.0–1.0 on the abstract axis
    width: float = 0.1   # width of the effect blob


@dataclass
class Clip:
    start: float
    duration: float
    params: ParameterSet = field(default_factory=ParameterSet)
    pixels: List[VirtualPixel] = field(default_factory=lambda: [VirtualPixel()])


@dataclass
class SubTrack:
    pitch: float = 60.0         # MIDI note number
    pitch_ratio: float = 0.5    # 0.0 (lowest) → 1.0 (highest) in track's range
    params: ParameterSet = field(default_factory=ParameterSet)
    clips: List[Clip] = field(default_factory=list)


@dataclass
class Track:
    name: str = "New Track"
    blending_mode: str = "Add"   # "Overwrite" | "Add" | "Multiply"
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
    fixture_id: str = ""
    x_start: float = 0.0
    x_end: float = 1.0
    flip: bool = False


@dataclass
class OutputConfig:
    """Full Art-Net / sACN output configuration. Serialized inside .titanproj."""
    protocol: str = "Art-Net"           # "Art-Net" | "sACN"
    net_mode: str = "Unicast"           # "Unicast" | "Broadcast" | "Multicast"
    target_ip: str = "127.0.0.1"
    art_net: int = 0                    # Art-Net net byte (0–127)
    art_sub: int = 0                    # Art-Net subnet (0–15)
    artnet_offset: int = 1              # QLC+ "1 vs 0" universe-number compatibility shift
    sacn_priority: int = 100
    sacn_source_name: str = "Titan Engine"
    sacn_preview: bool = False
    active: bool = True


@dataclass
class Project:
    name: str = "Untitled Titan Project"
    version: int = 4
    audio: AudioReference = field(default_factory=AudioReference)
    spatial_map: List[SpatialSegment] = field(default_factory=list)
    output_config: OutputConfig = field(default_factory=OutputConfig)
    tracks: List[Track] = field(default_factory=list)

    def save_to_file(self, filepath: str):
        with open(filepath, 'w') as f:
            json.dump(asdict(self), f, indent=4)

    @classmethod
    def load_from_file(cls, filepath: str) -> 'Project':
        with open(filepath, 'r') as f:
            data = json.load(f)

        project = cls(
            name=data.get('name', 'Untitled'),
            version=data.get('version', 4),
            audio=AudioReference(**data.get('audio', {})),
            output_config=OutputConfig(**data.get('output_config', {})),
            spatial_map=[SpatialSegment(**s) for s in data.get('spatial_map', [])],
        )

        for t_data in data.get('tracks', []):
            track = Track(
                name=t_data.get('name', ''),
                blending_mode=t_data.get('blending_mode', 'Add'),
                opacity=t_data.get('opacity', 1.0),
                fixture_ids=t_data.get('fixture_ids', []),
                params=ParameterSet(**t_data.get('params', {})),
            )
            for st_data in t_data.get('sub_tracks', []):
                subtrack = SubTrack(
                    pitch=st_data.get('pitch', 60.0),
                    pitch_ratio=st_data.get('pitch_ratio', 0.5),
                    params=ParameterSet(**st_data.get('params', {})),
                )
                for c_data in st_data.get('clips', []):
                    clip = Clip(
                        start=c_data.get('start', 0.0),
                        duration=c_data.get('duration', 1.0),
                        params=ParameterSet(**c_data.get('params', {})),
                        pixels=[VirtualPixel(**p) for p in c_data.get('pixels', [])],
                    )
                    subtrack.clips.append(clip)
                track.sub_tracks.append(subtrack)
            project.tracks.append(track)

        return project
