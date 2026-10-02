"""transition.zoom_blur — transisi zoom + blur di batas segmen.

Seperti whip: direction="out" di akhir segmen keluar, "in" di awal
segmen masuk. Zoom cepat + blur radial (gblur) dalam jendela duration.
"""
from app.schema import EffectContext, EffectOutput

META = {
    "id": "transition.zoom_blur",
    "category": "transition",
    "status": "stable",
    "version": 1,
    "description": "Transisi zoom-blur di batas segmen; dramatis.",
    "good_for": ["energetic", "cinematic", "hook"],
    "avoid_for": ["calm"],
    "params": {
        "direction": {"type": "str", "default": "out",
                      "options": ["out", "in"]},
        "duration": {"type": "float", "default": 0.3, "min": 0.15,
                     "max": 0.6},
    },
    "aspects": ["9:16", "16:9", "1:1", "4:5"],
    "max_per_10s": 3,
    "strong": True,
    "min_gap": 1.0,
    "conflicts_with": ["transition.whip"],
    "requires": {"assets": [], "face": False},
    "sfx": None,
}


def build(ctx: EffectContext, at, params: dict) -> EffectOutput:
    if at is None:
        raise ValueError("transition.zoom_blur butuh 'at' (batas segmen)")
    W, H = ctx.canvas.width, ctx.canvas.height
    d = params["duration"]
    direction = params["direction"]
    if direction == "out":
        a0, a1 = at - d, at
        # 0 -> 1 : zoom 1 -> 1.25 (dijepit di luar jendela)
        prog = f"min(max((t-{a0:.3f})/{d:.3f}\\,0)\\,1)"
        z = f"(1+0.25*{prog})"
    else:
        a0, a1 = at, at + d
        prog = f"min(max((t-{a0:.3f})/{d:.3f}\\,0)\\,1)"
        z = f"(1.25-0.25*{prog})"
    # Catatan: gblur sigma tak menerima ekspresi t di ffmpeg 8.1,
    # jadi blur konstan yang di-enable hanya dalam jendela.
    filt = (
        f"scale=w='{W}*{z}':h='{H}*{z}':eval=frame,"
        f"crop=w={W}:h={H}:x='(in_w-{W})/2':y='(in_h-{H})/2',"
        f"gblur=sigma=8:enable='between(t,{a0:.3f},{a1:.3f})'"
    )
    return EffectOutput(video_filters=[filt])
