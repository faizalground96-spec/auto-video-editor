"""insert.face_grid — grid 2-3 panel wajah dari face_track.

Tiap panel meng-crop satu wajah (mengikuti pergerakannya via ekspresi
`t` seperti smart_crop) lalu panel disusun berdampingan. Sinkron ke
segmen/kalimat tempat efek dipasang. Bila wajah kurang dari panel yang
diminta, panel menyesuaikan jumlah wajah.
"""
from app.schema import EffectContext, EffectOutput

META = {
    "id": "insert.face_grid",
    "category": "insert",
    "status": "beta",  # v1: ikuti wajah via ekspresi; uji di 4 rasio
    "version": 1,
    "description": "Grid wajah 2-3 panel yang mengikuti tiap wajah; "
                   "gaya diskusi/debat.",
    "good_for": ["discussion", "podcast", "many_people"],
    "avoid_for": ["single_speaker"],
    "params": {
        "panels": {"type": "int", "default": 2, "min": 2, "max": 3},
        "zoom": {"type": "float", "default": 2.4, "min": 1.8, "max": 3.5,
                 "desc": "pengali ukuran wajah -> panel"},
    },
    "aspects": ["9:16", "16:9", "1:1", "4:5"],
    "max_per_10s": 1,
    "strong": True,
    "min_gap": 5.0,
    "conflicts_with": ["insert.b_roll_top", "layout.split_compare",
                       "reframe.smart_crop"],
    "requires": {"assets": [], "face": True},
    "sfx": None,
}


def _nested_if(pts: list[tuple[float, float]]) -> str:
    """[(t, v)] -> ekspresi t bersarang (interpolasi linear)."""
    if len(pts) == 1:
        return f"{pts[0][1]:.2f}"
    expr = f"{pts[-1][1]:.2f}"
    for (t0, x0), (t1, x1) in zip(reversed(pts[:-1]), reversed(pts[1:])):
        if t1 - t0 < 1e-6:
            continue
        expr = (f"if(lt(t,{t1:.3f}),{x0:.2f}+({x1:.2f}-{x0:.2f})"
                f"*(t-{t0:.3f})/{t1 - t0:.3f},{expr})")
    return f"if(lt(t,{pts[0][0]:.3f}),{pts[0][1]:.2f},{expr})"


def build(ctx: EffectContext, at, params: dict) -> EffectOutput:
    track = ctx.face_track
    if not track or not track.get("samples"):
        raise ValueError("insert.face_grid butuh face_track")
    s0, s1 = ctx.seg_start, ctx.seg_end
    if s1 <= s0:
        raise ValueError("insert.face_grid harus dipasang di segmen")
    samples = [s for s in track["samples"] if s0 - 0.3 <= s["t"] <= s1 + 0.3]
    if not samples:
        raise ValueError("tak ada sampel wajah di segmen")
    W, H = ctx.canvas.width, ctx.canvas.height
    src_w, src_h = ctx.source.width, ctx.source.height
    want = int(params["panels"])
    zoom = float(params["zoom"])

    # jumlah wajah maks di segmen -> jumlah panel aktual
    n_faces = max(len(s["faces"]) for s in samples)
    n = max(1, min(want, n_faces))
    pw = int(W / n / 2) * 2  # lebar panel (genap)

    chains = []
    labels = []
    # [CUR] hanya boleh dikonsumsi sekali -> split dulu
    split_labels = "".join(f"[c{i}]" for i in range(n))
    chains.append(f"[CUR]split={n}{split_labels}")
    for i in range(n):
        pts_x, pts_y, sizes = [], [], []
        lx, ly = None, None
        for s in samples:
            faces = sorted(s["faces"], key=lambda f: f["x"])
            if len(faces) > i:
                f = faces[i]
                lx = (f["x"] + f["w"] / 2) * src_w
                ly = (f["y"] + f["h"] / 2) * src_h
                sizes.append(max(f["w"] * src_w, f["h"] * src_h))
            if lx is not None:
                pts_x.append((s["t"] - s0, lx))
                pts_y.append((s["t"] - s0, ly))
        if not pts_x:
            continue
        side = int((sum(sizes) / len(sizes) * zoom) / 2) * 2
        side = max(120, min(side, min(src_w, src_h)))
        xe = _nested_if(pts_x)
        ye = _nested_if(pts_y)
        lab = f"fp{i}"
        labels.append(lab)
        chains.append(
            f"[c{i}]crop=w={side}:h={side}:x='({xe})-{side / 2:.1f}'"
            f":y='({ye})-{side / 2:.1f}',"
            f"scale={pw}:{H}:force_original_aspect_ratio=increase,"
            f"crop={pw}:{H}[{lab}]")
    if not labels:
        raise ValueError("face_grid: tak ada wajah terlacak")
    stack = "".join(f"[{l}]" for l in labels)
    chains.append(f"{stack}hstack=inputs={len(labels)}[NEXT]")
    return EffectOutput(video_filters=[";".join(chains)])
