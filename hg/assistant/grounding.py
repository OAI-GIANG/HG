"""HG's own sentence-level check of an answer against the owner's notes.

The model's citations are hints, never the verdict. For every sentence HG decides, from the
text alone, which note (if any) supports it:

    NOTE      a retrieved note supports the sentence: enough of its content words appear in
              the note AND every number, date, proper name and negation the sentence asserts
              is consistent with that note
    CONFLICT  the sentence is close to a note but asserts a different number/date/name or
              flips a negation -- the most dangerous error in personal notes ("3 giờ" vs "5 giờ")
    BADCITE   the model cited a note that does not exist or does not support the sentence,
              and no other note supports it
    MODEL     no note supports it: the model's own words, unverified
    ABSTAIN   the answer says the notes do not have this ("Ghi chú chưa có thông tin này.")
    NONE      no factual content to check ("Vâng.", "Dưới đây là câu trả lời:")

Limits, stated wherever results are shown: this is a lexical check (word overlap plus exact
numbers, names and negations), not semantic entailment. It can miss paraphrases (false
MODEL) and cannot judge reasoning across several notes.
"""
import re

from hg.assistant import textvi

CITE = re.compile(r"\[\s*((?:N\d+)(?:\s*[,;]\s*N\d+)*)\s*\]", re.IGNORECASE)
_SENT_SPLIT = re.compile(r"(?<=[.!?…])\s+|\n+")
# Words a model uses to talk about the notes rather than about the world.
META = frozenset(textvi.fold(w) for w in "ghi chú note notes nguồn dựa theo thông tin cho biết biết rằng".split())

SUPPORT_THRESHOLD = 0.6     # share of the sentence's content words found in the note
NEAR_THRESHOLD = 0.4        # close enough that a number/negation mismatch is a CONFLICT
NEGATION_MATCH = 0.75       # share of a negated clause's words that must reappear to count as "the same"


ABSTAIN_PATTERNS = ("chua co thong tin", "khong co thong tin", "khong co trong ghi chu", "chua co trong ghi chu",
                    "khong tim thay", "toi khong biet", "khong ro", "no information", "not in the notes", "i don't know")
_LEAD_CITES = re.compile(r"^((?:\[\s*N\d+(?:\s*[,;]\s*N\d+)*\s*\]\s*)+)(.*)$", re.IGNORECASE | re.DOTALL)
_SPACE_BEFORE_PUNCT = re.compile(r"\s+([.,;:!?…])")


def split_sentences(text):
    """Sentences, with a citation written after the full stop ("... km. [N1]") kept on its sentence."""
    parts = [p.strip() for p in _SENT_SPLIT.split(textvi.nfc(text or ""))]
    out = []
    for part in parts:
        if not part:
            continue
        lead = _LEAD_CITES.match(part)
        if lead and out:
            out[-1] = out[-1] + " " + lead.group(1).strip()
            part = lead.group(2).strip()
            if not part:
                continue
        out.append(part)
    return out


def is_abstention(sentence):
    folded = " ".join(textvi.fold(w) for w in textvi.words(sentence))
    return any(p in folded for p in ABSTAIN_PATTERNS)


def citations(sentence):
    refs = []
    for group in CITE.findall(sentence):
        refs += [r.strip().upper() for r in re.split(r"[,;]", group)]
    return refs


def strip_citations(sentence):
    return _SPACE_BEFORE_PUNCT.sub(r"\1", CITE.sub("", sentence)).strip()


def _claim_words(sentence):
    return {k for k in textvi.query_keys(sentence) if textvi.fold(k.lstrip("~")) not in META}


def _names(sentence):
    """Capitalised words after the first word (names, places, brands), folded."""
    tokens = textvi.WORD.findall(textvi.nfc(sentence))
    return {textvi.fold(t.lower()) for t in tokens[1:] if t[:1].isupper() and not t.isdigit()}


UNITS = frozenset(textvi.fold(u) for u in """ngày tuần tháng năm giờ phút giây tiếng buổi lần km m cm mm kg g
lít ml đồng nghìn ngàn triệu tỷ tỉ psi phần trăm % usd đô vnd""".split())
_RATE_WORDS = frozenset({"moi", "hang", "mot"})


def _units(text):
    """Units bound to a quantity: after a number ('2 lần', '4 triệu') or a rate word ('mỗi ngày')."""
    tokens = [textvi.fold(t) for t in textvi.words(text)]
    return {t for i, t in enumerate(tokens)
            if t in UNITS and i > 0 and (tokens[i - 1].isdigit() or tokens[i - 1] in _RATE_WORDS)}


_CLAUSE_BREAK = re.compile(r"[,.;:!?…()\n]+|\b(?:nhưng|còn|mà|song|tuy|but|while)\b", re.IGNORECASE)


def _negated_clauses(text):
    """For every negation, the folded content words after it up to the end of its clause."""
    clauses = []
    for clause in _CLAUSE_BREAK.split(textvi.nfc(text or "")):
        if not clause:
            continue
        tokens = textvi.words(clause)
        for i, w in enumerate(tokens):
            if textvi.negations(w):
                governed = [t for t in tokens[i + 1:] if textvi.content_words(t) and not textvi.negations(t)]
                if governed:
                    clauses.append(frozenset(textvi.fold(t) for t in governed))
    return clauses


