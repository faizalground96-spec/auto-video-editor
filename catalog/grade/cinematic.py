"""grade.cinematic — kontras + teal/orange ringan + vignette halus."""
from app.schema import EffectContext, EffectOutput

META = {
    "id": "grade.cinematic",
    "category": "grade",
    "status": "stable",
    "version": 1,
    "description": "Sinematik: kontras naik, saturasi hangat, bayangan "
                   "sedikit teal, highlight sedikit oranye, vignette halus.",
    "good_for": ["cinematic", "serious", "storytelling"],
    "avoid_for": ["vlog"],
    "params": {
        "strength": {"type": "float", "default": 0.7, "min": 0.0,
                     "max": 1.0},
    },
    "aspects": ["9:16", "16:9", "1:1", "4:5"],
    "max_per_10s": 999,
    "strong": False,
    "min_gap": 0.0,
    "conflicts_with": ["grade.clean_bright", "grade.warm_pop"],
    "requires": {"assets": [], "face": False},
    "sfx": None,
}


def build(ctx: EffectContext, at, params: dict) -> EffectOutput:
    s = params["strength"]
    filt = (
        f"eq=contrast={1 + 0.10 * s:.3f}:saturation={1 + 0.12 * s:.3f},"
        f"colorbalance=rs={-0.05 * s:.3f}:bs={0.08 * s:.3f}:"
        f"bm={0.03 * s:.3f}:rh={0.07 * s:.3f}:bh={-0.06 * s:.3f},"
        f"vignette=angle=PI/5"
    )
    return EffectOutput(video_filters=[filt])
