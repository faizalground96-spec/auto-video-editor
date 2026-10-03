"""overlay.cta_button — tombol CTA gaya sungguhan di akhir video.

Teks "KLIK" + tombol "PELAJARI SEKARANG" dengan efek menyala (glow).
Untuk closing video edukasi/jualan kursus.
"""
from app.schema import EffectContext, EffectOutput

META = {
    "id": "overlay.cta_button",
    "category": "overlay",
    "status": "stable",
    "version": 1,
    "description": "Tombol CTA menyala di akhir video (gaya tombol asli).",
    "good_for": ["promo", "education", "social_media"],
    "avoid_for": ["cinematic", "serious"],
    "params": {
        "label": {"type": "str", "default": "PELAJARI SEKARANG"},
        "header": {"type": "str", "default": "KLIK"},
    },
    "aspects": ["9:16", "16:9", "1:1", "4:5"],
    "max_per_10s": 1,
    "strong": True,
    "min_gap": 5.0,
    "conflicts_with": [],
    "requires": {"assets": [], "face": False},
    "sfx": "pop",
}


def build(ctx: EffectContext, at, params: dict) -> EffectOutput:
    s, e = ctx.seg_start, ctx.seg_end
    label = params.get("label", "PELAJARI SEKARANG")
    header = params.get("header", "KLIK")
    # header KLIK besar di atas
    ev1 = {
        "start": s, "end": e,
        "text": (r"{\an5\pos(540,700)\c&HFFFFFF&\3c&H2A2A8C&\bord3\shad0}"
                 r"{\fscx150\fscy150}" + header),
        "style": "PosterBig",
    }
    # tombol: kotak merah dengan teks putih, efek glow via bord+blur
    # pakai \p untuk gambar kotak
    btn_y = 950
    ev2 = {
        "start": s, "end": e,
        "text": (
            r"{\an5\pos(540,%d)}" % btn_y +
            r"{\p1\c&H2A2A8C&\3c&H2A2A8C&}m -220 -45 l 220 -45 l 220 45 "
            r"l -220 45{\p0}" +
            r"{\an5\pos(540,%d)\c&HFFFFFF&\bord0}" % btn_y +
            r"{\fscx90\fscy90\b1}" + label
        ),
        "style": "PosterBig",
    }
    # animasi pulse: scale 100 -> 105 berulang
    # (disederhanakan: fade in)
    for ev in (ev1, ev2):
        ev["text"] = r"{\fad(200,0)}" + ev["text"]
    return EffectOutput(ass_events=[ev1, ev2])
