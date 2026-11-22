"""HG's own sentence-level check of an answer against the owner's notes.

The model's citations are hints, never the verdict. For every sentence HG decides, from the
text alone, which note (if any) supports it:

    NOTE      a retrieved note supports the sentence: enough of its content words appear in
              the note AND every number, date, proper name and negation the sentence asserts
              is consistent with that note; and, when the question is known, the note is about
              what was asked (anchored) and contains what the sentence adds beyond the question
              (new_information_gap)
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


_BRACKETED = re.compile(r"\[[^\]]*\]|\([^)]*\)")


def is_abstention(sentence):
    """The sentence itself says the notes lack this. A phrase only inside brackets, next to a
    claim ("… thay mỗi 6 tháng [Ghi chú chưa có thông tin này]"), is not an abstention."""
    outside = _BRACKETED.sub(" ", sentence)
    folded = " ".join(textvi.fold(w) for w in textvi.words(outside))
    if any(p in folded for p in ABSTAIN_PATTERNS):
        return True
    inside = " ".join(textvi.fold(w) for w in textvi.words(sentence))
    return any(p in inside for p in ABSTAIN_PATTERNS) and not textvi.content_words(outside)


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
    missing_numbers = textvi.number_gap(sentence, note_text)
    if missing_numbers:
        problems.append("số/ngày không có trong ghi chú: " + ", ".join(sorted(missing_numbers)))
    note_all = {textvi.fold(t) for t in textvi.words(note_text)}     # names may be function words ("tiếng Anh")
    if any(":" in v for v in textvi.numbers(note_text)):           # '8:00' states the hour and minutes
        note_all |= {"gio", "phut"}
    missing_units = _units(sentence) - note_all
    if missing_units:
        problems.append("đơn vị không có trong ghi chú: " + ", ".join(sorted(missing_units)))
    missing_names = _names(sentence) - note_all
    if missing_names:
        problems.append("tên không có trong ghi chú: " + ", ".join(sorted(missing_names)))
    sentence_neg, note_neg = _negated_clauses(sentence), _negated_clauses(note_text)
    claim_folded = {textvi.fold(k.lstrip("~")) for k in claim}
    if any(not any(_covered(s, n) for n in note_neg) for s in sentence_neg):
        problems.append("câu phủ định điều ghi chú không phủ định")
    elif any(_covered(n, claim_folded) and not any(_covered(n, s) for s in sentence_neg) for n in note_neg):
        problems.append("câu bỏ mất phủ định của ghi chú")
    return overlap, problems


# Relatives a question can name (RC-5, AC-A6 v4 u07): like a proper name, the relative asked about must
# be in the note. Each entry: the question form -> forms a note may use for the same person. Ambiguous
# words stay out ("ba" is also "three", "chú"/"bác"/"cô" also "chú ý", "bác sĩ", "cô giáo").
_KIN = {
    "bố": ("bố", "ba", "cha", "tía"), "cha": ("bố", "ba", "cha", "tía"),
    "mẹ": ("mẹ", "má", "mạ"), "vợ": ("vợ",), "chồng": ("chồng",),
    "ông nội": ("ông nội",), "ông ngoại": ("ông ngoại",), "bà nội": ("bà nội",), "bà ngoại": ("bà ngoại",),
}


_KIN_WORDS = frozenset(w for k, forms in _KIN.items() for f in (k,) + forms for w in f.split()) | frozenset(
    textvi.fold(w) for k, forms in _KIN.items() for f in (k,) + forms for w in f.split())


def _kin_gap(question, note_text):
    """Relatives named in the question that the note does not name (as written, with diacritics)."""
    q = " " + " ".join(textvi.words(question or "")) + " "
    n = " " + " ".join(textvi.words(note_text or "")) + " "
    missing = []
    for kin, forms in _KIN.items():
        if f" {kin} " in q and not any(f" {f} " in n for f in forms):
            missing.append(kin)
    return missing


def anchored(question, note_text, *, other_notes=()):
    """Return missing discriminative topic terms, or None when this note is on-topic.

    In addition to the original topic threshold, every question number, proper name, and
    content word that appears in another active note must be present in this candidate note.
    This prevents a note about Bin/September from answering a question about Na/October.
    """
    topic = textvi.topic_keys(question or "")
    if not topic:
        return None
    note_keys = set(textvi.document_keys(note_text))
    missing_numbers = textvi.number_gap(question or "", note_text)
    if missing_numbers:
        return "số " + ", ".join(sorted(f"tháng {int(v[2:])}" if re.match(r"^--\d{2}$", v) else v
                                        for v in missing_numbers))
    missing_kin = _kin_gap(question, note_text)
    if missing_kin:
        return " ".join(missing_kin)
    # Every capitalised name of the question must be in the note, even one that is also a function
    # word ("Bi" ~ "bị", v6 RC-12, ledger section 77).
    note_all = {textvi.fold(w) for w in textvi.words(note_text)}
    missing_names = sorted(n for n in _names(question or "") if n not in note_all)
    if missing_names:
        return " ".join(missing_names)
    other_keys = set()
    for other in other_notes or ():
        other_keys.update(textvi.document_keys(other))
    proper_names = _names(question or "")
    discriminative = []
    # Only topic words discriminate. Question words, answer slots and discourse markers ("bao" of
    # "bao nhiêu", "tiền" of "bao nhiêu tiền", "cỡ mấy") are not topic, and "bao" folds onto "bảo"
    # of a sibling note (AC-A6 v4 FAIL, RC-1, ledger section 75).
    for key in topic:
        token = key[1:] if key.startswith("~") else key
        is_name = textvi.fold(token) in proper_names
        appears_elsewhere = key in other_keys
        if (is_name or appears_elsewhere) and key not in note_keys:
            discriminative.append(token)
    if discriminative:
        return " ".join(dict.fromkeys(discriminative))
    # No topic word may be missing (v6 RC-14, ledger section 77). Tolerating one let a different
    # predicate through ("khám răng" anchored "khám mắt", "nặng bao nhiêu" anchored a vaccination note)
    # and HG then labelled the substituted answer NOTE. Light words, question words, fillers and the
    # parts of a written date or time are not topic words, so this is strict only on content.
    # Relatives are checked by _kin_gap (with their synonyms "ba"/"cha", "má"); a function word kept as
    # topic ("bà" of "bà nội") counts when the note has it anywhere.
    note_words = set(textvi.words(note_text))
    present = note_keys | note_words | {"~" + textvi.fold(w) for w in note_words}
    missing = [k for k in topic if k not in present and k.lstrip("~") not in _KIN_WORDS]
    if missing:
        return " ".join(k.lstrip("~") for k in missing)
    # RC-17 (AC-A6 v8): a price question needs an amount in the note, or the model guesses one.
    if "price" in answer_slots(question) and not _AMOUNT.search(textvi.fold(textvi.nfc(note_text).lower())):
        return "số tiền"
    return None


# An amount of money as notes write it: "185.000 đồng", "250.000đ", "250k", "1tr2", "250 nghìn", "1,2 triệu".
_AMOUNT = re.compile(r"(?<![\w.,])\d[\d.,]*\s*(?:dong|d|k|nghin|ngan|trieu|tr\d*|ty|ti|vnd|usd)(?![a-z])|"
                     r"(?<![\w.,])\d{1,3}(?:[.,]\d{3})+(?![\d.,]*\d)|\$\s*\d")


def answer_slots(question):
    """Return required answer shapes inferred conservatively from common Vietnamese questions."""
    folded = " ".join(textvi.fold(w) for w in textvi.words(question or ""))
    slots = []
    money_context = bool(re.search(r"\b(?:phi|hoc phi|chi phi|tien|gia)\b", folded))
    if (re.search(r"\b(?:bao nhieu tien|gia bao nhieu|gia la bao nhieu|het bao nhieu)\b", folded)
            or (money_context and re.search(r"\bbao nhieu\b", folded))):
        slots.append("price")
    if re.search(r"\b(?:may gio|bao nhieu gio|luc may gio)\b", folded):
        slots.append("time")
    if re.search(r"\b(?:ngay nao|thang nao|khi nao|bao gio|han .* khi nao|vao hom nao)\b", folded):
        slots.append("date")
    if re.search(r"\b(?:ten gi|la ai|cua ai|ai phu trach|ai truc)\b", folded):
        slots.append("person")
    if re.search(r"\b(?:o dau|cho nao|dia chi|dia diem nao)\b", folded):
        slots.append("place")
    if not slots and re.search(r"\b(?:bao nhieu|may|so may|co may|co bao nhieu)\b", folded):
        slots.append("number")
    return tuple(dict.fromkeys(slots))


_WEEKDAYS = frozenset("thu hai thu ba thu tu thu nam thu sau thu bay chu nhat".split())
_MONEY = re.compile(r"(?<!\w)\d[\d.,]*(?:\s*(?:dong|nghin|ngan|trieu|ty|ti|vnd|usd|do))?\b", re.I)
_CLOCK = re.compile(r"(?<!\w)(?:[01]?\d|2[0-3])(?:[:h]|\s+gio)(?:[0-5]?\d)?\b", re.I)
_DATE = re.compile(r"\b(?:\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?|\d{4}-\d{2}-\d{1,2}|ngay\s+\d{1,2}|thang\s+\d{1,2})\b", re.I)


def slot_mismatch(sentence, slots):
    """Answer-slot checks are conservative lexical guards, not semantic extraction."""
    if not slots:
        return []
    folded = " ".join(textvi.fold(w) for w in textvi.words(sentence or ""))
    missing = []
    for slot in slots:
        if slot == "price":
            ok = bool(_MONEY.search(folded)) and bool(re.search(r"\b(?:dong|nghin|ngan|trieu|ty|ti|vnd|usd|do)\b", folded))
        elif slot == "time":
            ok = bool(_CLOCK.search(folded)) or bool(re.search(r"\b(?:sang|trua|chieu|toi)\b", folded) and textvi.numbers(folded))
        elif slot == "date":
            raw_sentence = textvi.fold(textvi.nfc(sentence or ""))
            ok = bool(_DATE.search(raw_sentence)) or any(
                phrase in folded for phrase in ("thu hai", "thu ba", "thu tu", "thu nam",
                                                "thu sau", "thu bay", "chu nhat"))
        elif slot == "person":
            ok = bool(_names(sentence)) or bool(re.search(r"\b(?:anh|chi|ong|ba|co|chu|bac)\s+[a-z]+\b", folded))
        elif slot == "place":
            raw = textvi.words(sentence or "")
            ok = (any(w in raw for w in ("ở", "tại", "đến", "dưới", "trên", "trong", "cạnh",
                                          "bên", "sát", "đầu", "cuối", "gần", "sau", "trước",
                                          "chợ", "đường", "quận", "phường", "tầng", "phòng",
                                          "hẻm", "ngõ", "tiệm", "hồ", "quầy", "ngăn", "kệ",
                                          "chậu", "nhà", "sân")) or
                  bool(re.search(r"\b(?:o|tai|den|duong|quan|phuong|tang|phong|hem|ngo|so nha|dau duong)\b", folded)))
        else:
            ok = bool(textvi.numbers(sentence)) or bool(re.search(r"\b(?:mot|hai|ba|bon|nam|sau|bay|tam|chin|muoi|tram|nghin|trieu)\b", folded))
        if not ok:
            missing.append(slot)
    return missing


def is_question_echo(sentence, question):
    """A sentence made only of the question's own content words is not an answer claim."""
    sentence_keys = set(textvi.query_keys(sentence or ""))
    question_keys = set(textvi.query_keys(question or ""))
    return len(sentence_keys) >= 2 and sentence_keys <= question_keys and not textvi.numbers(sentence)


