"""Command-line front end of the assistant layer (called from `python -m hg`).

Exit codes, shared by every assistant command:
    0   done                      3   no model: notes only (MEMORY_ONLY) / model unavailable
    2   bad input                 4   note conflict (same subject, other text)
    5   nothing found (NO_DATA)   75  another HG process holds HG_HOME (try again)
    78  unsafe home, bad config, damaged ledger or untrusted local model
"""
import json
import os
import sys

from maep.core import MAEPError
from hg.assistant import config as cfg
from hg.assistant.home import Busy, HomeError, default_home, ensure_home
from hg.assistant.notes import NoteConflict, NoteError, NoteInactive, Notebook
from hg.brain.providers import ProviderError

EXIT_OK, EXIT_INPUT, EXIT_NO_MODEL, EXIT_CONFLICT, EXIT_NO_DATA, EXIT_BUSY, EXIT_CONFIG = 0, 2, 3, 4, 5, 75, 78
HELP_VI = ('HG — gõ câu hỏi rồi Enter.  "+ nội dung" để lưu ghi chú,  "/tim từ khoá" để tìm,  '
           '"/kiem văn bản" để đối chiếu,  "/q" để thoát.')


def add_parsers(sub):
    note = sub.add_parser("note", help="the owner's notes (add, search, list, show, forget)")
    nsub = note.add_subparsers(dest="note_command", required=True)
    add = nsub.add_parser("add", help="save a note (text from arguments, or stdin when none)")
    add.add_argument("text", nargs="*")
    add.add_argument("--subject", help="topic key; a second note on it must name --replaces")
    add.add_argument("--replaces", metavar="ID", help="the active note this one replaces")
    search = nsub.add_parser("search", help="find notes (works without diacritics)")
    search.add_argument("query", nargs="+")
    search.add_argument("--limit", type=int, default=5)
    lst = nsub.add_parser("list", help="newest notes first")
    lst.add_argument("--all", action="store_true", help="include replaced and forgotten notes")
    lst.add_argument("--limit", type=int, default=20)
    show = nsub.add_parser("show", help="a note and every version of its subject")
    show.add_argument("id")
    trust = nsub.add_parser("trust", help="lift the AI-directive quarantine for one note you have read")
    trust.add_argument("id")
    forget = nsub.add_parser("forget", help="retract a note (kept in history, not erased)")
    forget.add_argument("id")
    forget.add_argument("--reason", default="owner asked to forget")
    curate = nsub.add_parser("curate", help="read-only review candidates for duplicates, dates and conflicts")
    curate.add_argument("--threshold", type=float, default=0.88)
    curate.add_argument("--max-comparisons", type=int, default=20000,
                        help="hard cap on pair comparisons; report says when truncated")
    curate.add_argument("--max-findings", type=int, default=500, help="hard cap on emitted findings")
    save_ask = nsub.add_parser("save-ask", help="preview and explicitly authorize MODEL_DERIVED content from an ASK receipt")
    save_ask.add_argument("receipt_id", help="the ASK receipt event id shown by hg ask --json or /v1/chat")
    save_ask.add_argument("--subject", required=True, help="stable subject key for the owner-approved model-derived note")
    save_ask.add_argument("--text", required=True, help="content to save after explicit owner review; stored as MODEL_DERIVED")
    save_ask.add_argument("--confirm", metavar="SHA256", help="exact digest printed by the preview step")
    for p in (add, search, lst, show, forget, trust, curate, save_ask):
        p.add_argument("--json", action="store_true")

    memory = sub.add_parser("memory", help="inspect the layered Brain memory ledger")
    memory_sub = memory.add_subparsers(dest="memory_command", required=True)
    memory_curate = memory_sub.add_parser("curate", help="read-only curation candidates in one explicit MemoryStore ledger")
    memory_curate.add_argument("--ledger", required=True, help="absolute path to one existing MemoryStore JSONL ledger")
    memory_curate.add_argument("--threshold", type=float, default=0.88)
    memory_curate.add_argument("--max-comparisons", type=int, default=20000,
                               help="hard cap on pair comparisons; report says when truncated")
    memory_curate.add_argument("--max-findings", type=int, default=500, help="hard cap on emitted findings")
    memory_curate.add_argument("--json", action="store_true")

    ask = sub.add_parser("ask", help="answer from your notes with the local model; HG labels every sentence")
    ask.add_argument("question", nargs="*")
    ask.add_argument("--notes-only", action="store_true", help="never call a model")
    ask.add_argument("--provider", choices=["local", "anthropic"], default="local",
                     help="'anthropic' is a paid API and is used only when named here")
    ask.add_argument("--json", action="store_true", help="print the full receipt instead of the labelled answer")
    ask.add_argument("--general", action="store_true",
                     help="allow the model to answer a general-knowledge question when no note matches (labelled [?])")

    check = sub.add_parser("check", help="compare any text with your notes (no model)")
    check.add_argument("text", nargs="*")
    check.add_argument("--json", action="store_true")

    summ = sub.add_parser("summarize", help="summary anchored to source lines")
    summ.add_argument("path", help="a UTF-8 text file, or - for stdin")
    summ.add_argument("--model", action="store_true", help="let the local model write it; HG checks each line anchor")
    summ.add_argument("--strict", action="store_true", help="drop sentences HG cannot anchor")
    summ.add_argument("--max-sentences", type=int, default=5)
    summ.add_argument("--json", action="store_true")

    model = sub.add_parser("model", help="local model status and selection")
    msub = model.add_subparsers(dest="model_command", required=True)
    st = msub.add_parser("status")
    st.add_argument("--json", action="store_true")
    use = msub.add_parser("use", help="select a pulled model and pin its digest")
    use.add_argument("name")
    use.add_argument("--service-dir", help="runit service directory of Ollama (enables listener attestation)")

    ev = sub.add_parser("eval", help="fixed Vietnamese evaluation in a temporary home (never your notes)")
    ev.add_argument("--set", dest="spec", default=os.path.join(os.path.dirname(__file__), "eval_vi.json"))
    ev.add_argument("--json-out", help="write the full report here")
    sub.add_parser("repair", help="recover a ledger whose last line was cut off (backup first)")


