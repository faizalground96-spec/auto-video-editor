"""insert.b_roll_top — panel B-roll di atas, konten utama di bawah.

B-roll dari file `clip` (path absolut/relatif assets). Bila klip lebih
pendek dari segmen, frame terakhir dibekukan; bila lebih panjang,
dipotong. Proporsi atas: `top_ratio` dari tinggi kanvas.
"""
from pathlib import Path

from app.schema import EffectContext, EffectOutput

META = {
    "id": "insert.b_roll_top",
    "category": "insert",
    "status": "stable",
    "version": 1,
    "description": "Layar terbagi atas-bawah: B-roll di panel atas, "
                   "konten utama di bawah. Gaya Authority Disruptor.",
    "good_for": ["authority", "education", "news"],
    "avoid_for": [],
    "params": {
        "clip": {"type": "str", "default": "",
                 "desc": "path video B-roll (wajib)"},
        "top_ratio": {"type": "float", "default": 0.38, "min": 0.25,
                      "max": 0.6},
    },
    "aspects": ["9:16", "16:9", "1:1", "4:5"],
    "max_per_10s": 2,
    "strong": True,
    "min_gap": 3.0,
    "conflicts_with": ["insert.face_grid", "layout.split_compare"],
    "requires": {"assets": [], "face": False},
    "sfx": None,
}


def build(ctx: EffectContext, at, params: dict) -> EffectOutput:
    clip = params.get("clip", "")
    if not clip:
        raise ValueError("insert.b_roll_top butuh param 'clip' (path video)")
    clip_p = Path(clip)
    if not clip_p.is_absolute():
        clip_p = ctx.assets_dir / clip
    if not clip_p.is_file():
        raise FileNotFoundError(f"B-roll tidak ditemukan: {clip_p}")
    W, H = ctx.canvas.width, ctx.canvas.height
    top_h = int(H * params["top_ratio"] / 2) * 2
    bot_h = H - top_h
    dur = max(ctx.seg_end - ctx.seg_start, 0.1)
    filt = (
        f"[INPUT0]fps=30,setsar=1,scale={W}:{top_h}:"
        f"force_original_aspect_ratio=increase,crop={W}:{top_h},"
        f"tpad=stop_mode=clone:stop_duration={dur:.2f},"
        f"trim=end={dur:.3f},setpts=PTS-STARTPTS[broll];"
        f"[CUR]scale={W}:{bot_h}:force_original_aspect_ratio=increase,"
        f"crop={W}:{bot_h},setsar=1[main];"
        f"[broll][main]vstack=inputs=2[NEXT]"
    )
    return EffectOutput(video_filters=[filt],
                        extra_inputs=[str(clip_p)])
