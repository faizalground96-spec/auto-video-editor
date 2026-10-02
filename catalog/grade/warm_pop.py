"""grade.warm_pop — hangat dan hidup, cocok untuk vlog."""
from app.schema import EffectContext, EffectOutput

META = {
    "id": "grade.warm_pop",
    "category": "grade",
    "status": "stable",
    "version": 1,
    "description": "Hangat: saturasi & kecerahan naik sedikit, tone "
                   "kekuningan yang bersahabat.",
    "good_for": ["vlog", "casual", "energetic"],
    "avoid_for": ["serious", "cinematic"],
    "params": {
        "strength": {"type": "float", "default": 0.7, "min": 0.0,
                     "max": 1.0},
    },
    "aspects": ["9:16", "16:9", "1:1", "4:5"],
    "max_per_10s": 999,
    "strong": False,
    "min_gap": 0.0,
    "conflicts_with": ["grade.clean_bright", "grade.cinematic"],
    "requires": {"assets": [], "face": False},
    "sfx": None,
}


def build(ctx: EffectContext, at, params: dict) -> EffectOutput:
    s = params["strength"]
    filt = (
        f"eq=contrast={1 + 0.05 * s:.3f}:saturation={1 + 0.22 * s:.3f}:"
        f"brightness={0.02 * s:.3f},"
        f"colorbalance=rs={0.09 * s:.3f}:gs={0.04 * s:.3f}:"
        f"rm={0.05 * s:.3f}:rh={0.07 * s:.3f}"
    )
    return EffectOutput(video_filters=[filt])
