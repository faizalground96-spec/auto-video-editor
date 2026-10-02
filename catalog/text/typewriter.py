"""text.typewriter — kata diketik berurutan dengan kursor.

Seperti pop_in_word, tapi dengan kursor blok di ujung kata aktif dan
tanpa fade. Di akhir kalimat, kursor berkedip sebentar (event tambahan).
"""
from app.schema import EffectContext, EffectOutput
from app.subtitles import chunk_captions, segment_words

CURSOR = "{\\c&H0000C8FF&}▌{\\r}"

META = {
    "id": "text.typewriter",
    "category": "text",
    "status": "stable",
    "version": 1,
    "description": "Efek mesin ketik: kata muncul berurutan dengan kursor.",
    "good_for": ["storytelling", "hook"],
    "avoid_for": ["calm"],
    "params": {},
    "aspects": ["9:16", "16:9", "1:1", "4:5"],
    "max_per_10s": 999,
    "strong": False,
    "min_gap": 0.0,
    "conflicts_with": ["text.clean_caption", "text.pop_in_word",
                       "text.karaoke_highlight", "text.red_keyword"],
    "requires": {"assets": [], "face": False},
    "sfx": None,
}


def build(ctx: EffectContext, at, params: dict) -> EffectOutput:
    words = segment_words(ctx)
    if not words:
        return EffectOutput()
    events = []
    for cap in chunk_captions(words, ctx.canvas, ctx.config):
        cwords = cap["words"]
        if not cwords:
            continue
        line_of = {}
        for li, idxs in enumerate(cap["line_words"]):
            for ii in idxs:
                line_of[ii] = li

        def _text(n):
            chunks, cur, prev = [], [], 0
            for j, x in enumerate(cwords[:n]):
                li = line_of.get(x.get("i", j), 0)
                if li > prev:
                    chunks.append(" ".join(cur))
                    cur, prev = [], li
                cur.append(x["word"].strip())
            chunks.append(" ".join(cur))
            return "\\N".join(chunks)

        for i, w in enumerate(cwords):
            start = w["start"]
            end = (cwords[i + 1]["start"] if i + 1 < len(cwords)
                   else cap["end"])
            events.append({"start": start, "end": end,
                           "text": _text(i + 1) + CURSOR, "style": "Caption"})
        # akhir kalimat: kursor berkedip 0,4 dtk (dua event selang-seling)
        full = _text(len(cwords))
        events.append({"start": cap["end"], "end": cap["end"] + 0.2,
                       "text": full, "style": "Caption"})
        events.append({"start": cap["end"] + 0.2, "end": cap["end"] + 0.4,
                       "text": full + CURSOR, "style": "Caption"})
    return EffectOutput(ass_events=events)
