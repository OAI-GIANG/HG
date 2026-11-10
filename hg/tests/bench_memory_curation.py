"""One benchmark run per process: python bench_curation.py MODE N  (synthetic records only)."""
import json, resource, sys, time
from hg.memory.curation import analyze_memories

mode, n = sys.argv[1], int(sys.argv[2])


def make(i, subject, layer="SEMANTIC", kind="NOTE"):
    return {"memory_id": f"M-{i:07d}", "layer": layer, "kind": kind, "subject": subject,
            "content": f"ghi chú số {i} về lịch bảo dưỡng xe và thiết bị gia đình mã {i * 7919 % 100003}",
            "value": None, "status": "ACTIVE"}


if mode == "same":          # worst case: every record on one subject
    recs = [make(i, "chung") for i in range(n)]
elif mode == "distinct":    # Notebook-like: auto/explicit subjects are unique among ACTIVE notes
    recs = [make(i, f"s{i}") for i in range(n)]
elif mode == "brain":       # Brain-like: 3 episodes per task subject
    recs = [make(i, f"task:T-{i // 3}", layer="EPISODIC", kind="EVENT") for i in range(n)]
else:
    raise SystemExit("mode")
input_bytes = len(json.dumps(recs, ensure_ascii=False).encode("utf-8"))
groups = {}
for r in recs:
    groups[r["subject"]] = groups.get(r["subject"], 0) + 1
pairs = sum(k * (k - 1) // 2 for k in groups.values())
t0 = time.perf_counter()
report = analyze_memories(recs, as_of="2026-11-01T00:00:00Z")
t1 = time.perf_counter()
text = json.dumps(report, ensure_ascii=False, indent=2)
t2 = time.perf_counter()
print(json.dumps({
    "mode": mode, "n": n, "pairs_per_pass": pairs, "input_bytes": input_bytes,
    "analyze_s": round(t1 - t0, 3), "serialize_s": round(t2 - t1, 3), "output_bytes": len(text.encode("utf-8")),
    "conflicts": len(report["conflict_candidates"]), "near": len(report["near_duplicate_pairs"]),
    "cross_subject": len(report["cross_subject_candidates"]),
    "comparisons_evaluated": report["comparisons_evaluated"],
    "truncated": report["truncated"], "resource_limits": report["resource_limits"],
    "peak_rss_mb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1),
}), flush=True)
