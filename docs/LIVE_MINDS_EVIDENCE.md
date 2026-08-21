# Live Minds Continuity Evidence

Status: **LIVE_VERIFIED**

Completed: 2026-08-19 17:51:35 UTC

Dataset: **SYNTHETIC_DEMO_ONLY**

ContextPatch completed one real store operation and two real recall operations against the same
configured Mind in three distinct Builder conversations. Both recall requests omitted the approved
disclosure principle. Each official Mind reply was paired to the exact outbound message inside the
official ordered history before its bounded JSON receipt was parsed.

## Verified result

| Check | Result |
|---|---|
| Same Mind used for all calls | PASS |
| Three distinct conversation aliases and IDs | PASS |
| Store receipt reported `stored=true` | PASS |
| Recall A recovered the unpredictable continuity marker or full approved principle | PASS |
| Recall B recovered the unpredictable continuity marker or full approved principle | PASS |
| Recall requests omitted the approved principle | PASS |
| X, LinkedIn and YouTube patch keys matched exactly | PASS |
| Official outbound body hash matched the local request hash | PASS |
| Each official reply followed its request in ordered history | PASS |
| Raw and cleaned response hashes were recorded before parsing | PASS |
| Creator content remained synthetic and bounded | PASS |
| Automatic publishing and automatic credit top-up | OFF |

The complete proof contained exactly three outbound Builder messages: one store, one first recall
and one second recall. Platform delays were handled through read-only official-history recovery;
no stage was blindly resent. The final recovery run sent only the one remaining unsent recall.

## Evidence limitations

- The initial store call's before/after credit readings were not captured, so no historical credit
  delta is claimed for that call.
- This proves one synthetic cross-session continuity workflow on one configured Mind. It does not
  prove universal Minds reliability, real creator demand, publication, revenue or an award.
- Raw API keys, Mind UUID, aliases, conversation IDs, message IDs, request bodies and replies are
  excluded. The local evidence artifact stores only hashes, timestamps, bounded numeric balances
  and boolean verification results.

## Local evidence artifact

The ignored local file `output/live_minds_evidence.json` records:

- `continuity_verified=true`
- `same_mind=true`
- `distinct_conversations=true`
- three strict-schema-valid calls
- three ordered request/reply timestamp pairs
- per-call request, response, alias, conversation and remote-message hashes

The artifact is intentionally excluded from Git because the public document above is sufficient
for judging while the more detailed audit record remains local.
