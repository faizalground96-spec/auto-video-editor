"""text.poster_keyword — kata kunci GEDE gaya poster 3D + pop.

Untuk gaya kinetic typography: kata kunci tampil besar di tengah layar
dengan efek 3D (outline tebal + bayangan), animasi pop/scale saat masuk.
Warna: krem/marun/hitam sesuai parameter.

Berbeda dari pop_in_word (caption kecil ikut ucapan), ini untuk
kata kunci pilihan yang jadi elemen visual utama.
"""
from app.schema import EffectContext, EffectOutput
from app.subtitles import segment_words

META = {
    "id": "text.poster_keyword",
    "category": "text",
    "status": "stable",
    "version": 1,
    "description": "Kata kunci besar gaya poster 3D (outline+shadow) "
                   "dengan animasi pop; untuk kinetic typography.",
    "good_for": ["energetic", "social_media", "hook", "education",
                 "promo"],
    "avoid_for": ["calm", "serious"],
    "params": {
        "keywords": {"type": "list", "default": [],
                     "desc": "kata kunci (teks) yang ditampilkan besar; "
                             "bila kosong, pakai 3 kata terpanjang"},
        "color": {"type": "str", "default": "cream",
                  "desc": "cream/maroon/black"},
        "position": {"type": "str", "default": "center",
                     "desc": "center/top"},
    },
    "aspects": ["9:16", "16:9", "1:1", "4:5"],
    "max_per_10s": 5,
    "strong": True,
    "min_gap": 1.5,
    "conflicts_with": [],
    "requires": {"assets": [], "face": False},
    "sfx": "pop",
}

# warna ASS: &HAABBGGRR
_COLORS = {
    "cream": r"{\c&H1A1A1A&\3c&H1A1A1A&}",   # teks gelap di atas krem
    "maroon": r"{\c&H2A2A8C&\3c&H1A1A1A&}",  # merah marun
    "black": r"{\c&HE8E0D0&\3c&H1A1A1A&}",   # krem di atas hitam
    "white": r"{\c&HFFFFFF&\3c&H1A1A1A&}",
}


def build(ctx: EffectContext, at, params: dict) -> EffectOutput:
    words = segment_words(ctx)
    seg_start = ctx.seg_start
    seg_end = ctx.seg_end

    keywords = list(params.get("keywords") or [])
    if not keywords and words:
        # fallback: 3 kata terpanjang di segmen
        cands = sorted(set(w.get("word", "").strip() for w in words
                           if len(w.get("word", "").strip()) > 4),
                       key=len, reverse=True)[:3]
        keywords = cands
    if not keywords:
        return EffectOutput()

    color = params.get("color", "cream")
    ctag = _COLORS.get(color, _COLORS["cream"])
    pos = params.get("position", "center")
    # posisi: tengah (atau atas)
    if pos == "top":
        postag = r"{\an8\pos(540,420)}"
    else:
        postag = r"{\an5\pos(540,900)}"

    # bagi durasi segmen untuk tiap keyword
    dur = max(seg_end - seg_start, 1.0)
    slot = dur / len(keywords)
    events = []
    for i, kw in enumerate(keywords):
        ks = seg_start + i * slot
        ke = ks + slot * 0.95
        # animasi pop: scale 50% -> 110% -> 100% dalam 300ms
        pop = (r"{\fscx50\fscy50\t(0,150,\fscx110\fscy110)"
               r"\t(150,300,\fscx100\fscy100)}")
        # 3D: outline tebal (4px) + shadow dalam (2px)
        style3d = r"{\bord4\shad2}"
        text = (f"{postag}{ctag}{style3d}{pop}"
                f"{kw.upper()}")
        events.append({
            "start": round(ks, 3), "end": round(ke, 3),
            "text": text,
            "style": "PosterBig",
        })
    return EffectOutput(ass_events=events)
