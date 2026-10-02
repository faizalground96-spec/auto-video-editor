"""reframe.smart_crop — potong mengikuti wajah/subjek.

KONTRAK (seperti blur_fill): satu string filter segmen berlabel lengkap,
memetakan [vbase] -> [vref]. Kurva dihitung global oleh app.reframe
(deadzone + peredam + batas kecepatan), lalu diiris per segmen dan
diungkapkan sebagai ekspresi `t` lokal di filter crop (disederhanakan
dengan RDP). Bila kurva None (wajah tak terdeteksi / terlalu lebar),
renderer jatuh ke blur_fill sebelum memanggil efek ini.
"""
from app.reframe import curve_to_crop_expr
from app.schema import EffectContext, EffectOutput

META = {
    "id": "reframe.smart_crop",
    "category": "reframe",
    "status": "stable",
    "version": 1,
    "description": "Potong mengikuti wajah/subjek utama dengan pelacakan "
                   "yang dihaluskan (deadzone, tanpa getar). Mengisi penuh "
                   "bingkai. Cocok horizontal -> vertikal satu pembicara.",
    "good_for": ["single_speaker", "talking_head"],
    "avoid_for": ["many_people", "onscreen_text", "slides"],
    "params": {},
    "aspects": ["9:16", "16:9", "1:1", "4:5"],
    "max_per_10s": 999,
    "strong": False,
    "min_gap": 0.0,
    "conflicts_with": ["reframe.blur_fill", "reframe.fit_letterbox"],
    "requires": {"assets": [], "face": False},
    "sfx": None,
}


def build(ctx: EffectContext, at, params: dict) -> EffectOutput:
    curve = ctx.smart_crop_curve
    if not curve:
        raise ValueError("smart_crop butuh kurva (wajah tak terdeteksi?)")
    x_expr, y_expr = curve_to_crop_expr(curve, ctx.seg_start, ctx.seg_end)
    cw, ch = int(curve["crop_w"]), int(curve["crop_h"])
    seg = (f"[vbase]crop=w={cw}:h={ch}:x='{x_expr}':y='{y_expr}',"
           f"scale={ctx.canvas.width}:{ctx.canvas.height}"
           f":flags=lanczos[vref]")
    return EffectOutput(video_filters=[seg])