def _home():
    return ensure_home(default_home())


def _text_arg(words, stdin):
    origin = getattr(stdin, "origin", None) or ("tty" if stdin.isatty() else "pipe")
    if words:
        return " ".join(words), origin
    if stdin.isatty():
        return None, origin
    return stdin.read(), origin


def _print_json(obj, out):
    out(json.dumps(obj, ensure_ascii=False, indent=2))


def _color(stream):
    return stream.isatty() and not os.environ.get("NO_COLOR")


def _release():
    return os.environ.get("HG_RELEASE_ID", "dev")


def _model_parts(home):
    conf = cfg.load(home)
    listener = cfg.attest_listener(conf)
    provider = cfg.ollama(conf)
    check = cfg.check_model(conf, provider)
    return conf, listener, check


def run(args, *, stdin=None, out=None):
    stdin = stdin or sys.stdin
    out = out or (lambda line: print(line, flush=True))
    os.umask(0o077)
    try:
        return _dispatch(args, stdin, out)
    except Busy as exc:
        out(f"HG bận: {exc}")
        return EXIT_BUSY
    except (HomeError, cfg.ConfigError) as exc:
        out(f"HG từ chối chạy: {exc}")
        return EXIT_CONFIG
    except NoteInactive as exc:
        out("Lưu bị từ chối: biên nhận ASK đã gắn với ghi chú bị thu hồi hoặc thay thế; cần một lượt ASK mới và xác nhận mới.")
        return EXIT_CONFLICT
    except NoteConflict as exc:
        out(str(exc))
        return EXIT_CONFLICT
    except NoteError as exc:
        out(f"Đầu vào không hợp lệ: {exc}")
        return EXIT_INPUT
    except MAEPError as exc:
        out(f"Sổ cái hỏng hoặc không đọc được: {exc}. Chạy: hg repair")
        return EXIT_CONFIG


