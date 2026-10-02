"""layout.split_compare — split kiri-kanan "sebelum vs sesudah".

Dua rentang waktu sumber (left_from/to, right_from/to) tampil
berdampingan, masing-masing di-loop/dibekukan mengikuti durasi segmen.
Garis pemisah putih di tengah.
"""
from app.schema import EffectContext, EffectOutput

META = {
    "id": "layout.split_compare",
    "category": "layout",
    "status": "stable",
    "version": 1,
    "description": "Perbandingan kiri-kanan dua momen video.",
    "good_for": ["comparison", "education", "review"],
    "avoid_for": [],
    "params": {
        "left_from": {"type": "float", "default": 0.0},
        "left_to": {"type": "float", "default": 1.0},
        "right_from": {"type": "float", "default": 1.0},
        "right_to": {"type": "float", "default": 2.0},
    },
    "aspects": ["9:16", "16:9", "1:1", "4:5"],
    "max_per_10s": 1,
    "strong": True,
    "min_gap": 5.0,
    "conflicts_with": ["insert.b_roll_top", "insert.face_grid"],
    "requires": {"assets": [], "face": False},
    "sfx": None,
}


def build(ctx: EffectContext, at, params: dict) -> EffectOutput:
    W, H = ctx.canvas.width, ctx.canvas.height
    hw = int(W / 2 / 2) * 2
    dur = max(ctx.seg_end - ctx.seg_start, 0.1)
    lf, lt = params["left_from"], params["left_to"]
    rf, rt = params["right_from"], params["right_to"]
    if lt <= lf or rt <= rf:
        raise ValueError("split_compare: rentang waktu tidak valid")

    def panel(src_label, frm, to, lab):
        return (
            f"{src_label}trim=start={frm:.3f}:end={to:.3f},"
            f"setpts=PTS-STARTPTS,fps=30,setsar=1,format=yuv420p,"
            f"scale={hw}:{H}:force_original_aspect_ratio=increase,"
            f"crop={hw}:{H},"
            f"tpad=stop_mode=clone:stop_duration={dur:.2f},"
            f"trim=end={dur:.3f},setpts=PTS-STARTPTS[{lab}]"
        )

    filt = (
        "[VSRC]split=2[vsA][vsB];"
        + panel("[vsA]", lf, lt, "cmpL") + ";"
        + panel("[vsB]", rf, rt, "cmpR") + ";"
        f"[cmpL][cmpR]hstack=inputs=2,"
        f"drawbox=x={hw - 2}:y=0:w=4:h={H}:c=white:t=fill[NEXT]"
    )
    return EffectOutput(video_filters=[filt], needs_source=True)
