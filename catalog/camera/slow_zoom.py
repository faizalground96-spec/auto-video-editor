"""camera.slow_zoom — zoom lambat sepanjang segmen.

Skala bergerak linear 1.0 -> `factor` selama durasi segmen (waktu lokal).
Implementasi via scale+crop eval=frame (seperti punch_in), bukan zoompan.
"""
from app.schema import EffectContext, EffectOutput

META = {
    "id": "camera.slow_zoom",
    "category": "camera",
    "status": "stable",
    "version": 1,
    "description": "Zoom masuk perlahan sepanjang segmen; dramatis & halus.",
    "good_for": ["serious", "storytelling", "cinematic"],
    "avoid_for": ["high_energy"],
    "params": {
        "factor": {"type": "float", "default": 1.15, "min": 1.02,
                   "max": 1.5, "desc": "skala akhir"},
    },
    "aspects": ["9:16", "16:9", "1:1", "4:5"],
    "max_per_10s": 2,
    "strong": False,
    "min_gap": 2.0,
    "conflicts_with": ["camera.punch_in", "camera.whip_pan"],
    "requires": {"assets": [], "face": False},
    "sfx": None,
}


def build(ctx: EffectContext, at, params: dict) -> EffectOutput:
    W, H = ctx.canvas.width, ctx.canvas.height
    f = params["factor"]
    dur = max(ctx.seg_end - ctx.seg_start, 0.1)
    # t lokal 0..dur -> zoom 1 -> f
    z = f"(1+({f:.3f}-1)*t/{dur:.3f})"
    filt = (f"scale=w='{W}*{z}':h='{H}*{z}':eval=frame,"
            f"crop=w={W}:h={H}:x='(in_w-{W})/2':y='(in_h-{H})/2'")
    return EffectOutput(video_filters=[filt])
