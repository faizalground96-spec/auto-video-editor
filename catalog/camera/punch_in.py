"""camera.punch_in — zoom kecil sesaat pada kata penting lalu kembali."""
from app.schema import EffectContext, EffectOutput

META = {
    "id": "camera.punch_in",
    "category": "camera",
    "status": "stable",
    "version": 1,
    "description": "Zoom kecil sesaat (±0,3 detik) pada momen penekanan lalu "
                   "kembali normal. Menarik perhatian tanpa mengganggu.",
    "good_for": ["emphasis", "hook"],
    "avoid_for": ["calm"],
    "params": {
        "scale": {"type": "float", "min": 1.05, "max": 1.30,
                  "default": 1.12},
        "duration": {"type": "float", "min": 0.2, "max": 1.0,
                     "default": 0.6},
    },
    "aspects": ["9:16", "16:9", "1:1", "4:5"],
    "max_per_10s": 3,
    "strong": True,
    "min_gap": 1.0,
    "conflicts_with": ["camera.crash_zoom", "camera.slow_push"],
    "requires": {"assets": [], "face": False},
    "sfx": "pop",
}


def build(ctx: EffectContext, at, params: dict) -> EffectOutput:
    if at is None:
        raise ValueError("camera.punch_in butuh 'at'")
    W, H = ctx.canvas.width, ctx.canvas.height
    s = params["scale"]
    d = params["duration"]
    a0, a1 = at - d / 2, at + d / 2
    # tonjolan halus sin^2: 0 -> 1 -> 0 dalam jendela d detik
    bump = (f"pow(sin(PI*(t-{a0:.3f})/{d:.3f}),2)"
            f"*between(t,{a0:.3f},{a1:.3f})")
    z = f"(1+({s:.3f}-1)*{bump})"
    # scale eval=frame (halus, tanpa getar zoompan); crop x/y otomatis per frame
    filt = (f"scale=w='{W}*{z}':h='{H}*{z}':eval=frame,"
            f"crop=w={W}:h={H}:x='(in_w-{W})/2':y='(in_h-{H})/2'")
    return EffectOutput(video_filters=[filt])
