"""text.pop_in_word — kata muncul satu per satu dengan fade cepat.

Tiap kata jadi satu Dialogue: mulai di word.start, teks = kata-kata
sebelumnya + kata baru (fade-in 60ms). Kata dalam emphasis_idx tampil
merah dan lebih besar (emphasis_scale). Teks SELALU dari words.json.
"""
from app.schema import EffectContext, EffectOutput
from app.subtitles import RED, chunk_captions, emphasis_set, segment_words

META = {
    "id": "text.pop_in_word",
    "category": "text",
    "status": "stable",
    "version": 1,
    "description": "Caption kinetik: kata muncul satu per satu mengikuti "
                   "ucapan; kata kunci bisa merah & lebih besar.",
    "good_for": ["energetic", "social_media", "hook", "news", "opinion"],
    "avoid_for": ["calm", "serious"],
    "params": {
        "emphasis_idx": {"type": "list", "default": [],
                         "desc": "indeks kata (words.json) yang ditekankan"},
        "emphasis_scale": {"type": "float", "default": 1.25, "min": 1.0,
                           "max": 2.0},
    },
    "aspects": ["9:16", "16:9", "1:1", "4:5"],
    "max_per_10s": 999,
    "strong": False,
    "min_gap": 0.0,
    "conflicts_with": ["text.clean_caption", "text.karaoke_highlight",
                       "text.typewriter", "text.red_keyword"],
    "requires": {"assets": [], "face": False},
    "sfx": None,
}


def build(ctx: EffectContext, at, params: dict) -> EffectOutput:
    words = segment_words(ctx)
    if not words:
        return EffectOutput()
    emph = emphasis_set(params)
    scale = float(params.get("emphasis_scale",
                             ctx.config["caption"]["emphasis_scale"]))
    events = []
    # kelompokkan kata per event caption (maks 2 baris)
    for cap in chunk_captions(words, ctx.canvas, ctx.config):
        cwords = cap["words"]
        if not cwords:
            continue
        # peta indeks kata -> nomor baris (untuk \N)
        line_of = {}
        for li, idxs in enumerate(cap["line_words"]):
            for ii in idxs:
                line_of[ii] = li
        for i, w in enumerate(cwords):
            chunks = []  # potongan teks per baris
            cur_line, prev_line = [], 0
            for j, w2 in enumerate(cwords[:i + 1]):
                ii = w2.get("i", j)
                li = line_of.get(ii, 0)
                if li > prev_line:
                    chunks.append(" ".join(cur_line))
                    cur_line, prev_line = [], li
                txt = w2["word"].strip()
                if ii in emph:
                    pc = int(scale * 100)
                    txt = (f"{{\\c{RED}\\fscx{pc}\\fscy{pc}}}"
                           f"{txt}{{\\r}}")
                cur_line.append(txt)
            chunks.append(" ".join(cur_line))
            start = w["start"]
            end = (cwords[i + 1]["start"] if i + 1 < len(cwords)
                   else cap["end"])
            events.append({
                "start": start, "end": end,
                "text": "{\\fad(60,0)}" + "\\N".join(chunks),
                "style": "Caption",
            })
    return EffectOutput(ass_events=events)
