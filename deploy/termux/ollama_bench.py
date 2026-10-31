#!/usr/bin/env python3
"""Raw-data benchmark for the local Ollama API (standalone, standard library only).

  python3 -I -S ollama_bench.py --out DIR [--url http://127.0.0.1:11434] [--model qwen3:1.7b]
          [--endpoint chat|generate|both] [--runs 3] [--num-thread 4] [--num-ctx 4096]
          [--prompt TEXT] [--rss-pid PID ...] [--timeout 600]

For every run it keeps the exact request and every NDJSON line as received (DIR/run-*.ndjson, with
SHA-256 in the report), and measures with time.monotonic():
  t0      immediately before the request is sent
  TTFB    first byte of the response body
  TTFT    first chunk whose generated text is non-empty: message.content (/api/chat) or response
          (/api/generate); message.thinking is timed separately and never counts as TTFT
Generation TPS = eval_count / (eval_duration / 1e9) from the final chunk; prompt TPS likewise from
prompt_eval_*. total_duration is reported but never used for TPS. A run whose final chunk lacks
these fields gets tps = null, not an estimate.
Cold/warm is observed, not assumed: /api/ps before each run says whether the model was loaded, and
load_duration is recorded. Nothing here unloads or changes models. Only numeric loopback URLs are
accepted, and no HTTP proxy is used (http.client ignores proxy variables).
"""
import argparse
import hashlib
import http.client
import json
import os
import platform
import sys
import time
from ipaddress import ip_address
from urllib.parse import urlsplit

DEFAULT_PROMPT = "Giải thích ngắn gọn bằng tiếng Việt: vì sao bầu trời có màu xanh?"


def loopback(url):
    parts = urlsplit(url)
    try:
        ok = parts.scheme == "http" and parts.hostname and ip_address(parts.hostname).is_loopback
    except ValueError:
        ok = False
    if not ok or parts.username or parts.password:
        raise SystemExit("url must be http://<numeric loopback IP>:<port>")
    return parts.hostname, parts.port or 80


def get_json(host, port, path, timeout):
    conn = http.client.HTTPConnection(host, port, timeout=timeout)
    try:
        conn.request("GET", path)
        resp = conn.getresponse()
        body = resp.read()
        return resp.status, json.loads(body) if body else None
    finally:
        conn.close()


def rss_kib(pid):
    try:
        with open(f"/proc/{pid}/status", encoding="ascii", errors="replace") as stream:
            for line in stream:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1])
    except OSError:
        return None
    return None


def generated_text(endpoint, chunk):
    if endpoint == "chat":
        message = chunk.get("message") or {}
        return message.get("content") or "", message.get("thinking") or ""
    return chunk.get("response") or "", chunk.get("thinking") or ""


