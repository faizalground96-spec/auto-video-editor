"""overlay.emoji_burst — stiker PNG muncul meletup di momen kunci.

Stiker dari assets/stickers (PNG RGBA, bukan emoji font). Muncul dengan
animasi pop (skala 0 -> 1 dalam 0,12 dtk), tampil selama `duration`.
"""
from app.schema import EffectContext, EffectOutput
from app.utils import ff_filter_path

META = {
    "id": "overlay.emoji_burst",
    "category": "overlay",
    "status": "stable",
    "version": 1,
    "description": "Stiker meletup di momen kunci; playful & tegas.",
    "good_for": ["energetic", "hook", "social_media"],
    "avoid_for": ["serious", "cinematic"],
    "params": {
        "sticker": {"type": "str", "default": "burst",
                    "options": ["burst", "alert", "arrow"]},
        "pos": {"type": "str", "default": "top_right",
                "options": ["top_left", "top_right", "bottom_left",
                            "bottom_right", "center"]},
        "scale": {"type": "float", "default": 0.22, "min": 0.1, "max": 0.5,
                  "desc": "fraksi tinggi kanvas"},
        "duration": {"type": "float", "default": 0.9, "min": 0.3, "max": 3.0},
    },
    "aspects": ["9:16", "16:9", "1:1", "4:5"],
    "max_per_10s": 3,
    "strong": True,
    "min_gap": 1.0,
    "conflicts_with": [],
    "requires": {"assets": ["stickers"], "face": False},
    "sfx": None,
}

_POS = {
    "top_left": (0.06, 0.10),
    "top_right": (0.94, 0.10),
    "bottom_left": (0.06, 0.80),
    "bottom_right": (0.94, 0.80),
    "center": (0.50, 0.35),
}


def build(ctx: EffectContext, at, params: dict) -> EffectOutput:
    if at is None:
        raise ValueError("overlay.emoji_burst butuh 'at'")
    name = params["sticker"]
    p = ctx.assets_dir / "stickers" / f"{name}.png"
    if not p.is_file():
        raise FileNotFoundError(f"stiker tidak ditemukan: {p}")
    W, H = ctx.canvas.width, ctx.canvas.height
    px, py = _POS[params["pos"]]
    size = int(H * params["scale"])
    a, b = at, at + params["duration"]
    # pop: skala 0 -> 1 dalam 0,12 dtk
    pop = f"min(1,(t-{a:.3f})/0.12)"
    filt = (
        f"movie='{ff_filter_path(p)}',format=rgba,"
        f"scale=w='{size}*{pop}':h='-1':eval=frame[st];"
        f"[CUR][st]overlay="
        f"x='{px:.2f}*(W-w)':y='{py:.2f}*(H-h)':"
        f"enable='between(t,{a:.3f},{b:.3f})'[NEXT]"
    )
    return EffectOutput(video_filters=[filt])