def _dispatch(args, stdin, out):
    from hg.assistant.ask import safe
    command = args.command
    if command == "repair":
        from hg.assistant.repair import repair
        results = repair(_home())
        _print_json(results, out)
        return EXIT_CONFIG if any(r["status"] == "DAMAGED" for r in results) else EXIT_OK

    if command == "memory":
        if args.memory_command == "curate":
            from datetime import datetime, timezone
            from pathlib import Path
            import stat
            from hg.memory.curation import CurationInputError, analyze_memories
            from hg.memory.store import MemoryStore
            ledger = Path(args.ledger)
            try:
                if not ledger.is_absolute() or ledger.is_symlink() or not ledger.is_file():
                    raise NoteError("--ledger must be an absolute path to an existing regular file, not a symlink")
                mode = ledger.stat().st_mode
                if not stat.S_ISREG(mode):
                    raise NoteError("--ledger must be a regular file")
                store = MemoryStore(ledger)
                report = analyze_memories(store.all_records(), as_of=datetime.now(timezone.utc).isoformat(),
                                          near_duplicate_threshold=args.threshold,
                                          max_pair_comparisons=args.max_comparisons, max_findings=args.max_findings)
            except CurationInputError as exc:
                raise NoteError(str(exc)) from exc
            except OSError as exc:
                raise NoteError("memory ledger could not be read safely") from exc
            if args.json:
                _print_json(report, out)
            else:
                out(f"Rà soát chỉ đọc ledger {ledger.name}: {report['records_seen']} bản ghi.")
                for title, key in (
                    ("Trùng chính xác", "exact_duplicate_groups"),
                    ("Gần trùng", "near_duplicate_pairs"),
                    ("Mốc thời gian", "staleness_candidates"),
                    ("Mâu thuẫn/divergence", "conflict_candidates"),
                ):
                    out(f"{title}: {len(report[key])}")
                    for row in report[key]:
                        out("  " + ", ".join(row["memory_ids"]) + " — "
                            + row.get("classification", row["type"]))
                out("Không có bản ghi nào bị tự động sửa đổi.")
            return EXIT_OK if report["records_seen"] else EXIT_NO_DATA

    if command == "note":
        nb = Notebook(_home())
        sub = args.note_command
        if sub == "add":
            text, origin = _text_arg(args.text, stdin)
            if text is None:
                out("Nhập nội dung ghi chú (Ctrl-D để lưu):")
                text = stdin.read()
            record, created = nb.add(text, subject=args.subject, replaces=args.replaces, origin=origin)
            if args.json:
                _print_json({"created": created, "note": record}, out)
            else:
                out(("Đã lưu " if created else "Đã có sẵn ") + f"{record['memory_id']}"
                    + (f" (thay {args.replaces})" if args.replaces else "") + f": {safe(record['content'])[:100]}")
            return EXIT_OK
        if sub == "search":
            hits = nb.search(" ".join(args.query), limit=args.limit)
            if args.json:
                _print_json(hits, out)
            for h in hits if not args.json else []:
                out(f"{h['memory_id']}  {h['created_at'][:10]}  {safe(h['content'])[:100]}")
            if not hits and not args.json:
                out("Không tìm thấy ghi chú nào.")
            return EXIT_OK if hits else EXIT_NO_DATA
        if sub == "list":
            records = nb.snapshot() if args.all else nb.active()
            records = list(reversed(records))[:args.limit]
            if args.json:
                _print_json(records, out)
            else:
                for r in records:
                    status = "" if r["status"] == "ACTIVE" else f" [{r['status']}]"
                    out(f"{r['memory_id']}  {r['created_at'][:10]}{status}  {safe(r['content'])[:100]}")
                if not records:
                    out("Chưa có ghi chú nào. Thêm: hg note add \"nội dung\"")
            return EXIT_OK
        if sub == "show":
            versions = nb.history(args.id)
            if args.json:
                _print_json(versions, out)
            else:
                for r in versions:
                    out(f"v{r['version']} {r['memory_id']} {r['created_at'][:16]} {r['status']} "
                        f"nguồn={r['source_ref']}\n    {safe(r['content'])}")
            return EXIT_OK
        if sub == "trust":
            nb.trust(args.id)
            out(f"Đã đánh dấu {args.id} là an toàn: HG sẽ gửi ghi chú này cho model (ghi lại trong sổ cái).")
            return EXIT_OK
        if sub == "forget":
            record = nb.forget(args.id, reason=args.reason)
            out(f"Đã thu hồi {record['memory_id']} (vẫn còn trong lịch sử: hg note show {record['memory_id']}).")
            return EXIT_OK
        if sub == "curate":
            from datetime import datetime, timezone
            from hg.memory.curation import CurationInputError, analyze_memories
            try:
                report = analyze_memories(nb.snapshot(), as_of=datetime.now(timezone.utc).isoformat(),
                                          near_duplicate_threshold=args.threshold,
                                          max_pair_comparisons=args.max_comparisons, max_findings=args.max_findings)
            except CurationInputError as exc:
                raise NoteError(str(exc)) from exc
            if args.json:
                _print_json(report, out)
            else:
                out(f"Rà soát chỉ đọc: {report['records_seen']} bản ghi, "
                    f"{report['active_non_working_records']} đang hoạt động, "
                    f"{report['inactive_records_preserved']} bản ghi lịch sử.")
                for title, key in (
                    ("Trùng chính xác", "exact_duplicate_groups"),
                    ("Gần trùng (chỉ là tín hiệu từ vựng)", "near_duplicate_pairs"),
                    ("Mốc thời gian cần xem xét", "staleness_candidates"),
                    ("Mâu thuẫn/divergence cần xem xét", "conflict_candidates"),
                    ("Ứng viên khác subject (chỉ xem xét)", "cross_subject_candidates"),
                ):
                    rows = report[key]
                    out(f"{title}: {len(rows)}")
                    for row in rows:
                        out("  " + ", ".join(row["memory_ids"]) + " — "
                            + row.get("classification", row["type"])
                            + (f" (Jaccard={row['lexical_jaccard']})" if "lexical_jaccard" in row else ""))
                out(f"So sánh {report['comparisons_evaluated']} cặp; giới hạn {report['resource_limits']['max_pair_comparisons']} cặp; "
                    + ("BÁO CÁO BỊ CẮT — cần thu hẹp phạm vi hoặc tăng giới hạn có chủ đích." if report['truncated']
                       else "đã hoàn tất phạm vi so sánh trong giới hạn."))
                out("Không có bản ghi nào bị tự động xóa, gộp, thay thế hoặc phân xử.")
            return EXIT_OK if report["records_seen"] else EXIT_NO_DATA
        if sub == "save-ask":
            from hg.assistant.ask_archive import AskArchiveError, preview_model_derived_save, save_model_derived_content
            try:
                preview = preview_model_derived_save(_home(), args.receipt_id, subject=args.subject, text=args.text)
                if args.confirm is None:
                    if args.json:
                        _print_json(preview, out)
                    else:
                        out("CHƯA LƯU — đây chỉ là bản xem trước.")
                        out(f"Nguồn ASK: {preview['receipt_event_id']} "
                            f"({preview.get('provider') or 'provider không rõ'}:{preview.get('model') or 'model không rõ'})")
                        out(f"Chủ đề: {preview['subject']}")
                        out(f"Nội dung MODEL_DERIVED (nguồn từ model): {preview['content']}")
                        out(f"SHA-256 xác nhận: {preview['confirmation_sha256']}")
                        out("Kiểm tra nội dung rồi chạy lại đúng lệnh với --confirm <SHA-256> để lưu.")
                    return EXIT_OK
                record, created = save_model_derived_content(
                    _home(), args.receipt_id, subject=args.subject, text=args.text, confirm_sha256=args.confirm)
                result = {"created": created, "memory_id": record["memory_id"], "subject": record["subject"],
                          "source_ref": record["source_ref"], "status": record["status"]}
                if args.json:
                    _print_json(result, out)
                else:
                    out(("Đã lưu ghi chú " if created else "Đã có ghi chú ACTIVE từ cùng thao tác ")
                        + f"{record['memory_id']} — MODEL_DERIVED; Chủ Nhân xác nhận quyền lưu, không xác minh tính đúng/sự thật.")
                return EXIT_OK
            except AskArchiveError as exc:
                raise NoteError(str(exc)) from exc

    if command == "check":
        from hg.assistant.check import LABELS_VI, check
        text, _origin = _text_arg(args.text, stdin)
        if text is None:
            out("Dán văn bản cần đối chiếu (Ctrl-D để xong):")
            text = stdin.read()
        result = check(text, Notebook(_home()))
        if args.json:
            _print_json(result, out)
        else:
            if result["directives_in_text"]:
                out("⚠ Văn bản này chứa câu lệnh nhắm vào AI (" + ", ".join(result["directives_in_text"])
                    + ") — có thể là tin nhắn lừa đảo.")
            for r in result["sentences"]:
                tag = LABELS_VI[r["label"]]
                out(f"[{tag}] {safe(r['sentence'])}" if tag else safe(r["sentence"]))
                if r["label"] in {"NOTE", "CONFLICT"}:
                    out(f"    ↳ {r['memory_id']}: {safe(r['note_text'])[:100]}"
                        + (f" — {'; '.join(r['reasons'])}" if r["reasons"] else ""))
        return EXIT_CONFLICT if result["counts"]["CONFLICT"] else EXIT_OK

    if command == "ask":
        from hg.assistant.ask import ask
        home = _home()
        question, _origin = _text_arg(args.question, stdin)
        if question is None:
            out("Nhập câu hỏi (Ctrl-D để gửi):")
            question = stdin.read()
        if not question.strip():
            out("Câu hỏi trống.")
            return EXIT_INPUT
        return _ask(home, question, args, out)

    if command == "summarize":
        return _summarize(args, stdin, out)

    if command == "model":
        return _model(args, out)

    if command == "eval":
        from hg.assistant import evaluate
        home = _home()
        conf, listener, check = _model_parts(home)
        if check["status"] != "READY":
            out(f"Model chưa sẵn sàng: {check}")
            return EXIT_NO_MODEL
        report = evaluate.run(args.spec, router_factory=lambda: cfg.router(conf), listener=listener,
                              model_check=check, release=_release(),
                              progress=lambda qid, r: out(f"{qid} {r['outcome']} {r['seconds']:.1f}s"))
        if args.json_out:
            with open(args.json_out, "w", encoding="utf-8") as stream:
                json.dump(report, stream, ensure_ascii=False, indent=2)
        _print_json({"metrics": report["metrics"], "checks": report["checks"], "verdict": report["verdict"]}, out)
        return EXIT_OK if report["verdict"] == "PASS" else 1
    raise NoteError(f"unknown command {command}")


