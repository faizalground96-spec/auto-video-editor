"""overlay.progress_bar — bar progres di bawah segmen.

Garis tipis di tepi bawah safe area; lebar tumbuh 0 -> W selama segmen
(waktu lokal t). Warna & ketebalan dari param.
"""
from app.schema import EffectContext, EffectOutput

META = {
    "id": "overlay.progress_bar",
    "category": "overlay",
    "status": "stable",
    "version": 1,
    "description": "Bar progres halus di bawah; memberi rasa gerak.",
    "good_for": ["education", "storytelling"],
    "avoid_for": [],
    "params": {
        "color": {"type": "str", "default": "red",
                  "options": ["red", "white", "yellow"]},
        "thickness": {"type": "float", "default": 0.008, "min": 0.004,
                      "max": 0.02, "desc": "fraksi tinggi kanvas"},
    },
    "aspects": ["9:16", "16:9", "1:1", "4:5"],
    "max_per_10s": 999,
    "strong": False,
    "min_gap": 0.0,
    "conflicts_with": [],
    "requires": {"assets": [], "face": False},
    "sfx": None,
}

_COLORS = {"red": "0xE50914", "white": "white", "yellow": "0xFFC800"}


def build(ctx: EffectContext, at, params: dict) -> EffectOutput:
    W, H = ctx.canvas.width, ctx.canvas.height
    h = max(2, int(H * params["thickness"]))
    y = H - int(H * ctx.canvas.safe_bottom) - h - 4
    dur = max(ctx.seg_end - ctx.seg_start, 0.1)
    color = _COLORS[params["color"]]
    filt = (f"drawbox=x=0:y={y}:w='{W}*min(1\\,t/{dur:.3f})':h={h}:"
            f"c={color}:t=fill")
    return EffectOutput(video_filters=[filt])
