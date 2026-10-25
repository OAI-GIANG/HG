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

MAEP-1.2.0 governance primitives and contract specifications are under `maep/`. Memory & Knowledge's local implementation and MAEP integration adapter are under `memory/`; BrainOrchestrator/runtime provider binding remains pending and is not yet verified.