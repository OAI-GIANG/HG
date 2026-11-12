"""Vietnamese-first text analysis for the assistant layer. Standard library only.

Why HG needs its own analyzer instead of `hg.memory.index.tokenize`:
- Vietnamese words are written as separate syllables, so the most frequent syllables
  ("là", "có", "của", "và") match almost every note; BM25 then never says "nothing
  relevant" and abstention cannot work. Function syllables are dropped here, and adjacent
  content syllables are also indexed as pairs ("xe_máy") so multi-syllable words score
  above their parts.
- People type on phones without diacritics ("bao hiem xe may"). Every token is also
  folded: combining marks removed after NFD and "đ" mapped to "d" by hand, because NFD
  leaves "đ" unchanged.
- Negation syllables ("không", "chưa", ...) are NOT stopwords: they flip meaning, so the
  grounding check needs them (`negations`).
"""
import re
import unicodedata

WORD = re.compile(r"\w+", re.UNICODE)
_NUMBER = re.compile(r"\d+(?:[.,:/\-]\d+)*")

# Function syllables that carry no topic. Kept small and explicit; negations excluded on purpose.
# Only entries WITH diacritics are matched as written. Text typed without diacritics is matched
# against UNACCENTED_STOP below, a curated list of forms whose function-word reading dominates:
# "nha" can be "nhà" (house), "ho" "hộ" (hộ chiếu), "cho" "chó" (dog), "the" "thẻ" (card),
# "be" "bé" (child), "ve" "vé" (ticket) — dropping those would lose the topic (finding F-D3).
STOPWORDS = frozenset("""
là và của có cho các những một này đó kia thì với trong để đã sẽ đang được bị
ở tại về từ khi nào gì ai sao thế nhé nha ạ à ơi vậy rồi cũng lại mà nên hay hoặc
nhưng thêm bằng như theo vào ra lên xuống qua tôi mình bạn anh chị em ông bà họ
chúng ta hãy xin vui lòng giúp cái con chiếc việc điều người lúc
vâng dạ ừ ok okay
the a an of to in on at is are was were be been and or for with by from it this that
""".split())
NEGATIONS = frozenset({"không", "ko", "hông", "chưa", "chẳng", "chả", "đừng", "chớ", "khỏi",
                       "not", "no", "never", "none"})
UNACCENTED_STOP = frozenset("""
la va cua cac nhung mot nay kia voi trong de se bi o khi nao gi ai sao nhe a oi roi cung nen hay hoac thi
them nhu theo vao ra len toi em ta xin giup chiec viec nguoi luc u vui ok okay
of and or for with from this that is are was were been by it
""".split())
# Without diacritics only unambiguous negations count: "cho" may be "chớ" but is far more often
# "cho" (for) or "chó" (dog); "dung" may be "đừng", "dùng" or "đúng"; "cha" may be "chả" or "cha".
UNACCENTED_NEGATIONS = frozenset({"khong", "ko", "not", "no", "never", "none"})


# Question and modal words: they shape a question but are not its topic. Accented forms are
# matched as written; only the unaccented forms listed in _SAFE_UNACCENTED_QUESTION are matched
# without diacritics, because e.g. "dau" can be "đâu" (where) or "dầu" (oil).
QUESTION_WORDS = frozenset("nhiêu mấy đâu phải cần làm gồm hả hở chứ chăng".split())
_SAFE_UNACCENTED_QUESTION = frozenset({"nhieu", "phai", "gom", "lam"})
# "bao" is a question word only in "bao nhiêu"/"bao nhieu" (else it may be "bảo hiểm", "báo").
# Answer slots: the noun a question asks to fill ("tên gì", "ngày nào", "mấy giờ", "liều bao
# nhiêu", "bao nhiêu tiền") is optional when matching a note's topic (finding F-D3).
_SLOT_BEFORE = frozenset({"gì", "gi", "nào", "nao"})
_SLOT_AFTER = frozenset({"mấy"})
_TIME_INTERROGATIVE_HEADS = frozenset({"khi", "luc", "hoi", "gio"})


def nfc(text):
    return unicodedata.normalize("NFC", text or "")


def fold(token):
    """Remove Vietnamese diacritics: 'đ'->'d', then drop combining marks."""
    token = token.replace("đ", "d").replace("Đ", "D")
    decomposed = unicodedata.normalize("NFD", token)
    return unicodedata.normalize("NFC", "".join(c for c in decomposed if not unicodedata.combining(c)))


