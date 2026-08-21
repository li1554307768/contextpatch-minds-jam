# Evidence Status

Last updated: 2026-08-20 (local build phase)

| Claim | Current status | Acceptable evidence |
|---|---|---|
| Synthetic scenario is bundled | `VERIFIABLE_LOCAL` | `data/synthetic_demo.json` |
| Deterministic impact scan works | `VERIFIED_LOCAL` | `make verify`: 36 passed; deterministic service tests |
| Human approval gates fact memory | `VERIFIED_LOCAL` | State-machine tests and audit event sequence |
| Pause blocks follow-up work | `VERIFIED_LOCAL` | Pause tests and local state transition |
| No auto-publish path exists | `VERIFIED_LOCAL` | Source/dependency review: only Minds uses `httpx`; `auto_publish=false` |
| Minds request/history/receipt contract works | `LIVE_VERIFIED` | Mock transport tests plus [LIVE_MINDS_EVIDENCE.md](LIVE_MINDS_EVIDENCE.md) |
| Live cross-session Minds continuity works | `LIVE_VERIFIED` | One store + two recalls, same Mind, three distinct official conversations |
| Local browser workflow works in Chrome | `VERIFIED_LOCAL` | Synthetic load, impact scan, approval, disabled send and Pause/Resume checked |
| 111-second demo media is valid | `VERIFIED_LOCAL` | [DEMO_VIDEO_REPORT.md](DEMO_VIDEO_REPORT.md) |
| Repository secret scan is clean | `VERIFIED_LOCAL` | Custom tree, Git-blob and artifact key-pattern scan: 0 findings |
| Public repository exists | `NOT_CREATED` | Anonymous clone and public URL |
| Public demo video exists | `NOT_UPLOADED` | Public/unlisted URL and processed HD playback |
| Separate second-entry workflow exists | `VERIFIED_PLATFORM_UI` | Logged-in **Submit new BUIDL** opened a fresh organizer disclaimer; no unlimited-entry claim |
| Second BUIDL submitted | `NOT_SUBMITTED` | New success receipt and new public BUIDL URL |
| Real users or publications | `0 / NONE` | Consent-backed user evidence or live platform URL |
| Revenue | `$0` | Non-owner payment, refund and payout evidence |

## Interpretation

- `VERIFIABLE_LOCAL` means the artifact can be inspected on this machine.
- `PENDING_*` means the intended implementation or artifact exists only as a claim until the named
  check runs.
- `NOT_YET_VERIFIED` and `NOT_SUBMITTED` are valid states, not failures to hide.
- A mocked API test is not a live Minds exchange.
- A local approval is not an external publication.
- A submission receipt is not an award, user adoption or revenue.

## Local verification summary

`make verify` completed with 36 passing tests and 86.27% coverage against an 85% threshold. Ruff
reported all checks passed, mypy succeeded on 6 source files, and Bandit reported 0 issues. The
secret scan found 0 findings. A real three-conversation Minds continuity proof also passed; public
repository access, video upload and a second BUIDL remain separate evidence gates.
