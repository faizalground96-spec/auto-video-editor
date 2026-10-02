"""transition.whip — transisi geser-cepat + blur di batas segmen.

Dipasang dua kali: direction="out" di akhir segmen keluar (at = akhir),
direction="in" di awal segmen masuk (at = awal). Tiap sisi menganimasikan
`duration` detik. Digabung, terbaca sebagai satu whip transition.

Implementasi: crop window bergerak cepat dalam batas aman (scale 1.5x
memberi ruang gerak 0.5W) + blur kuat. Crop x tak boleh negatif, jadi
gerakan dibatasi 0..0.5W.
"""
from app.schema import EffectContext, EffectOutput

META = {
    "id": "transition.whip",
    "category": "transition",
    "status": "stable",
    "version": 2,
    "description": "Transisi whip: geser cepat + blur di batas segmen.",
    "good_for": ["energetic", "social_media"],
    "avoid_for": ["calm", "serious", "cinematic"],
    "params": {
        "direction": {"type": "str", "default": "out",
                      "options": ["out", "in"],
                      "desc": "out=akhir segmen, in=awal segmen"},
        "duration": {"type": "float", "default": 0.3, "min": 0.15,
                     "max": 0.6},
        "way": {"type": "str", "default": "left",
                "options": ["left", "right"]},
    },
    "aspects": ["9:16", "16:9", "1:1", "4:5"],
    "max_per_10s": 3,
    "strong": True,
    "min_gap": 1.0,
    "conflicts_with": ["transition.zoom_blur"],
    "requires": {"assets": [], "face": False},
    "sfx": None,
}


def build(ctx: EffectContext, at, params: dict) -> EffectOutput:
    if at is None:
        raise ValueError("transition.whip butuh 'at' (batas segmen)")
    W, H = ctx.canvas.width, ctx.canvas.height
    d = params["duration"]
    direction = params["direction"]
    # arah konten: left = konten bergerak ke kiri (x crop membesar)
    sgn = 1 if params.get("way", "left") == "left" else -1
    # scale 1.5 -> x aman di [0, 0.5W]; tengah = 0.25W
    c0 = 0.25
    if direction == "out":
        a0, a1 = at - d, at
        # tengah -> tepi (keluar)
        x0, x1 = c0, c0 + sgn * 0.25
    else:
        a0, a1 = at, at + d
        # tepi -> tengah (masuk)
        x0, x1 = c0 - sgn * 0.25, c0
    prog = f"min(max((t-{a0:.3f})/{d:.3f}\\,0)\\,1)"
    x = f"{W}*({x0:.3f}+({x1:.3f}-{x0:.3f})*{prog})"
    # Catatan: di filter crop, konstanta W tak ada; substitusi angka.
    x_num = x.replace("W*", f"{W}*")
    filt = (
        f"scale=w='{W}*1.5':h='{H}*1.5':eval=frame,"
        f"crop=w={W}:h={H}:x='{x_num}':y='(in_h-{H})/2',"
        f"gblur=sigma=6:enable='between(t,{a0:.3f},{a1:.3f})'"
    )
    return EffectOutput(video_filters=[filt])