_ACCENTED_STOPWORDS = frozenset(w for w in STOPWORDS if w != fold(w))
_FOLDED_STOPWORDS = frozenset(fold(w) for w in STOPWORDS)          # kept for callers; not used for matching
_FOLDED_NEGATIONS = UNACCENTED_NEGATIONS


def is_stopword(w):
    return w in _ACCENTED_STOPWORDS if w != fold(w) else w in UNACCENTED_STOP


def words(text):
    """Lower-cased NFC word tokens, punctuation removed."""
    return WORD.findall(nfc(text).lower())


def content_words(text):
    """Words that carry topic: no function syllables, no single letters (digits kept)."""
    out = []
    for w in words(text):
        # Accented words are compared as written ("đỏ" is not "đó"); words without diacritics
        # only against the curated UNACCENTED_STOP list.
        if is_stopword(w):
            continue
        if len(w) == 1 and not w.isdigit():
            continue
        out.append(w)
    return out


def _key(word):
    """An accented word matches only itself ('thủ' is not 'thứ'); a word typed without
    diacritics matches every accented form it could stand for ('thu' ~ 'thủ', 'thứ', 'thu')."""
    return word if word != fold(word) else "~" + word


def topic_keys(text):
    """Keys of what a question is about, in order: content words minus question/modal words,
    negations, "bao" of "bao nhiêu", and answer-slot nouns ("tên gì", "mấy giờ", "liều bao nhiêu")."""
    raw = words(text)
    drop = set()
    for i, w in enumerate(raw):
        nxt = raw[i + 1] if i + 1 < len(raw) else ""
        is_bao_nhieu = w == "bao" and fold(nxt) == "nhieu"
        if is_bao_nhieu or w in _SLOT_BEFORE:
            # Only a noun DIRECTLY before the interrogative is a slot ("tên gì", "ngày nào"):
            # in "nhóm máu của tôi là gì" the whole subject is asked, and "khi nào"/"lúc nào"
            # ask for a time without naming a slot.
            j = i - 1
            if j >= 0 and not is_stopword(raw[j]) and fold(raw[j]) not in _TIME_INTERROGATIVE_HEADS:
                drop.add(j)
        if is_bao_nhieu:
            drop.add(i)
            if i + 2 < len(raw) and not is_stopword(raw[i + 2]):
                drop.add(i + 2)
        if w in _SLOT_AFTER and i + 1 < len(raw):
            drop.add(i + 1)
    out = []
    for i, w in enumerate(raw):
        if i in drop or is_stopword(w) or (len(w) == 1 and not w.isdigit()):
            continue
        if w in QUESTION_WORDS or (w == fold(w) and w in _SAFE_UNACCENTED_QUESTION):
            continue
        if negations(w):
            continue
        out.append(_key(w))
    return out


def query_keys(text):
    """Match keys for text someone typed or a model wrote."""
    return [_key(w) for w in content_words(text)]


def document_keys(text):
    """Match keys a stored text offers: each word as written and its folded form."""
    keys = []
    for w in content_words(text):
        keys.append(w)
        keys.append("~" + fold(w))
    return keys


def analyze(text):
    """Index terms for stored text: as-written and folded words, plus both kinds of adjacent pairs."""
    words_ = content_words(text)
    folded = ["~" + fold(w) for w in words_]
    pairs = [f"{a}_{b}" for a, b in zip(words_, words_[1:])] + [f"{a}_{b}" for a, b in zip(folded, folded[1:])]
    return words_ + folded + pairs


def analyze_query(text):
    """Query terms: each word keyed by how it was typed, plus adjacent pairs of those keys."""
    keys = query_keys(text)
    return keys + [f"{a}_{b}" for a, b in zip(keys, keys[1:])]


_GROUPED = re.compile(r"^\d{1,3}(?:[.,]\d{3})+$")
# "8 giờ 30", "8h30", "8g30": an hour and its minutes, the same time as "8:30".
_HOUR_MINUTE = re.compile(r"(?<!\w)(?<!\d[.,:/\-])(\d{1,2})\s*(?:giờ|gio|h|g)\s*(\d{1,2})(?!\w|[.,:/\-]\d)",
                          re.IGNORECASE)


