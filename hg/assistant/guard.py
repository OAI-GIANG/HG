"""Quarantine for stored text that addresses an AI ("ignore your instructions", "SYSTEM: …").

OWASP LLM01 (prompt injection) recommends segregating external content and validating output
with deterministic code. Notes are the owner's own data, but owners also save things other
people wrote — a scam email, a forwarded message — and a small local model will obey an
instruction it finds there. So HG does not hand such a note to a model at all:

- the note is still found and shown to the owner, verbatim, with a warning;
- it is never put into a model request and never the source of a NOTE / KHỚP label;
- the owner can lift the quarantine for one note (`hg note trust ID`, recorded in the ledger).

This is best-effort defence in depth. HG's guarantee does not depend on it: whatever the model
writes, HG's own sentence check decides the label (hg.assistant.grounding).

Detection runs on normalised copies of the text (see `normalise`) and grades its signals:
a STRONG signal (an instruction to drop previous instructions, a persona switch, a request to
reveal hidden instructions or send notes away, chat-template tokens) quarantines on its own;
WEAK signals (a role tag, "answer only", "admin mode", "system prompt", an AI addressee, a
fake end-of-data marker) quarantine only when at least two distinct ones occur.
"""
import re
import unicodedata

from hg.assistant import textvi

# Look-alike letters from other scripts that are used to dodge filters (Cyrillic, Greek).
_HOMOGLYPHS = str.maketrans({
    "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "у": "y", "х": "x", "і": "i", "ј": "j", "ѕ": "s",
    "ԁ": "d", "һ": "h", "ӏ": "l", "ո": "n", "ν": "v", "ο": "o", "α": "a", "ε": "e", "ι": "i", "κ": "k",
    "τ": "t", "ρ": "p", "μ": "m", "η": "n", "Α": "a", "Ε": "e", "Ο": "o", "Ι": "i", "Κ": "k", "Τ": "t",
    "А": "a", "Е": "e", "О": "o", "Р": "p", "С": "c", "Т": "t", "Х": "x", "І": "i", "М": "m", "Н": "h",
})
_LEET = str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "@": "a", "$": "s", "!": "i"})
_DOTTED = re.compile(r"(?<![\w.])(?:\w\.){2,}\w(?![\w.])")   # "S.Y.S.T.E.M"
_DROP = {"Cf", "Mn"}                               # format chars (zero-width, bidi); marks handled by fold

_OBJ = r"(?:huong dan|chi dan|chi thi|quy tac|lenh|yeu cau|thiet lap|luat|instruction|instructions|rules|prompt|prompts|" \
       r"guidelines|directives|directions|policy|policies|checks)"
