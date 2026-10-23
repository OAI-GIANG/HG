# HG

HG is an independent software product. This repository is the canonical source for HG.

## Functional boundaries

- **HG Brain** — BrainOrchestrator; the single coordination authority.
- **Memory & Knowledge** — owns memory, knowledge, and history.
- **Creativity & Research** — owns research workflows, hypotheses, and proposals.
- **Tools & Automation** — owns tool integration and execution mechanisms.
- **Security & Verification** — owns security policy, verification, and audit.

## Cross-cutting governance

MAEP applies across task intake, authorization, execution, evidence review, acceptance, and closure. It is not a sixth functional domain.

MAEP V1 governance primitives and contract specifications are implemented under `maep/`.

## Runtime (in-process)

`hg/` holds the first runtime: BrainOrchestrator (`hg/brain/`), the tool execution boundary (`hg/tools/`) and acceptance (`hg/verification/`), assembled in `hg/runtime.py` on top of the task-state owner `maep/task_store.py`. Python standard library only, offline.

```sh
python -m hg selfcheck                                  # end-to-end check in a temp dir
python -m unittest discover -s maep/tests -v
python -m unittest discover -s hg/tests -t . -v
```

Grants are anchored to the owner manifest on `main` (RT-06). The intelligence layer -- model router, planner, memory, context, research, options, code tools, learning loop, benchmark, health -- is in `hg/` (MIID Phase D); a live model is optional and not configured here. What is and is not built: `docs/architecture/MIID_AUDIT_AND_CAPABILITY_MATRIX_V1.md`, `docs/architecture/MIID_PHASE_D_RECORD_V1.md`.