def _number_values(token):
    """Canonical values of one written number. Order, decimals and identifier zeros are kept:
    '5/9' (5 September) is not '9/5'; '8:05' is not '5:08'; '0,5' is not '5'; '0420' is not '420'."""
    if _GROUPED.match(token):                              # '18.200', '4,000,000'
        return {str(int(re.sub(r"[.,]", "", token)))}
    parts = re.split(r"[.,:/\-]", token)
    seps = set(re.findall(r"[.,:/\-]", token))
    if len(parts) == 1:
        # A leading zero is part of an identifier (phone number, code): '0912345678', '0420'.
        # One or two digits are a quantity or a date part: '05' == '5'.
        return {token} if len(token) > 2 and token[0] == "0" else {str(int(token))}
    if seps == {":"} and len(parts) in (2, 3):             # '8:05', '08:05:30'
        return {f"{int(parts[0])}:" + ":".join(f"{int(p):02d}" for p in parts[1:])} | (
            {str(int(parts[0]))} if all(int(p) == 0 for p in parts[1:]) else set())
    if len(parts) == 2 and seps <= {".", ","}:             # decimal comma or point: '0,5', '2.5'
        return {f"{int(parts[0])}.{parts[1].rstrip('0') or '0'}".removesuffix(".0")}
    if len(parts) == 2 and seps == {"/"}:                  # day/month: '5/9'
        return {f"--{int(parts[1]):02d}-{int(parts[0]):02d}"}
    if len(parts) == 3 and len(seps) == 1 and seps <= {"/", "-", "."}:
        if len(parts[0]) == 4:                             # ISO '2026-09-15'
            y, m, d = parts
        else:                                              # Vietnamese order '15/09/2026'
            d, m, y = parts
        return {f"{int(y)}-{int(m):02d}-{int(d):02d}"}
    # Anything else (a range '10-15', mixed separators) keeps its integer atoms.
    return {str(int(p)) for p in parts if p}


def numbers(text):
    """Canonical values of every number, so '2026-09-15' == '15/09/2026', '18.200' == '18200',
    '8 giờ 30' == '8:30' and '0,5' == '0.5' -- and '5/9' != '9/5', '8:05' != '5:08',
    '0,5' != '5', '0420' != '420'.

    A thousands-grouped number ('18.200', '4,000,000') is one integer; a two-part number with
    '.' or ',' that is not grouped is a decimal; 'd/m' and 'd/m/y' are Vietnamese day-first
    dates and 'y-m-d' an ISO date; 'h:mm' is a time. Unit conversions ('20 giờ' vs '8 giờ
    tối') are not understood and show up as a mismatch.
    """
    text = nfc(text)
    values = set()
    for m in _HOUR_MINUTE.finditer(text):
        values.add(f"{int(m.group(1))}:{int(m.group(2)):02d}")
    text = _HOUR_MINUTE.sub(" ", text)
    for n in _NUMBER.findall(text):
        values |= _number_values(n)
    return values


def number_gap(claim_text, source_text, *, parts=False):
    """Values the claim states that the source does not.

    A day/month in the claim ('5/9') is found in a full date of the source ('05/09/2026'), not
    the other way round. With parts=True (eval keys, written by the owner as separate atoms such
    as ["18", "30"] or "2027") a plain integer may also be a part of a source date or time; never
    a digit run of a decimal or an identifier ('5' is not in '0,5', '420' is not in '0420').
    Grounding uses parts=False: "họp lúc 5 giờ" is not supported by a note saying 15:05."""
    source = numbers(source_text)
    offered = set(source)
    days = set()
    for v in source:
        if re.match(r"^(?:\d+|-)-\d{2}-\d{2}$", v):          # '2026-09-05', '--09-05'
            if not v.startswith("--"):
                days.add(v[v.index("-"):])
            if parts:
                offered |= {str(int(p)) for p in v.split("-") if p}
        elif ":" in v and parts:                              # '18:30'
            offered |= {str(int(p)) for p in v.split(":")}
    return {v for v in numbers(claim_text) - offered if not (v.startswith("--") and v[1:] in days)}


def negations(text):
    """Negation words, folded so 'không' and 'khong' compare equal; accented words must match exactly."""
    return {fold(w) for w in words(text)
            if w in NEGATIONS or (w == fold(w) and w in UNACCENTED_NEGATIONS)}


def folded_set(text):
    return {fold(w) for w in content_words(text)}


def covers(claim_text, source_text):
    """(share of the claim's words found in the source, the claim's keys) under the key rules above."""
    claim = set(query_keys(claim_text))
    if not claim:
        return 0.0, claim
    return len(claim & set(document_keys(source_text))) / len(claim), claim