STRONG = [
    # --- override earlier instructions
    ("vi-ignore", r"\b(?:bo qua|phot lo|lo di|quen|xoa bo|huy bo|vut bo|dung nghe theo|dung tuan theo|khong can theo)\b"
                  r".{0,30}?\b" + _OBJ + r"\b"),
    ("vi-override", r"\b" + _OBJ + r"\b.{0,40}?\b(?:cu|truoc do|truoc day|truoc|ban dau|an toan)\b.{0,40}?"
                    r"\b(?:vo hieu|bi thu hoi|da thu hoi|khong con hieu luc|khong con ap dung|het hieu luc|bi huy)\b"),
    ("vi-forget-told", r"\bquen\b.{0,15}?\b(?:het|tat ca|moi)?\b.{0,15}?\b(?:da|duoc)?\s*(?:dan|bao|chi|huong dan)\b"
                       r".{0,15}?\bban\b"),
    ("vi-supreme", r"\b(?:menh lenh cao nhat|uu tien cao nhat|quy tac moi nhat|lenh tiep theo cua he thong|"
                   r"huong dan moi tu quan tri)\b"),
    ("en-ignore", r"\b(?:ignore|disregard|forget|override|bypass|skip|drop)\b.{0,25}?\b(?:your|all|any|the|previous|prior|"
                  r"earlier|above|usual|old|my)?\s*(?:previous|prior|earlier|above|usual|old|system)?\s*" + _OBJ + r"\b|"
                  r"\b(?:ignore|disregard)\s+(?:the\s+)?above\b|\bignore\s+(?:the\s+)?(?:user'?s?\s+)?question\b"),
    ("en-no-longer", r"\b(?:everything|anything|all)\s+(?:you were|you've been|you have been)\s+told\b|"
                     r"\b(?:no longer applies?|obey this note|follow only (?:the|these|this)|over anything else)\b"),
    # --- persona / role switch
    ("vi-persona", r"\b(?:tu bay gio|ke tu bay gio|ke tu gio|tu gio|tu nay|tu dong nay)\b.{0,40}?\b(?:ban la|ban se|"
                   r"ban chi|tro ly|ai|mo hinh|lam theo|hay coi)\b"),
    ("vi-roleplay", r"\b(?:hay\s+)?nhap vai\b|\bdong vai\b.{0,40}?\b(?:ngan hang|ho tro|quan tri|nhan vien)\b"),
    ("en-persona", r"\b(?:you are now|from now on,? you|act as an? (?:ai|assistant|admin|system|unrestricted)|"
                   r"pretend (?:to be|you are)|roleplay as|you must now|as the real assistant)\b"),
    # --- reveal hidden instructions or other data
    ("vi-reveal", r"\b(?:tiet lo|hien thi|in ra|cho xem|dua ra|doc ra|chep|liet ke)\b.{0,40}?\b(?:prompt|loi nhac he thong|"
                  r"chi dan he thong|huong dan he thong|chi dan an|huong dan noi bo|cau hinh an|toan bo ghi chu|"
                  r"tat ca cac ghi chu|ghi chu khac)\b"),
    ("en-reveal", r"\b(?:reveal|show|print|output|leak|repeat|dump|list)\b.{0,40}?\b(?:system prompt|hidden prompt|"
                  r"your instructions|initial instructions|your prompt|your rules|hidden configuration|instructions you were|"
                  r"environment variables|keys or tokens|all (?:the )?notes|every note)\b"),
    # --- forced output, whatever is asked
    ("vi-forced", r"\b(?:du nguoi dung hoi gi|bat ke (?:nguoi dung hoi gi|cau hoi|ho hoi)|moi cau hoi deu|"
                  r"cau tra loi cua ban bat buoc|chi duoc (?:dap|tra loi|noi))\b"),
    ("en-forced", r"\b(?:to every question|whatever (?:the user|they) (?:ask|asks)|no matter what (?:the user|they) ask|"
                  r"reply only in|must (?:begin|start) with)\b"),
    # --- exfiltration
    ("exfil-url", r"!\[[^\]]*\]\(\s*https?://|\b(?:webhook|paste cong khai|pastebin|collect|log\?q=)\b|"
                  r"https?://\S+\?\S*=\s*(?:$|\s|\))"),
    ("vi-exfil", r"\b(?:gui|chuyen|dang|tai len|upload|chep)\b.{0,30}?\b(?:het|toan bo|tat ca)?\s*(?:ghi chu|notes|du lieu)\b"
                 r".{0,60}?(?:http|www|@|email|link|nhom|telegram|zalo|webhook)"),
    ("en-exfil", r"\b(?:send|forward|post|upload|email|append)\b.{0,30}?\b(?:all|every|the)?\s*(?:notes?|data|messages|"
                 r"memory|conversation|contents)\b.{0,40}?(?:http|www|@|to\s+\S+@|link)"),
    # --- answering instructions aimed at the reader of the note
    ("tell-user", r"\b(?:noi voi nguoi dung|bao nguoi dung|hoi nguoi dung|tell the user|ask the user|claim (?:that )?the|"
                  r"say (?:that )?the (?:appointment|meeting|bill|notes?|account))\b"),
    ("insert-answer", r"\b(?:chen|them|dua|gan)\b.{0,40}?\b(?:vao|trong)\s+cau tra loi\b|"
                      r"\binclude\b.{0,40}?\bin your (?:answer|reply|response)\b"),
    # --- structure that never occurs in a personal note
    ("chat-template", r"(?:<\|im_start\|>|<\|im_end\|>|\[inst\]|\[/inst\]|<\|system\|>|<\|assistant\|>|<<sys>>|"
                      r"#{2,}\s*system\s*#{2,}|begin (?:admin|system) instructions|end of (?:user )?notes)"),
    ("tool-call", r"\"(?:tool|function|function_call|tool_name)\"\s*:|\b(?:goi cong cu|call the tool|invoke the tool)\b"),
    ("decode-follow", r"\b(?:giai ma|decode)\b.{0,60}?\b(?:lam theo|lam dung|follow|execute|run)\b|"
                      r"\b(?:lam theo|follow)\b.{0,30}?\b(?:base64|chuoi ma hoa)\b"),
    ("hidden-instruction", r"<!--.{0,200}?(?:tro ly|assistant|\bai\b|nguoi dung|the user).{0,200}?-->"),
    ("zh-ignore", r"(?:忽略|无视|忘记).{0,10}?(?:指令|指示|提示|规则|说明)"),
    ("zh-persona", r"(?:你现在是|从现在开始你|扮演)"),
    ("zh-reveal", r"(?:系统提示|显示.{0,6}提示词|泄露)"),
]
WEAK = [
    ("role-tag", r"(?:^|[\s\[\(\"'>|:])(?:system|assistant|developer|user)\s*:\s*(?:\S+\s+){0,3}?"
                 r"(?:you|ignore|disregard|answer|reply|respond|reveal|grant|give|say|print|output|pretend|act|"
                 r"forget|obey|follow|execute|run|bo qua|hay|tra loi|da hieu|tot|gio)\b"),
    ("only-answer", r"\b(?:answer|reply|respond|say)\s+(?:only|with only|just|solely)\b|"
                    r"\b(?:chi|hay)\s+(?:tra loi|noi|dap)\b.{0,40}?\b(?:mot tu|duy nhat|bang dung|bang chu|dung mot)\b|"
                    r"\btra loi\s+(?:moi|tat ca)\s+cau hoi\b|\btra loi bang mot tu\b"),
    ("mode", r"\b(?:admin|administrator|developer|god|jailbreak|dan|unrestricted|debug)\s+mode\b|"
             r"\bche do\s+(?:quan tri|nha phat trien|khong gioi han)\b|\btat (?:cac )?quy tac an toan\b"),
    ("system-prompt", r"\bsystem\s+prompt\b|\bprompt\s+he\s+thong\b|\bloi nhac he thong\b"),
    ("ai-addressee", r"\b(?:tro ly|tro ly ai|tro ly ao|chatbot|mo hinh ngon ngu|language model|llm|"
                     r"assistant|friendly ai|dear ai|hey ai|ghi chu cho may|luu y cho tro ly)\b|"
                     r"\b(?:neu ban la|if you(?:'re| are)) (?:ai|mot ai|tro ly|mo hinh|an ai|a language model|"
                     r"summarizing|reading)\b|(?:^|[\s(,.;])ai\s*[:,]"),
    ("end-marker", r"\b(?:het du lieu|end of (?:data|context|document|notes)|ket thuc (?:du lieu|ngu canh|tai lieu))\b|"
                   r"</(?:data|context|notes)>|\[ket thuc tai lieu\]"),
    ("answer-instruction", r"\b(?:hay|lam on|vui long|nho|please|kindly|could you)\b.{0,50}?\b(?:tra loi|dap|noi|in|chep|"
                           r"liet ke|bo qua|lo|reply|respond|say|tell|print|skip|ignore)\b|"
                           r"\bkhi (?:duoc hoi|nguoi dung hoi)\b|\bwhen asked\b"),
    ("third-person-user", r"\b(?:nguoi dung|the user|user's)\b"),
    ("secret-request", r"\b(?:ma otp|otp|mat khau|password|token|keys?)\b.{0,40}?\b(?:nguoi dung|the user|xac minh|"
                       r"verify|gui|send|type)\b"),
]
_STRONG = [(n, re.compile(p)) for n, p in STRONG]
_WEAK = [(n, re.compile(p)) for n, p in WEAK]