def _ask(home, question, args, out):
    from hg.assistant.ask import ask
    conf = cfg.load(home)
    listener, check = None, None
    if not args.notes_only and args.provider == "local":
        listener = cfg.attest_listener(conf)
        check = cfg.check_model(conf, cfg.ollama(conf))
    notes_only = args.notes_only or (args.provider == "local" and check["status"] != "READY")
    reason = None if args.notes_only or not check or check["status"] == "READY" else \
        f"model {check['status']}: {check.get('reason', '')} (xem: hg model status)"
    lines = []
    sink = lines.append if args.json else out
    code, receipt = ask(question, notebook=Notebook(home), router_factory=lambda: cfg.router(conf, provider_choice=args.provider),
                        listener=listener, model_check=check, out=sink, color=_color(sys.stdout) and not args.json,
                        notes_only=notes_only, unavailable_reason=reason, max_tokens=conf["max_tokens"],
                        release=_release(), general=getattr(args, "general", False))
    if args.json:
        _print_json(receipt, out)
    return code


def _summarize(args, stdin, out):
    from hg.assistant import summarize as sm
    from hg.assistant.ask import append_receipt, safe
    from datetime import datetime, timezone
    try:
        text, info = sm.read_input(args.path, stdin=getattr(stdin, "buffer", None))
    except sm.InputError as exc:
        out(f"Không tóm tắt được: {exc}")
        return EXIT_INPUT
    if info.get("symlink_target"):
        out(f"(liên kết tới: {info['symlink_target']})")
    home = _home()
    dropped, response = [], None
    if args.model:
        conf = cfg.load(home)
        cfg.attest_listener(conf)
        check = cfg.check_model(conf, cfg.ollama(conf))
        if check["status"] != "READY":
            out(f"Model chưa sẵn sàng ({check['status']}); dùng tóm tắt trích xuất.")
            items, mode = sm.extractive(text, max_sentences=args.max_sentences), "extractive"
        else:
            try:
                items, dropped, response = sm.with_model(text, cfg.router(conf), max_sentences=args.max_sentences,
                                                         strict=args.strict)
                mode = "model"
            except ProviderError as exc:
                out(f"Model lỗi ({exc}); dùng tóm tắt trích xuất.")
                items, mode = sm.extractive(text, max_sentences=args.max_sentences), "extractive"
            except sm.DirectiveInput:
                out("⚠ Văn bản chứa câu lệnh nhắm vào AI — HG không gửi cho model; dùng tóm tắt trích xuất.")
                items, mode = sm.extractive(text, max_sentences=args.max_sentences), "extractive-quarantined"
    else:
        items, mode = sm.extractive(text, max_sentences=args.max_sentences), "extractive"
    rec = sm.receipt(info, mode, items, dropped, response)
    append_receipt(home, "SUMMARY", rec, clock=lambda: datetime.now(timezone.utc))
    if args.json:
        _print_json(dict(rec, items=items), out)
    else:
        for line in sm.render(items, color=_color(sys.stdout)):
            out(safe(line))
        if not items:
            out("Văn bản quá ngắn hoặc không có câu nào đủ nội dung để tóm tắt.")
        if dropped:
            out(f"— đã loại {len(dropped)} câu không neo được vào dòng nguồn (--strict)")
    return EXIT_OK if items else EXIT_NO_DATA


