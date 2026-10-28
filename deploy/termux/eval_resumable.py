"""Resumable run of HG's fixed evaluation with the release's own ask() and score() (F-D2 workaround).

usage: python3 -I -B eval_resumable.py RELEASE_ROOT SPEC.json WORKDIR OUT.json

Every question's receipt is appended to WORKDIR/receipts.jsonl as soon as it is answered, so a run
killed by Android continues where it stopped instead of restarting. Notes live in WORKDIR/home
(a private temporary HG_HOME, never the owner's notes). Scoring is hg.assistant.evaluate.score,
unchanged. The owner's config.json (model + pinned digest + service dir) is copied in.
"""
import json
import os
import shutil
import sys
from pathlib import Path

release, spec_path, work, out = (Path(a) for a in sys.argv[1:5])
sys.path.insert(0, str(release))
from hg.assistant import config as cfg  # noqa: E402
from hg.assistant.ask import ask  # noqa: E402
from hg.assistant.evaluate import score  # noqa: E402
from hg.assistant.notes import Notebook  # noqa: E402

spec = json.loads(spec_path.read_text(encoding="utf-8"))
work.mkdir(mode=0o700, parents=True, exist_ok=True)
home = work / "home"
fresh = not home.exists()
home.mkdir(mode=0o700, exist_ok=True)
nb = Notebook(home)
ids_path = work / "key_to_id.json"
if fresh:
    shutil.copy(Path(os.environ["HOME"]) / ".local/share/hg/assistant/config.json", home / "config.json")
    key_to_id = {}
    for n in spec["notes"]:
        record, _ = nb.add(n["content"], subject=n["subject"], origin="test")
        key_to_id[n["key"]] = record["memory_id"]
    ids_path.write_text(json.dumps(key_to_id))
key_to_id = json.loads(ids_path.read_text())
conf = cfg.load(Path(os.environ["HOME"]) / ".local/share/hg/assistant")
listener = cfg.attest_listener(conf)
check = cfg.check_model(conf, cfg.ollama(conf))
receipts_path = work / "receipts.jsonl"
done = {}
if receipts_path.exists():
    for line in receipts_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            item = json.loads(line)
            done[item["id"]] = item["receipt"]
release_id = release.name
for q in spec["questions"]:
    if q["id"] in done:
        continue
    _code, receipt = ask(q["question"], notebook=nb, router_factory=lambda: cfg.router(conf), listener=listener,
                         model_check=check, out=lambda *_a: None, release=release_id,
                         max_tokens=conf["max_tokens"])
    with receipts_path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({"id": q["id"], "receipt": receipt}, ensure_ascii=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    done[q["id"]] = receipt
    print(q["id"], receipt["outcome"], f"{receipt['seconds']:.1f}s", flush=True)
receipts = [done[q["id"]] for q in spec["questions"]]
report = score(spec, receipts, key_to_id)
report.update(spec=str(spec_path), model_check=check, listener=listener, release=release_id,
              harness="eval_resumable.py (release ask() + evaluate.score)",
              answers=[{"id": q["id"], "question": q["question"], "answer": r.get("answer"),
                        "labels": [s["label"] for s in r.get("sentences", [])]}
                       for q, r in zip(spec["questions"], receipts)])
out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({"metrics": report["metrics"], "checks": report["checks"], "verdict": report["verdict"]},
                 ensure_ascii=False, indent=2))
sys.exit(0 if report["verdict"] == "PASS" else 1)
