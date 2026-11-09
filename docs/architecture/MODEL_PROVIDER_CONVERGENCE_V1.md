# HG Model Provider Convergence V1

Status: implementation and local contract tests; live local planning verified on Termux.
Scope: OAI-GIANG/HG only. This document records the provider boundary and does not authorize production cutover.

## 1. Contract

HG Brain consumes providers only through ModelRouter. ModelPlanner receives text proposals from the router; those proposals are untrusted data. The planner parses the proposal, derives action/resource/scope/authorization fields from registered adapters, validates every step, and permits at most three plan attempts (MAEP-014). A valid plan is still only a proposal: BrainOrchestrator and MAEP must authorize each effect, ActionGateway rechecks authority at the effect boundary, and AcceptanceGate requires evidence before closure.

## 2. Supported provider choices

| Choice | Provider | Execution | Notes |
|---|---|---|---|
| local | OllamaProvider | loopback-only HTTP; offline | Default; local model must be process-attested and digest-pinned where configured |
| anthropic | AnthropicProvider | HTTPS | Explicit selection only; requires ANTHROPIC_API_KEY |
| deepseek | OpenAICompatibleProvider | HTTPS | Explicit selection only; requires DEEPSEEK_API_KEY |

No provider is a silent fallback for another. The assistant CLI's --provider option selects exactly one provider. The ModelPlanner factory uses planner_provider when configured and otherwise chooses local. An explicit factory argument overrides the config for that call only.

## 3. OpenAI-compatible adapter constraints

- Python standard library transport; no vendor SDK dependency.
- Endpoint must use HTTPS, or HTTP to a literal loopback IP; user-info, query, fragment and dot-dot path segments are rejected.
- Redirects are not followed, preventing credential forwarding to another endpoint.
- Response and error bodies are capped at 4 MiB. Provider error bodies are not disclosed in raised errors or receipts.
- Capability declaration is text input/text output only; streaming, tool calling, and structured output are false until separately qualified.
- API key is read from the environment variable named by configuration (DEEPSEEK_API_KEY by default). The key value must never be stored in HG config, Git, logs, prompts, or acceptance artifacts.
- Unknown token pricing is represented as unknown (cost_known=false, cost_usd=null), never as zero.

## 4. Configuration and use

Configuration keys:
- deepseek_base_url (default https://api.deepseek.com)
- deepseek_model (default deepseek-flash)
- deepseek_api_key_env (default DEEPSEEK_API_KEY)
- planner_provider (null by default; null means local)

The config loader rejects planner_provider values other than null, local, anthropic, or deepseek. hg.assistant.config.build_planner() returns a ModelPlanner whose router is built from the selected provider. It does not execute a task or bypass MAEP.

Example in Python:

    from hg.assistant import config
    planner = config.build_planner(config.load(home), provider_choice="local")

The governed execution path is:

    ModelPlanner -> ModelRouter -> provider
      -> parse and validate proposal
      -> BrainOrchestrator
      -> MAEP authorization / TaskGrantIssuer
      -> ActionGateway
      -> evidence / AcceptanceGate / closure

## 5. Acceptance and limitations

- Unit tests cover provider wire format, endpoint constraints, redirects, bounded responses, redaction, error mapping, cost unknown, provider config, and planner factory selection.
- Termux WP2 verification used a digest-pinned local Qwen model and a separate runtime directory. It recorded a successful model call, one authorized write, exact read-back, evidence, gate PASS, and CLOSED_VERIFIED task state.
- No live DeepSeek request is claimed: no DEEPSEEK_API_KEY was present during verification. Remote provider behavior is covered by deterministic test doubles, not a live API test.
- WP2 was a sandbox runtime exercise, not a production service integration or deployment.
