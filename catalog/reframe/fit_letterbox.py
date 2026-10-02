"""reframe.fit_letterbox — video utuh dengan bar polos (cadangan)."""
from app.schema import EffectContext, EffectOutput

META = {
    "id": "reframe.fit_letterbox",
    "category": "reframe",
    "status": "stable",
    "version": 1,
    "description": "Video tampil utuh dengan bar polos di sisi kosong. "
                   "Cadangan bila crop maupun blur tidak cocok.",
    "good_for": ["slides"],
    "avoid_for": [],
    "params": {},
    "aspects": ["9:16", "16:9", "1:1", "4:5"],
    "max_per_10s": 999,
    "strong": False,
    "min_gap": 0.0,
    "conflicts_with": ["reframe.smart_crop", "reframe.blur_fill"],
    "requires": {"assets": [], "face": False},
    "sfx": None,
}


def build(ctx: EffectContext, at, params: dict) -> EffectOutput:
    W, H = ctx.canvas.width, ctx.canvas.height
    seg = (f"[vbase]scale={W}:{H}:force_original_aspect_ratio=decrease:"
           f"flags=lanczos,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2[vref]")
    return EffectOutput(video_filters=[seg])