NEW_INFO_RATIO = 0.6        # share of the answer's new words (not in the question) the note must contain


def new_information_gap(sentence, question, note_text):
    """Words the sentence adds beyond the question that the note does not contain, if too many.

    An answer may only add what its source note says: with two or fewer new words all must be
    in the note, otherwise at least NEW_INFO_RATIO of them ("Họp lúc 20 giờ ở quán cà phê" is
    not supported by a note that never mentions a café).
    """
    if not question:
        return []
    asked = {textvi.fold(k.lstrip("~")) for k in textvi.query_keys(question)}
    # Numbers are compared by value in compare() ('05/09/2026' is '5/9'), not as words here.
    new = [k for k in _claim_words(sentence)
           if textvi.fold(k.lstrip("~")) not in asked and not k.lstrip("~").isdigit()]
    if not new:
        return []
    note_keys = set(textvi.document_keys(note_text))
    missing = [k.lstrip("~") for k in new if k not in note_keys]
    if (len(new) <= 2 and missing) or (len(new) > 2 and (len(new) - len(missing)) / len(new) < NEW_INFO_RATIO):
        return sorted(missing)
    return []


def check_sentence(sentence, notes, *, question=None, other_notes_by_ref=None):
    """notes: {ref: text}; optional sibling notes enforce discriminative anchors."""
    text = strip_citations(sentence)
    cited = citations(sentence)
    if question and is_question_echo(text, question):
        return {"sentence": text, "label": "NONE", "note": None, "cited": cited,
                "reasons": ["lặp lại câu hỏi, không cung cấp câu trả lời"]}
    if is_abstention(text):
        return {"sentence": text, "label": "ABSTAIN", "note": None, "cited": cited, "reasons": []}
    if not _claim_words(text):
        return {"sentence": text, "label": "NONE", "note": None, "cited": cited, "reasons": []}
    scored, off_topic = [], {}
    for ref, note_text in notes.items():
        overlap, problems = compare(text, note_text)
        siblings = (other_notes_by_ref or {}).get(ref, ())
        topic = anchored(question, note_text, other_notes=siblings) if question else None
        added = new_information_gap(text, question, note_text) if question else []
        question_topic = set(textvi.topic_keys(question or "")) if question else set()
        sentence_keys = set(textvi.query_keys(text))
        slot_relevant = bool(question_topic & sentence_keys)
        slots_missing = slot_mismatch(text, answer_slots(question)) if slot_relevant else []
        reasons = []
        if topic:
            reasons.append(f"{ref} không phân biệt đúng chủ đề: {topic}")
        if added:
            reasons.append(f"{ref} không có: {', '.join(added)}")
        if slots_missing:
            reasons.append(f"câu trả lời không điền đúng kiểu thông tin: {', '.join(slots_missing)}")
        if reasons:
            off_topic[ref] = "; ".join(reasons)
        scored.append((ref, overlap, problems))
    supported = sorted(((r, o) for r, o, p in scored if o >= SUPPORT_THRESHOLD and not p and r not in off_topic),
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
    topic = [off_topic[ref] for ref in sorted(off_topic)]
    if cited:
        unknown = [c for c in cited if c not in notes]
        reasons = (["ghi chú không tồn tại: " + ", ".join(unknown)] if unknown else []) + \
                  (["ghi chú được trích không hỗ trợ câu này"] if len(unknown) < len(cited) else []) + topic
        return {"sentence": text, "label": "BADCITE", "note": None, "cited": cited, "reasons": reasons}
    return {"sentence": text, "label": "MODEL", "note": None, "cited": cited, "reasons": topic}


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


def check_text(text, notes, *, question=None):
    """Label every sentence of `text` against `notes` ({ref: text})."""
    return summarize([check_sentence(s, notes, question=question) for s in split_sentences(text)])


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
