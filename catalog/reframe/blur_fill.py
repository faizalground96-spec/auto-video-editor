"""reframe.blur_fill — video utuh di tengah, latar versi blur dirinya.

KONTRAK: efek kategori 'reframe' mengembalikan SATU string filter yang
merupakan segmen berlabel lengkap, memetakan [vbase] -> [vref]
(label internal bebas). Renderer mendelegasikan mode reframe ke sini.
"""
from app.schema import EffectContext, EffectOutput

META = {
    "id": "reframe.blur_fill",
    "category": "reframe",
    "status": "stable",
    "version": 1,
    "description": "Video asli tampil utuh di tengah; latarnya versi blur "
                   "dari video itu sendiri yang digelapkan sedikit. Aman "
                   "untuk slide/teks/banyak orang.",
    "good_for": ["slides", "many_people", "onscreen_text"],
    "avoid_for": [],
    "params": {
        "blur_sigma": {"type": "float", "min": 4.0, "max": 60.0,
                       "default": 24.0},
        "darken": {"type": "float", "min": 0.0, "max": 0.8,
                   "default": 0.35},
    },
    "aspects": ["9:16", "16:9", "1:1", "4:5"],
    "max_per_10s": 999,
    "strong": False,
    "min_gap": 0.0,
    "conflicts_with": ["reframe.smart_crop", "reframe.fit_letterbox"],
    "requires": {"assets": [], "face": False},
    "sfx": None,
}


def build(ctx: EffectContext, at, params: dict) -> EffectOutput:
    W, H = ctx.canvas.width, ctx.canvas.height
    sig = params["blur_sigma"]
    dark = params["darken"]
    # Latar: penuhi kanvas -> kecilkan 1/8 -> blur (cepat & halus) ->
    # besarkan lagi -> gelapkan sedikit. Depan: muat utuh, tempel tengah.
    seg = (
        "[vbase]split=2[vb1][vb2];"
        f"[vb1]scale={W}:{H}:force_original_aspect_ratio=increase,"
        f"crop={W}:{H},scale=iw/8:ih/8,gblur=sigma={sig:.1f},"
        f"scale={W}:{H},eq=brightness=-{dark:.2f}[vbg];"
        f"[vb2]scale={W}:{H}:force_original_aspect_ratio=decrease[vfg];"
        f"[vbg][vfg]overlay=(W-w)/2:(H-h)/2[vref]"
    )
    return EffectOutput(video_filters=[seg])
