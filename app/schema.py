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
    type: Literal["float", "int", "bool", "str", "choice", "list"]
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
    status: Literal["stable", "beta", "experimental", "disabled"] = "stable"
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
    requires_at: bool = False  # True bila build() butuh at (batas/waktu)
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
    # Rentang segmen (waktu absolut sumber) — diisi renderer per chunk.
    # Efek berbasis waktu memakai waktu LOKAL (t=0 di awal segmen).
    seg_start: float = 0.0
    seg_end: float = 0.0
    # Kurva smart_crop global (dari app.reframe), diisi renderer bila ada.
    smart_crop_curve: Optional[Any] = None


@dataclass
class EffectOutput:
    """Dikembalikan build(): potongan filter & event untuk renderer."""
    video_filters: list[str] = field(default_factory=list)
    ass_events: list[dict] = field(default_factory=list)
    # File input tambahan (path absolut). Di filter, rujuk sebagai
    # [INPUT0], [INPUT1], ... (indeks ke list ini); renderer mengganti
    # dengan label [1:v], [2:v], ... sesuai urutan global.
    extra_inputs: list[str] = field(default_factory=list)
    sfx_cues: list[dict] = field(default_factory=list)
    # True bila efek butuh akses video sumber mentah (selain [CUR]).
    # Di filter, pakai placeholder [VSRC]; renderer mengganti dengan
    # label salinan sumber. (Satu [VSRC] per efek; split sendiri bila
    # butuh >1.)
    needs_source: bool = False


# ---------------------------------------------------------------------------
# EDL (Tahap 3: minimal; Tahap 6: analysis, emphasis_words, closing, seed)
# ---------------------------------------------------------------------------
class ReframeSpec(BaseModel):
    mode: str = "none"             # none | smart_crop | blur_fill | fit_letterbox
    why: str = ""


class CanvasSpec(BaseModel):
    aspect: str = "auto"
    reframe: ReframeSpec = Field(default_factory=ReframeSpec)
    # Tahap 6 (opsional; diisi validator bila kosong):
    width: Optional[int] = None
    height: Optional[int] = None
    fps: Optional[float] = None
    source_orientation: Optional[str] = None

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
    intensity: str = "medium"      # calm | medium | aggressive
    why: str = ""


class SegmentEffect(BaseModel):
    id: str
    at: Optional[float] = None
    params: dict[str, Any] = Field(default_factory=dict)


class Segment(BaseModel):
    start: float = 0.0
    end: float = 0.0
    role: str = "body"             # hook | body | puncak | penutup | ...
    effects: list[SegmentEffect] = Field(default_factory=list)
    why: str = ""


class AnalysisInfo(BaseModel):
    """Hasil analisis Gemini atas video (deskriptif, bukan perintah render)."""
    topic: str = ""
    genre: str = ""
    mood: str = ""
    energy: str = "medium"         # low | medium | high
    speech_pace: str = ""
    face_box_hint: Optional[dict[str, float]] = None  # x,y,w,h relatif
    important_onscreen_text: bool = False


class EmphasisWord(BaseModel):
    """Kata penekanan: idx -> words.json (waktu diisi validator)."""
    idx: int
    word: str = ""
    start: float = 0.0
    end: float = 0.0


class ClosingSpec(BaseModel):
    id: str = "closing.title_card"
    text: str = ""
    start: float = 0.0


class Edl(BaseModel):
    schema_version: int = 2
    canvas: CanvasSpec = Field(default_factory=CanvasSpec)
    analysis: AnalysisInfo = Field(default_factory=AnalysisInfo)
    global_: GlobalSpec = Field(default_factory=GlobalSpec, alias="global")
    emphasis_words: list[EmphasisWord] = Field(default_factory=list)
    segments: list[Segment] = Field(default_factory=list)
    closing: Optional[ClosingSpec] = None
    seed: Optional[int] = None

    model_config = {"populate_by_name": True}