def _model(args, out):
    home = _home()
    conf = cfg.load(home)
    if args.model_command == "status":
        try:
            listener = cfg.attest_listener(conf)
        except cfg.ConfigError as exc:
            listener = {"status": "FAILED", "reason": str(exc)}
        provider = cfg.ollama(conf)
        try:
            check = cfg.check_model(conf, provider)
        except cfg.ConfigError as exc:
            check = {"status": "DIGEST_MISMATCH", "reason": str(exc)}
        report = {"ollama_url": conf["ollama_url"], "model": conf["model"], "listener": listener, "model_check": check}
        if args.json:
            _print_json(report, out)
        else:
            out(f"Ollama: {conf['ollama_url']}  model: {conf['model']}")
            out(f"  model: {check['status']}" + (f" — {check.get('reason')}" if check.get("reason") else "")
                + (f" (digest {str(check.get('digest'))[:12]}…, {'đã ghim' if check.get('pinned') else 'chưa ghim'})"
                   if check["status"] == "READY" else ""))
            out(f"  tiến trình: {listener['status']} — {listener.get('reason', '')}")
            if check.get("available"):
                out("  có sẵn: " + ", ".join(check["available"]))
        if check["status"] == "DIGEST_MISMATCH" or listener["status"] == "FAILED":
            return EXIT_CONFIG
        return EXIT_OK if check["status"] == "READY" else EXIT_NO_MODEL
    if args.model_command == "use":
        conf["model"], conf["model_digest"] = args.name, None
        if args.service_dir:
            conf["ollama_service_dir"] = args.service_dir
        check = cfg.check_model(conf, cfg.ollama(conf))
        if check["status"] != "READY":
            out(f"Không dùng được {args.name}: {check['status']} — {check.get('reason', '')}")
            return EXIT_NO_MODEL
        conf["model_digest"] = check["digest"]
        if conf.get("ollama_service_dir"):
            cfg.attest_listener(conf)
        path = cfg.save(home, conf)
        out(f"Đã chọn {check['model']} và ghim digest {check['digest'][:12]}… ({path})")
        return EXIT_OK


