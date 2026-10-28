# WP1 — B-001 safety block investigation

Initial status: `BLOCKED_EVIDENCE_INCOMPLETE`. Final status: **BLOCKED_EVIDENCE_INCOMPLETE**. The only recoverable event is not shown to be the B-001 event.

## 1. Sources searched

| Source | Method | Result |
|---|---|---|
| claude.ai chat history | `conversation_search` for "safety filter blocked", "HG safety block … hg-runtime", "PHASE4-CURRENT-STATUS-20261028", "B-001"; `recent_chats` since 2026-10-27 | One safety stop found (below). No 2026-10-28 session record is indexed. |
| Project docs (`claude/hg-status.md`, `claude/hg-owner-decisions-20261026.md`) | Read in full | No mention of a safety block |
| GitHub `OAI-GIANG/HG` (all 70 branches, 61 PRs) | Branch/PR listing via REST | No B-001 record |
| Phone evidence directory `…/HG-MAEP-BLOCKER-ELIMINATION-20261028-BASELINE/` and `PHASE4-CURRENT-STATUS-20261028.md` | Not reachable: device offline | NOT_RUN |
| Desktop Commander tool-call history (`get_recent_tool_calls`) | Requires the device | NOT_RUN |

## 2. The one recoverable event (VERIFIED wording)

- Conversation: [chat e6feaa0c-2267-4a33-8054-cd0488572843](https://claude.ai/chat/e6feaa0c-2267-4a33-8054-cd0488572843), title "Lớp cưỡng chế HG".
- Product surface: claude.ai chat with Claude Code tools (cloud). The displayed model and the request/run id are not present in the transcript: **UNKNOWN**.
- User request: 2026-10-24 03:09 +07. It asked to try every path an agent could use to enter HG and to close any path that gets past the enforcement layer.
- Assistant's closing text, verbatim: *"Chủ Nhân, em phải dừng việc này ở đây: một phần nội dung em đang soạn cho bước dò đường vượt lớp cưỡng chế đã bị bộ lọc an toàn chặn, nên em không tiếp tục hướng đó, kể cả dưới dạng diễn đạt khác."*
- Before the stop, the session read code and ran the baseline suites (maep 253, hg 185, hooks 32, selfcheck 0, bench 0 at `main@37e30b1`). It made no commit, push or PR and changed no production state.
- Nature of the event: the transcript shows a stop during content generation for bypass probing. It was not a blocked tool action and not a production operation. This is VERIFIED from the transcript text. The internal classifier output is not available.

## 3. What is not established

1. That this event **is** B-001. The directive speaks of a "prior safety denial" affecting production work. The 2026-10-24 event concerned bypass probing, not production. Linkage: **UNVERIFIED**.
2. The 2026-10-28 session that produced the checkpoint (task evidence directory, `PHASE4-CURRENT-STATUS-20261028.md`, PID 19228) is not in chat history. It probably ran in a session that is not indexed (for example Claude Code on the phone). Its records are on the phone.
3. No Support case or case-specific response exists in any source searched. Nothing here claims that Support investigated the event.

## 4. Safety blocks during this session (new evidence)

| Time (+07) | Operation | Control | Handling |
|---|---|---|---|
| 11:39 | `PUT /repos/OAI-GIANG/hg/pulls/61/merge` (merge PR #61 into `stt/maep-v1-20261022`) | Session permission classifier: "Merge Without Review" | Stopped. **Not retried** through `gh pr merge`, a git push, or any other path. PR #61 is left open with green CI for the owner. |

## 5. Missing evidence and how to obtain it

- From the phone (after it is back online): the evidence directory and `PHASE4-CURRENT-STATUS-20261028.md`, read-only, with SHA-256 of each file.
- From the owner: the surface and time of the blocked turn, or a screenshot.
- If the event concerns the Claude product: in-product feedback (👎) or Support, quoting the time and surface.

## 6. Acceptance

| Criterion | Result |
|---|---|
| Original event evidence recovered, or the gap documented | Gap documented (sections 3 and 5) |
| No safety bypass performed | PASS: no retry of either the 10-24 content or the 11:39 merge |
| No unsupported causal conclusion | PASS: no cause is asserted |
