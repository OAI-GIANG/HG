"""`hg check`: hold any text (a message someone sent, a plan, a draft) against the owner's notes.

No model is involved. For each sentence HG finds the closest notes and reports:
    KHỚP      (NOTE)      a note says the same thing
    MÂU THUẪN (CONFLICT)  a note on the same thing has a different number/date/name or negation
    CHƯA RÕ   (MODEL)     no note covers it
"""
from hg.assistant import grounding

LABELS_VI = {"NOTE": "KHỚP", "CONFLICT": "MÂU THUẪN", "MODEL": "CHƯA RÕ", "BADCITE": "CHƯA RÕ",
             "NONE": "", "ABSTAIN": ""}


def check(text, notebook, *, per_sentence=5):
    records = notebook.active()
    results = []
    for sentence in grounding.split_sentences(text):
        hits = notebook.search(sentence, limit=per_sentence, records=records)
        refs = {f"N{i}": h for i, h in enumerate(hits, 1)}
        result = grounding.check_sentence(sentence, {ref: h["content"] for ref, h in refs.items()})
        if result["label"] == "BADCITE":          # citations inside someone else's text mean nothing here
            result["label"] = "MODEL"
        result["memory_id"] = refs[result["note"]]["memory_id"] if result.get("note") else None
        result["note_text"] = refs[result["note"]]["content"] if result.get("note") else None
        results.append(result)
    return grounding.summarize(results)
