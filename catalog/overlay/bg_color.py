"""overlay.bg_color — ganti background jadi warna solid per segmen.

Untuk gaya kinetic typography: latar berganti krem/merun/hitam tiap
beat kalimat. Overlay full-screen di belakang video (atau menutup
penuh bila diinginkan).
"""
from app.schema import EffectContext, EffectOutput

META = {
    "id": "overlay.bg_color",
    "category": "overlay",
    "status": "stable",
    "version": 1,
    "description": "Background warna solid full-screen; ganti tiap segmen.",
    "good_for": ["energetic", "education", "promo", "social_media"],
    "avoid_for": ["cinematic", "serious"],
    "params": {
        "color": {"type": "str", "default": "cream",
                  "options": ["cream", "maroon", "black", "dark_brown"]},
        "opacity": {"type": "float", "default": 1.0, "min": 0.0,
                    "max": 1.0},
    },
    "aspects": ["9:16", "16:9", "1:1", "4:5"],
    "max_per_10s": 10,
    "strong": False,
    "min_gap": 0.0,
    "conflicts_with": [],
    "requires": {"assets": [], "face": False},
    "sfx": None,
}

_COLORS = {
    "cream": "0xF5EFE0",
    "maroon": "0x8C2A2A",
    "black": "0x0A0A0A",
    "dark_brown": "0x3A2418",
}


def build(ctx: EffectContext, at, params: dict) -> EffectOutput:
    color = _COLORS.get(params.get("color", "cream"), _COLORS["cream"])
    op = float(params.get("opacity", 1.0))
    W, H = ctx.canvas.width, ctx.canvas.height
    s, e = ctx.seg_start, ctx.seg_end
    # solid color full-screen selama segmen
    filt = (
        f"color=c={color}:s={W}x{H}:d={e - s:.3f}:r=30,"
        f"format=rgba,colorchannelmixer=aa={op}[bg];"
        f"[CUR][bg]overlay=0:0:"
        f"enable='between(t,{s:.3f},{e:.3f})'[NEXT]"
    )
    return EffectOutput(video_filters=[filt])
