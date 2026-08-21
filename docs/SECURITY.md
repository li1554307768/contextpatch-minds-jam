# Security and Human-Control Model

ContextPatch is deliberately designed as a correction assistant, not a publishing agent.

## Hard controls

- **No publisher exists:** the project contains no X, LinkedIn or YouTube write integration.
- **Human approval first:** a fact change must be approved locally before a correction principle
  can be sent to Minds.
- **Explicit Minds send:** preparing a creator-authorized request never sends it.
- **Pause is fail-closed:** Pause prevents new follow-up work while preserving the audit trail.
- **Credit floor:** live Minds calls stop at the configured floor; the floor cannot be set below 10.
- **Unknown remote outcome:** a timeout or selected server errors become `UNCERTAIN`; inspect
  official history before any retry.
- **Single-flight live send:** an in-process lock and SQLite global send lease prevent concurrent
  workers from sending separate live requests at the same time.
- **Transport before content:** official history must bind the outbound item to the first eligible
  `senderType=0` reply before response content is parsed.
- **Bounded receipt contract:** unexpected fields, conflicting IDs and invalid types are rejected.
  A body may omit the redundant request ID only after transport has already been verified.
- **Local binding:** the demo server is intended for `127.0.0.1`, not a public interface.

## Threat model

| Threat | Control | Residual risk |
|---|---|---|
| Prompt injection inside imported text | Values are quoted as untrusted data; common injection phrases are flagged | Pattern matching cannot detect every novel attack |
| Hallucinated correction | Exact old/new facts and bounded originals remain local; each platform patch is only a draft | Human reviewer can still approve a bad draft |
| Duplicate remote send | Stable hashes, in-process lock, SQLite global lease and uncertain-outcome lock | Manual operator could bypass the workflow outside the app |
| Wrong conversation reply | Match outbound raw hash/reference, `messageId` or `id`, conversation ID, sender role and strict ordering window | Upstream API behavior can change |
| Secret disclosure | `.env` is ignored; docs and demo contain placeholders only | Screenshots or manual uploads may leak secrets if not reviewed |
| Unauthorized publishing | No social write adapters or access tokens | Copying approved text to a platform is a separate human action |
| Stale correction | Due time and WHY NOW are visible in the queue | The creator may still defer a critical correction |

## Data minimization

The bundled scenario is fully synthetic. A live deployment should store only the content needed to
identify affected variants and produce a correction. Do not store passwords, cookies, social access
tokens, payment data or identity documents.

The Minds request should contain only:

- an opaque memory key;
- one approved old-to-new fact change;
- one approved disclosure principle; and
- one to three synthetic or scope-approved affected originals, each at most 4,000 characters and
  explicitly excluded from long-term memory; and
- an explicit instruction not to publish or contact anyone.

## Operational checklist

Before a live Minds call:

1. Verify the intended Mind UUID without exposing it in screenshots or logs.
2. Confirm the fact and disclosure principle are human-approved.
3. Confirm Pause is off and the credit balance is above the floor.
4. Check the prepared request for injection flags.
5. Confirm no active SQLite send lease exists.
6. Send once. On timeout, inspect history; do not resend.

Before copying a patch to a platform:

1. Re-check the source of truth.
2. Confirm the platform variant is actually affected.
3. Review the full replacement text, not only the highlighted diff.
4. Preserve legally required disclosures.
5. Publish manually under the account owner's control.

## Known limitations

- String-based injection detection is defense-in-depth, not a complete content firewall.
- Local approval proves only that a UI action occurred; it does not prove legal authority to change
  someone else's content.
- A verified Minds reply proves an API exchange, not that the correction is factually correct.
- A receipt body is never accepted through a production copy-paste endpoint; transport evidence is
  required first.
- If Builder omits request or reply timestamps, ContextPatch cannot prove wall-clock ordering and
  reports that limitation instead of inventing a time.
- The local demo has no authentication because it is not intended for public exposure.