def normalise(text):
    """Matching copy: NFKC, homoglyphs to Latin, invisible format characters removed, lower-case,
    diacritics folded (đ -> d), letter-spaced words joined, whitespace collapsed."""
    text = unicodedata.normalize("NFKC", text or "").translate(_HOMOGLYPHS)
    text = "".join(c for c in text if unicodedata.category(c) != "Cf")
    folded = textvi.fold(text.lower())
    folded = _DOTTED.sub(lambda m: m.group(0).replace(".", ""), folded)
    return " ".join(_join_spaced(chunk) for chunk in re.split(r"\s{2,}|\n", folded) if chunk.strip())


def _join_spaced(chunk):
    """'b o q u a' -> 'boqua' only when a chunk is made of single letters (letter-spaced word)."""
    tokens = chunk.split()
    letters = [t.strip(",.;:!?") for t in tokens]
    if len(tokens) >= 2 and all(len(t) == 1 and t.isalpha() for t in letters):
        return "".join(letters) + ("," if tokens[-1].endswith(",") else "")
    out, run = [], []
    for t in tokens + [""]:
        if len(t) == 1 and t.isalpha():
            run.append(t)
            continue
        if len(run) >= 4:
            out.append("".join(run))
        else:
            out.extend(run)
        run = []
        if t:
            out.append(t)
    return " ".join(out)