def one_run(host, port, endpoint, request, raw_path, timeout):
    body = json.dumps(request, ensure_ascii=False).encode("utf-8")
    conn = http.client.HTTPConnection(host, port, timeout=timeout)
    result = {"endpoint": endpoint, "request": request, "raw_file": os.path.basename(raw_path), "errors": []}
    ttfb = ttft = first_thinking = None
    final, chunks, empty = None, 0, 0
    digest = hashlib.sha256()
    with open(raw_path, "xb") as raw:
        t0 = time.monotonic()
        try:
            conn.request("POST", f"/api/{endpoint}", body=body, headers={"Content-Type": "application/json"})
            resp = conn.getresponse()
            result["http_status"] = resp.status
            while True:
                line = resp.readline()
                now = time.monotonic() - t0
                if not line:
                    break
                if ttfb is None:
                    ttfb = now
                raw.write(line)
                digest.update(line)
                try:
                    chunk = json.loads(line)
                except ValueError:
                    result["errors"].append({"at_s": now, "error": "non-JSON line"})
                    continue
                chunks += 1
                if "error" in chunk:
                    result["errors"].append({"at_s": now, "error": str(chunk["error"])[:200]})
                text, thinking = generated_text(endpoint, chunk)
                if thinking and first_thinking is None:
                    first_thinking = now
                if text.strip() and ttft is None:
                    ttft = now
                if not text and not thinking and not chunk.get("done"):
                    empty += 1
                if chunk.get("done"):
                    final = chunk
        except (OSError, http.client.HTTPException) as exc:
            result["errors"].append({"error": f"{exc.__class__.__name__}: {exc}"[:200]})
        finally:
            result["wall_s"] = time.monotonic() - t0
            conn.close()
    result.update(raw_sha256=digest.hexdigest(), chunks=chunks, empty_chunks=empty, ttfb_s=ttfb, ttft_s=ttft,
                  first_thinking_s=first_thinking)
    if final:
        fields = ("eval_count", "eval_duration", "prompt_eval_count", "prompt_eval_duration", "load_duration",
                  "total_duration", "done_reason")
        result.update({k: final.get(k) for k in fields})
        ec, ed = final.get("eval_count"), final.get("eval_duration")
        pc, pd = final.get("prompt_eval_count"), final.get("prompt_eval_duration")
        result["generation_tps"] = ec / (ed / 1_000_000_000) if isinstance(ec, int) and isinstance(ed, int) and ed > 0 else None
        result["prompt_tps"] = pc / (pd / 1_000_000_000) if isinstance(pc, int) and isinstance(pd, int) and pd > 0 else None
    else:
        result["errors"].append({"error": "no final (done=true) chunk"})
        result["generation_tps"] = result["prompt_tps"] = None
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", required=True)
    parser.add_argument("--url", default="http://127.0.0.1:11434")
    parser.add_argument("--model", default="qwen3:1.7b")
    parser.add_argument("--endpoint", choices=("chat", "generate", "both"), default="both")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--num-thread", type=int, default=4)
    parser.add_argument("--num-ctx", type=int, default=4096)
    parser.add_argument("--prompt", default=DEFAULT_PROMPT)
    parser.add_argument("--think", action="store_true", help="request thinking (timed separately)")
    parser.add_argument("--rss-pid", type=int, action="append", default=[])
    parser.add_argument("--timeout", type=float, default=600)
    args = parser.parse_args(argv)
    host, port = loopback(args.url)
    os.makedirs(args.out, mode=0o700, exist_ok=False)
    report = {"tool": "hg-ollama-bench-1", "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
              "machine": platform.machine(), "kernel": platform.release(), "python": platform.python_version(),
              "url": args.url, "model": args.model, "options": {"num_thread": args.num_thread, "num_ctx": args.num_ctx},
              "think": args.think, "cpu_count": os.cpu_count(), "runs": []}
    try:
        report["version"] = get_json(host, port, "/api/version", 30)[1]
        tags = get_json(host, port, "/api/tags", 30)[1] or {}
    except (OSError, http.client.HTTPException, ValueError) as exc:
        report["error"] = f"Ollama unreachable: {exc.__class__.__name__}"
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
        return 3
    model = next((m for m in tags.get("models", []) if m.get("name") in (args.model, f"{args.model}:latest")), None)
    report["model_digest"] = model.get("digest") if model else None
    if model is None:
        report["error"] = "model not pulled"
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
        return 3
    endpoints = ("chat", "generate") if args.endpoint == "both" else (args.endpoint,)
    for i in range(args.runs):
        for endpoint in endpoints:
            ps = get_json(host, port, "/api/ps", 30)[1] or {}
            loaded = any(m.get("name") == model["name"] for m in ps.get("models", []))
            options = {"num_thread": args.num_thread, "num_ctx": args.num_ctx}
            if endpoint == "chat":
                request = {"model": model["name"], "messages": [{"role": "user", "content": args.prompt}],
                           "stream": True, "think": args.think, "options": options}
            else:
                request = {"model": model["name"], "prompt": args.prompt, "stream": True, "think": args.think,
                           "options": options}
            rss_before = {pid: rss_kib(pid) for pid in args.rss_pid}
            run = one_run(host, port, endpoint, request, os.path.join(args.out, f"run-{i + 1}-{endpoint}.ndjson"),
                          args.timeout)
            run.update(index=i + 1, model_loaded_before=loaded, start="warm" if loaded else "cold",
                       rss_kib_before=rss_before, rss_kib_after={pid: rss_kib(pid) for pid in args.rss_pid})
            report["runs"].append(run)
    text = json.dumps(report, ensure_ascii=False, sort_keys=True, indent=1)
    with open(os.path.join(args.out, "report.json"), "x", encoding="utf-8") as stream:
        stream.write(text + "\n")
    print(text)
    return 0 if all(r["generation_tps"] is not None and not r["errors"] for r in report["runs"]) else 1


if __name__ == "__main__":
    sys.exit(main())