def interactive(stdin=None, out=None):
    """Bare `hg`: one line in, one answer out. '+' saves a note, '/tim' searches, '/q' quits."""
    import argparse
    out = out or (lambda line: print(line, flush=True))
    out(HELP_VI)
    while True:
        try:
            line = input("HG> ")
        except (EOFError, KeyboardInterrupt):
            out("")
            return EXIT_OK
        line = line.strip()
        if not line:
            continue
        if line in {"/q", "/thoat", "/thoát", "/quit"}:
            return EXIT_OK
        if line.startswith("+"):
            ns = argparse.Namespace(command="note", note_command="add", text=[line[1:].strip()], subject=None,
                                    replaces=None, json=False)
            code = run(ns, out=out, stdin=_Prompt())
        elif line.split()[0] in {"/tim", "/tìm"}:
            ns = argparse.Namespace(command="note", note_command="search", query=line.split()[1:] or [""], limit=5, json=False)
            code = run(ns, out=out)
        elif line.split()[0] in {"/kiem", "/kiểm"}:
            ns = argparse.Namespace(command="check", text=line.split()[1:], json=False)
            code = run(ns, out=out, stdin=_Prompt())
        else:
            ns = argparse.Namespace(command="ask", question=[line], notes_only=False, provider="local", json=False,
                                    general=False)
            code = run(ns, out=out, stdin=_Prompt())
        if code not in (EXIT_OK, EXIT_NO_MODEL, EXIT_NO_DATA):
            out(f"(mã thoát {code})")


class _Prompt:
    """stdin stand-in for commands started from the interactive prompt: text came from the owner typing."""

    origin = "prompt"

    def isatty(self):
        return True

    def read(self):
        return ""