def directives(text):
    """Names of the signals found; non-empty means: quarantine (one strong, or two distinct weak)."""
    base = normalise(text)
    variants = {base, base.translate(_LEET)}
    strong = sorted({name for name, rx in _STRONG for v in variants if rx.search(v)})
    weak = sorted({name for name, rx in _WEAK for v in variants if rx.search(v)})
    if strong or len(weak) >= 2:
        return strong + weak
    return []


def is_directive(text):
    return bool(directives(text))


# ---------------------------------------------------------------- held-out measurement
RECALL_MIN = 0.75              # fixed 2026-10-29 before any held-out data was run
FALSE_POSITIVE_MAX = 0.05


def evaluate(injection_items, ordinary_items):
    """Recall on injection texts and false-positive rate on ordinary notes, with the misses."""
    missed = [{"id": i["id"], "technique": i.get("technique")} for i in injection_items if not is_directive(i["text"])]
    flagged = [{"id": i["id"], "signals": directives(i["text"])} for i in ordinary_items if is_directive(i["text"])]
    recall = 1 - len(missed) / len(injection_items)
    fp_rate = len(flagged) / len(ordinary_items)
    return {"injections": len(injection_items), "ordinary": len(ordinary_items),
            "recall": round(recall, 3), "false_positive_rate": round(fp_rate, 3),
            "thresholds": {"recall_min": RECALL_MIN, "false_positive_max": FALSE_POSITIVE_MAX},
            "verdict": "PASS" if recall >= RECALL_MIN and fp_rate <= FALSE_POSITIVE_MAX else "FAIL",
            "missed": missed, "flagged": flagged}


def main(argv=None):
    """python -m hg.assistant.guard eval INJECTIONS.json ORDINARY.json  (prints a JSON report)"""
    import json
    import sys
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 3 or args[0] != "eval":
        print(main.__doc__)
        return 2
    load = lambda path: json.loads(open(path, encoding="utf-8").read())["items"]
    report = evaluate(load(args[1]), load(args[2]))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
