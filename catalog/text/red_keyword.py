"""text.red_keyword — caption statis, kata kunci merah.

Tanpa animasi (seperti clean_caption), tetapi kata pada emphasis_idx
tampil merah. Untuk penekanan yang tenang namun tegas.
"""
from app.schema import EffectContext, EffectOutput
from app.subtitles import RED, chunk_captions, emphasis_set, segment_words

META = {
    "id": "text.red_keyword",
    "category": "text",
    "status": "stable",
    "version": 1,
    "description": "Caption statis dua baris; kata kunci merah.",
    "good_for": ["serious", "education", "authority"],
    "avoid_for": ["high_energy"],
    "params": {
        "emphasis_idx": {"type": "list", "default": [],
                         "desc": "indeks kata (words.json) yang merah"},
    },
    "aspects": ["9:16", "16:9", "1:1", "4:5"],
    "max_per_10s": 999,
    "strong": False,
    "min_gap": 0.0,
    "conflicts_with": ["text.clean_caption", "text.pop_in_word",
                       "text.karaoke_highlight", "text.typewriter"],
    "requires": {"assets": [], "face": False},
    "sfx": None,
}


def build(ctx: EffectContext, at, params: dict) -> EffectOutput:
    words = segment_words(ctx)
    if not words:
        return EffectOutput()
    emph = emphasis_set(params)
    events = []
    for cap in chunk_captions(words, ctx.canvas, ctx.config):
        # warnai per kata, pertahankan struktur 2 baris
        wmap = {w.get("i"): w for w in cap["words"]}
        lines = []
        for idxs in cap["line_words"]:
            parts = []
            for ii in idxs:
                w = wmap.get(ii)
                if w is None:
                    continue
                txt = w["word"].strip()
                if ii in emph:
                    txt = f"{{\\c{RED}}}{txt}{{\\r}}"
                parts.append(txt)
            lines.append(" ".join(parts))
        if not lines:
            continue
        events.append({"start": cap["start"], "end": cap["end"],
                       "text": "\\N".join(lines), "style": "Caption"})
    return EffectOutput(ass_events=events)
