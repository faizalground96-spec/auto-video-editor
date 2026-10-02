"""camera.whip_pan — simulasi whip pan di titik cut.

Crop bergerak cepat menyapu horizontal + blur ringan dalam jendela
`duration` di sekitar `at` (waktu lokal segmen). Untuk transisi antar
topik yang energetik.
"""
from app.schema import EffectContext, EffectOutput

META = {
    "id": "camera.whip_pan",
    "category": "camera",
    "status": "stable",
    "version": 1,
    "description": "Sapuan kamera cepat + blur di momen cut; energi tinggi.",
    "good_for": ["energetic", "transition", "hook"],
    "avoid_for": ["calm", "serious"],
    "params": {
        "duration": {"type": "float", "default": 0.35, "min": 0.15,
                     "max": 0.8},
        "direction": {"type": "str", "default": "right",
                      "options": ["left", "right"]},
    },
    "aspects": ["9:16", "16:9", "1:1", "4:5"],
    "max_per_10s": 3,
    "strong": True,
    "min_gap": 1.0,
    "conflicts_with": ["camera.punch_in", "camera.slow_zoom"],
    "requires": {"assets": [], "face": False},
    "sfx": None,
}


def build(ctx: EffectContext, at, params: dict) -> EffectOutput:
    if at is None:
        raise ValueError("camera.whip_pan butuh 'at'")
    W, H = ctx.canvas.width, ctx.canvas.height
    d = params["duration"]
    sgn = 1 if params.get("direction", "right") == "right" else -1
    a0, a1 = at - d / 2, at + d / 2
    # sapuan: x bergerak -A -> +A mengikuti sin (cepat di tengah)
    A = f"({W}*0.06)"
    sweep = (f"{sgn}*{A}*sin(PI*(t-{a0:.3f})/{d:.3f})"
             f"*between(t,{a0:.3f},{a1:.3f})")
    filt = (
        f"scale=w='{W}*1.15':h='{H}*1.15':eval=frame,"
        f"crop=w={W}:h={H}:x='(in_w-{W})/2+({sweep})':y='(in_h-{H})/2',"
        f"gblur=sigma=4:enable='between(t,{a0:.3f},{a1:.3f})'"
    )
    return EffectOutput(video_filters=[filt])
