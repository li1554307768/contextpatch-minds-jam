# Minds Integration Contract

## Purpose

Minds supplies the persistent correction layer. It remembers an explicitly approved correction
principle and recalls that principle in a new conversation when a related fact changes again.

Local code supplies the guardrails: exact facts, affected-version discovery, natural request
construction, credit checks, official-history pairing, bounded receipt validation, Pause and human
approval.

## Environment variables

```dotenv
CONTEXTPATCH_MINDS_API_KEY=
CONTEXTPATCH_MIND_ID=
CONTEXTPATCH_MINDS_BASE_URL=https://api.build.hellominds.ai
CONTEXTPATCH_CREDIT_FLOOR=10
```

Never commit real values. The repository example must remain blank.

## Two-session proof protocol

### Session A: store an approved principle

After the creator approves a factual change, ContextPatch prepares a natural,
creator-authorized `store_principle` request. It includes the old fact, new fact and approved
disclosure principle. A human explicitly sends it. The reply is accepted only after the official
history proves which remote response belongs to that outbound request; the bounded receipt must
then report `stored: true`.

### Session B: recall without restating the principle

A second alias is used for a new conversation. ContextPatch sends one change, the same opaque memory
key and one to three bounded affected originals, but does not include the previously approved
principle. Every original must be synthetic or explicitly scope-approved and no longer than 4,000
characters. The request labels these originals untrusted and forbids storing them as long-term
memory.

A valid reply must return the recalled principle, a `platform_patches` object whose keys exactly
match the requested platform set, plus a concise WHY NOW explanation. Every patch must contain
1–2,000 characters. Missing, duplicate or extra platform keys are rejected. In the production
workflow, the normalized recalled principle must exactly equal the locally approved principle.

This is the meaningful continuity test: the new session receives less context than the first one,
yet the Mind can apply the prior approved boundary.

## Natural request boundary

The Mind receives a short, creator-authorized private memory request. It explains the human
decision, states that neither ContextPatch nor the Mind may contact or publish, and quotes a small
structured request containing:

- `schema_version`
- `request_id`
- `operation`
- `memory_key`
- `security_boundary`
- `data`

Imported values are explicitly described as untrusted quoted facts. Affected originals are marked
as temporary drafting context that must not become long-term memory. A human-readable request
reference and receipt marker support reliable remote correlation without making an internal
protocol prefix the product's value proposition.

## Reply verification

A reply is not accepted merely because it looks plausible. ContextPatch verifies:

1. the exact outbound request reference and raw-body hash in ordered official history;
2. the remote `messageId` or `id` plus conversation ID when supplied by Builder;
3. outbound `senderType=1` and the first eligible Mind reply with `senderType=0`;
4. a closed ordering window: a later user message before the reply invalidates the pairing;
5. raw and cleaned response hashes plus available remote request/reply timestamps, persisted before
   parsing;
6. reply-after-request chronology when both remote timestamps are available, with missing time
   evidence reported as a limitation;
7. the exact allowed receipt fields, operation, memory key, dynamic platform key set and size
   limits;
8. exact normalized equality between the recalled and locally approved principle in production;
   and
9. uniqueness hashes for outbound semantics and accepted responses.

The receipt normally includes the local request ID. If official transport correlation is already
verified, the body may omit that redundant field. A present but wrong request ID is always rejected.
There is no production endpoint for manually pasting a response body.

An in-process lock plus a SQLite global send lease permits only one live send at a time, including
across local worker processes. If a timeout or ambiguous server failure occurs, status becomes
`UNCERTAIN`. ContextPatch only checks official history; it does not resend. If the conversation
itself cannot be proven, the request remains locked.

## Evidence boundary

The repository demonstrates the protocol and supports mocked contract tests. A live proof completed
on 2026-08-19 UTC after all of the following were captured without secrets:

- two distinct aliases and remote conversation IDs;
- one verified store reply;
- one verified recall reply from the new conversation;
- exact ordered-history linkage;
- credit change and timestamp; and
- a redacted evidence report reviewed by a human.

The result is documented in [LIVE_MINDS_EVIDENCE.md](LIVE_MINDS_EVIDENCE.md). See also
[EVIDENCE_STATUS.md](EVIDENCE_STATUS.md) and [REAL_EVIDENCE_TEMPLATE.md](REAL_EVIDENCE_TEMPLATE.md).
