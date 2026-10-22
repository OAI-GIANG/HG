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

MAEP V1 governance primitives and contract specifications are implemented under `maep/`. Runtime integration with BrainOrchestrator remains pending and is not yet verified.