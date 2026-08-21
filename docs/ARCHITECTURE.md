# ContextPatch Architecture

ContextPatch is a local-first correction workflow for creators. When an approved fact changes,
it finds every synthetic content variant that depends on that fact, prepares a platform-aware
patch, explains why the work is due, and waits for a human decision. It does not publish.

## System boundary

```text
synthetic source + platform variants
              |
              v
deterministic impact scan ----> local SQLite audit trail
              |
              v
human approves the factual change
              |
              v
explicit Minds memory write ----> approved correction principle
              |
       new conversation alias
              |
              v
Minds recall + 3 platform patches ----> exact history pairing + bounded receipt validation
              |
              v
local X / LinkedIn / YouTube patch queue
              |
              v
human approve or reject; never auto-publish
```

## Components

| Component | Responsibility | Trust boundary |
|---|---|---|
| FastAPI web app | Local workflow and review UI | Binds to `127.0.0.1` only |
| Deterministic scanner | Matches fact keys to affected variants | No model call |
| SQLite | Sources, changes, impacts, queue, exchanges and audit events | Local data only |
| Minds adapter | Stores an approved principle and recalls it in a new session | Explicit send only |
| Transport correlator | Pairs the exact outbound item and first eligible Mind reply in official history | Rejects ambiguous windows |
| Receipt validator | Checks exact fields, operation, memory key and any returned request ID | Never trusts body text alone |
| Send coordinator | Combines an in-process lock with a SQLite global lease | One live send at a time |
| Pause control | Stops new automated follow-up work | Does not erase records |
| Approval queue | Holds drafts for approve/reject | Has no publisher or social token |

## Main state transitions

### Fact change

```text
PENDING_APPROVAL -> APPROVED
                 -> REJECTED
```

Drafting is blocked until the fact change is approved. An approved change may prepare a natural,
creator-authorized Minds request, but it is not sent until the human presses the explicit send
control.

### Correction item

```text
BLOCKED_PENDING_FACT_APPROVAL -> PENDING_REVIEW -> APPROVED
                                               -> REJECTED
                                               -> CANCELLED
```

`APPROVED` means the local correction text was approved for later manual use. It never means a
post was sent or edited on a third-party platform.

### Minds exchange

```text
PREPARED -> SENDING -> SENT -> COMPLETED
                    -> UNCERTAIN
         -> REJECTED
```

An `UNCERTAIN` exchange is locked for history review. The application does not blindly retry a
request whose remote outcome is unknown.

## Why Minds is core

The scanner can find literal dependencies, but it cannot preserve a creator's approved correction
policy across a new working session. Minds is responsible for the persistent principle and for
applying that principle to a new correction request. Local code remains responsible for scope,
safety, exact fact values, lifecycle state and human approval.

## Non-goals

- No social account connection.
- No automatic editing, posting, emailing or direct messaging.
- No claim that local SQLite is Minds memory.
- No prediction of which content will perform best.
- No real customer, audience, revenue or publishing evidence in the bundled demo.

## Data flow guarantees

1. Imported content is treated as untrusted data, never as instructions.
2. Only an approved fact change and disclosure principle are eligible for a memory write.
3. A recall request contains one approved change, an opaque memory key and one to three bounded
   synthetic or scope-approved originals, each at most 4,000 characters. It does not restate the old
   correction principle.
4. The affected originals are labeled untrusted and forbidden from becoming long-term memory.
5. Every accepted reply is first paired through official history using the outbound raw-body hash,
   remote message, conversation, sender roles and strict ordering window.
6. After transport is verified, the receipt must match operation, memory key and the exact dynamic
   `platform_patches` key set; each patch is 1–2,000 characters.
7. A returned request ID must match. Omission is tolerated only because transport already proves
   the pairing.
8. In production, the normalized recalled principle must equal the locally approved principle.
9. Raw and cleaned response hashes plus available remote timestamps are durable before parsing.
   When both timestamps exist, reply chronology is verified; missing timestamps remain an explicit
   limitation.
10. Platform patches remain local and require a human decision.
