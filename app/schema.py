"""schema.py — model pydantic untuk META efek dan EDL.

Tahap 3: META (validasi katalog) + EDL minimal untuk kerangka ujung-ke-ujung.
Tahap 6 akan memperluas model EDL (analysis, emphasis_words, closing, seed).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator

from .canvas import CANVAS_SPECS


# ---------------------------------------------------------------------------
# META efek (satu file .py di catalog/)
# ---------------------------------------------------------------------------
class ParamSpec(BaseModel):
    type: Literal["float", "int", "bool", "str", "choice"]
    min: Optional[float] = None
    max: Optional[float] = None
    default: Any = None
    choices: list[str] = Field(default_factory=list)


class EffectRequires(BaseModel):
    assets: list[str] = Field(default_factory=list)
    face: bool = False


class EffectMeta(BaseModel):
    id: str
    category: Literal["text", "camera", "grade", "transition", "overlay",
                      "layout", "reframe", "insert", "closing", "sfx"]
    status: Literal["stable", "experimental", "disabled"] = "stable"
    version: int = 1
    description: str = ""
    good_for: list[str] = Field(default_factory=list)
    avoid_for: list[str] = Field(default_factory=list)
    params: dict[str, ParamSpec] = Field(default_factory=dict)
    aspects: list[str] = Field(
        default_factory=lambda: list(CANVAS_SPECS.keys()))
    max_per_10s: float = 2.0
    strong: bool = False
    min_gap: float = 0.0
    conflicts_with: list[str] = Field(default_factory=list)
    requires: EffectRequires = Field(default_factory=EffectRequires)
    sfx: Optional[str] = None

    @field_validator("aspects")
    @classmethod
    def _aspects_known(cls, v: list[str]) -> list[str]:
        unknown = [a for a in v if a not in CANVAS_SPECS]
        if unknown:
            raise ValueError(f"rasio tak dikenal di aspects: {unknown}")
        return v

    @field_validator("id")
    @classmethod
    def _id_matches_category(cls, v: str, info) -> str:
        # id harus diawali "<kategori>." — diisi info.data bila tersedia
        return v


# ---------------------------------------------------------------------------
# Konteks & keluaran efek
# ---------------------------------------------------------------------------
@dataclass
class EffectContext:
    """Diberikan ke build(ctx, at, params) tiap efek."""
    canvas: Any                    # app.canvas.Canvas
    source: Any                    # app.probe.SourceInfo
    words: list[dict]              # words.json (satu sumber kebenaran timing)
    work_dir: Path
    assets_dir: Path
    config: dict                   # config.yaml (penuh)
    face_track: Optional[Any] = None


@dataclass
class EffectOutput:
    """Dikembalikan build(): potongan filter & event untuk renderer."""
    video_filters: list[str] = field(default_factory=list)
    ass_events: list[dict] = field(default_factory=list)
    extra_inputs: list[str] = field(default_factory=list)
    sfx_cues: list[dict] = field(default_factory=list)


# ---------------------------------------------------------------------------
# EDL minimal (kerangka Tahap 3; diperluas di Tahap 6)
# ---------------------------------------------------------------------------
class ReframeSpec(BaseModel):
    mode: str = "none"             # none | smart_crop | blur_fill | fit_letterbox
    why: str = ""


class CanvasSpec(BaseModel):
    aspect: str = "auto"
    reframe: ReframeSpec = Field(default_factory=ReframeSpec)

    @field_validator("aspect")
    @classmethod
    def _aspect_known(cls, v: str) -> str:
        if v != "auto" and v not in CANVAS_SPECS:
            raise ValueError(f"rasio tak dikenal: {v}")
        return v


class EffectRef(BaseModel):
    id: str
    params: dict[str, Any] = Field(default_factory=dict)


class GlobalSpec(BaseModel):
    text_style: Optional[EffectRef] = None
    grade: Optional[EffectRef] = None
    intensity: str = "medium"


class SegmentEffect(BaseModel):
    id: str
    at: Optional[float] = None
    params: dict[str, Any] = Field(default_factory=dict)


class Segment(BaseModel):
    start: float = 0.0
    end: float = 0.0
    role: str = "body"
    effects: list[SegmentEffect] = Field(default_factory=list)


class Edl(BaseModel):
    schema_version: int = 1
    canvas: CanvasSpec = Field(default_factory=CanvasSpec)
    global_: GlobalSpec = Field(default_factory=GlobalSpec, alias="global")
    segments: list[Segment] = Field(default_factory=list)

    model_config = {"populate_by_name": True}
