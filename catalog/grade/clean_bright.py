"""grade.clean_bright — terang dan bersih."""
from app.schema import EffectContext, EffectOutput

META = {
    "id": "grade.clean_bright",
    "category": "grade",
    "status": "stable",
    "version": 1,
    "description": "Grade terang dan bersih, cocok untuk edukasi dan vlog. "
                   "Kekuatan bisa diatur 0-1.",
    "good_for": ["education", "vlog", "calm"],
    "avoid_for": ["cinematic", "sad", "dramatic"],
    "params": {
        "strength": {"type": "float", "min": 0.0, "max": 1.0,
                     "default": 0.6},
    },
    "aspects": ["9:16", "16:9", "1:1", "4:5"],
    "max_per_10s": 999,   # grade dasar, bukan efek kuat
    "strong": False,
    "min_gap": 0.0,
    "conflicts_with": ["grade.teal_orange", "grade.warm_soft",
                       "grade.bw_contrast"],
    "requires": {"assets": [], "face": False},
    "sfx": None,
}


def build(ctx: EffectContext, at, params: dict) -> EffectOutput:
    s = params["strength"]
    filt = (f"eq=brightness={0.08 * s:.3f}:contrast={1 + 0.08 * s:.3f}"
            f":saturation={1 + 0.15 * s:.3f}")
    return EffectOutput(video_filters=[filt])
