# Competitive Differentiation

ContextPatch is not another cross-posting scheduler. It focuses on the maintenance problem that
appears after content has already been repurposed.

| Category | Typical job | Missing layer | ContextPatch |
|---|---|---|---|
| Social scheduler | Publish one campaign to several channels | Does not preserve an approved correction policy across future sessions | Builds local correction drafts only; never publishes |
| Generic AI rewriter | Rewrite one prompt into several formats | May change facts or forget a prior disclosure rule | Grounds every patch in an explicit old-to-new fact and recalled principle |
| CMS redirect/versioning | Update one owned web property | Does not find copies in platform-specific variants | Maps one source fact to X, LinkedIn and YouTube versions |
| Search-and-replace tool | Replace literal strings | Cannot explain disclosure intent or WHY NOW | Deterministic impact scan plus persistent, human-approved policy |
| Monitoring alert | Notify that content may be stale | Stops before a review-ready correction | Produces bounded drafts and queues them for approval |

## Defensible product decisions

1. **Corrections, not generation volume.** The value is reducing stale or misleading claims after a
   fact changes, not producing more posts.
2. **Minds remembers principles, not raw inbox data.** The durable asset is the creator's approved
   correction policy.
3. **Deterministic scope before model judgment.** Fact-key matching identifies affected versions;
   the Mind handles continuity and platform-aware phrasing.
4. **No auto-publish.** Safety is enforced by the absence of a publisher, not only by a prompt.
5. **Evidence is explicit.** Mocked tests, live Minds proof, human approval and actual publication
   are reported as different events.

## Honest limitations

- The demo uses a small synthetic dataset; it does not prove recall or precision at creator scale.
- Literal fact-key mapping requires disciplined content metadata or later extraction work.
- Platform rules and edit capabilities vary; ContextPatch intentionally leaves final publication to
  the account owner.
- Persistent memory improves consistency but cannot replace factual verification or legal review.
