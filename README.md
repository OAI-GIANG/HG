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

What is and is not built: `docs/architecture/MIID_AUDIT_AND_CAPABILITY_MATRIX_V1.md`. Grants are not yet anchored to the owner trust root (RT-06); reasoning, model providers and layered memory are the next phase.