def _covered(a, b):
    """Most of a's words appear in b."""
    return bool(a) and len(a & b) / len(a) >= NEGATION_MATCH


def compare(sentence, note_text):
    """Return (overlap, problems) for one sentence against one note."""
    claim = _claim_words(sentence)
    if not claim:
        return 0.0, []
    note_keys = set(textvi.document_keys(note_text))
    note_words = textvi.folded_set(note_text)
    overlap = len(claim & note_keys) / len(claim)
    problems = []
    missing_numbers = textvi.numbers(sentence) - textvi.numbers(note_text)
    if missing_numbers:
        problems.append("số/ngày không có trong ghi chú: " + ", ".join(sorted(missing_numbers)))
    missing_units = _units(sentence) - note_words
    if missing_units:
        problems.append("đơn vị không có trong ghi chú: " + ", ".join(sorted(missing_units)))
    missing_names = _names(sentence) - note_words
    if missing_names:
        problems.append("tên không có trong ghi chú: " + ", ".join(sorted(missing_names)))
    sentence_neg, note_neg = _negated_clauses(sentence), _negated_clauses(note_text)
    claim_folded = {textvi.fold(k.lstrip("~")) for k in claim}
    if any(not any(_covered(s, n) for n in note_neg) for s in sentence_neg):
        problems.append("câu phủ định điều ghi chú không phủ định")
    elif any(_covered(n, claim_folded) and not any(_covered(n, s) for s in sentence_neg) for n in note_neg):
        problems.append("câu bỏ mất phủ định của ghi chú")
    return overlap, problems


def check_sentence(sentence, notes):
    """notes: {ref: text}. Returns one labelled record."""
    text = strip_citations(sentence)
    cited = citations(sentence)
    if is_abstention(text):
        return {"sentence": text, "label": "ABSTAIN", "note": None, "cited": cited, "reasons": []}
    if not _claim_words(text):
        return {"sentence": text, "label": "NONE", "note": None, "cited": cited, "reasons": []}
    scored = []
    for ref, note_text in notes.items():
        overlap, problems = compare(text, note_text)
        scored.append((ref, overlap, problems))
    supported = sorted(((r, o) for r, o, p in scored if o >= SUPPORT_THRESHOLD and not p),
                       key=lambda x: (-x[1], x[0]))
    cited_ok = [r for r, _o in supported if r in cited]
    if cited_ok or supported:
        ref = cited_ok[0] if cited_ok else supported[0][0]
        reasons = []
        bad = [c for c in cited if c not in {r for r, _o in supported}]
        if bad:
            reasons.append("trích dẫn thừa/sai bị bỏ qua: " + ", ".join(bad))
        return {"sentence": text, "label": "NOTE", "note": ref, "cited": cited, "reasons": reasons}
    near = sorted(((r, o, p) for r, o, p in scored if o >= NEAR_THRESHOLD and p), key=lambda x: (-x[1], x[0]))
    if near:
        ref, _o, problems = near[0]
        return {"sentence": text, "label": "CONFLICT", "note": ref, "cited": cited, "reasons": problems}
    if cited:
        unknown = [c for c in cited if c not in notes]
        reasons = (["ghi chú không tồn tại: " + ", ".join(unknown)] if unknown else []) + \
                  (["ghi chú được trích không hỗ trợ câu này"] if len(unknown) < len(cited) else [])
        return {"sentence": text, "label": "BADCITE", "note": None, "cited": cited, "reasons": reasons}
    return {"sentence": text, "label": "MODEL", "note": None, "cited": cited, "reasons": []}


def summarize(records):
    """Counts over labelled sentences; NONE and ABSTAIN are not claims."""
    counts = {k: 0 for k in ("NOTE", "MODEL", "CONFLICT", "BADCITE")}
    for r in records:
        if r["label"] in counts:
            counts[r["label"]] += 1
    claims = sum(counts.values())
    return {"sentences": records, "counts": counts, "claims": claims,
            "abstained": any(r["label"] == "ABSTAIN" for r in records),
            "grounded_ratio": round(counts["NOTE"] / claims, 3) if claims else 0.0,
            "method": "lexical overlap + exact numbers, names and negations (not semantic entailment)"}


def check_text(text, notes):
    """Label every sentence of `text` against `notes` ({ref: text})."""
    return summarize([check_sentence(s, notes) for s in split_sentences(text)])


def note_conflicts(notes, *, threshold=SUPPORT_THRESHOLD):
    """Pairs of notes that talk about the same thing but disagree on a number, name or negation."""
    refs = sorted(notes)
    found = []
    for i, a in enumerate(refs):
        for b in refs[i + 1:]:
            short, long_ = (a, b) if len(_claim_words(notes[a])) <= len(_claim_words(notes[b])) else (b, a)
            overlap, problems = compare(notes[short], notes[long_])
            if overlap >= threshold and problems:
                found.append({"notes": [a, b], "reasons": problems})
    return found
