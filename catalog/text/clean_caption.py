"""text.clean_caption — caption sederhana dua baris, kalem, tanpa animasi."""
from app.schema import EffectContext, EffectOutput
from app.subtitles import chunk_captions

META = {
    "id": "text.clean_caption",
    "category": "text",
    "status": "stable",
    "version": 2,   # v2: chunking dipindah ke app/subtitles.py
    "description": "Caption sederhana maksimal dua baris, kalem, tanpa animasi. "
                   "Gaya teks default yang aman untuk semua video.",
    "good_for": ["calm", "education", "serious", "vlog"],
    "avoid_for": ["high_energy", "hype"],
    "params": {},
    "aspects": ["9:16", "16:9", "1:1", "4:5"],
    "max_per_10s": 999,   # gaya dasar, bukan efek kuat
    "strong": False,
    "min_gap": 0.0,
    "conflicts_with": ["text.pop_in_word", "text.karaoke_highlight",
                       "text.typewriter"],
    "requires": {"assets": [], "face": False},
    "sfx": None,
}


def build(ctx: EffectContext, at, params: dict) -> EffectOutput:
    words = ctx.words or []
    if not words:
        return EffectOutput()
    events = [
        {"start": c["start"], "end": c["end"],
         "text": "\\N".join(c["lines"]), "style": "Caption"}
        for c in chunk_captions(words, ctx.canvas, ctx.config)
    ]
    return EffectOutput(ass_events=events)
