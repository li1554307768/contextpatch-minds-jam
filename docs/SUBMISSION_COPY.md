# Submission Copy

All copy below is English-first and ready to paste after the external rules and evidence gates are
cleared.

## Name

**ContextPatch**

## Tagline

**The persistent correction layer for creators.**

## Track

**Content Repurposing Across Platforms**

## Short description

ContextPatch remembers a creator's approved correction principles, finds every affected X,
LinkedIn and YouTube variant when a fact changes, and prepares human-reviewed patches with a clear
WHY NOW. It never posts automatically.

## Problem

Creators repurpose one launch, offer or announcement into many platform-specific versions. When a
fact such as the launch date changes, those copies become inconsistent. A manual search is easy to
miss, while a generic rewrite model may overwrite context or forget the creator's prior public-
correction policy.

## Solution

ContextPatch maps source facts to each repurposed version. A deterministic scan finds affected
content. After the creator approves the new fact, a Mind stores the approved correction principle.
In a separate session, the Mind recalls that principle and applies it to bounded X, LinkedIn and
YouTube drafts. Every draft stays in a local review queue. Pause stops follow-up work, and no social
publisher exists in the application.

## Why Minds is essential

The durable value is not one rewrite. It is continuity: the creator should not have to restate how
to correct sensitive claims every time a new variant appears. Minds persists the approved principle
across conversation aliases and supplies the recalled policy, draft and WHY NOW explanation. Local
code first pairs the exact outbound item and Mind reply in official ordered history, persists raw
and cleaned hashes, then validates the bounded receipt before any draft is accepted.

## Technical summary

- Python 3.10+, FastAPI, Jinja, SQLite and vanilla browser UI.
- Deterministic fact-key impact matching before any model call.
- Minds Builder API adapter with credit floor and explicit-send workflow.
- Natural creator-authorized Minds requests, strict remote history pairing, bounded receipts and
  timeout lockout without blind resend.
- Exact `platform_patches` keys for the affected X, LinkedIn and YouTube originals.
- Normalized recalled-principle equality, outbound raw-hash verification, and a process lock plus
  SQLite global send lease.
- Human approval for facts and drafts; no platform write tokens or auto-publish path.
- Fully synthetic demo data.

## Safety statement

ContextPatch treats imported content as untrusted data. It sends only an approved fact change and
correction principle to Minds, requires exact official-history pairing plus a bounded receipt, and
never connects to a social publishing API. `APPROVED` means approved for manual use, not posted.

## Viability hypothesis

The target user is an independent course, membership or sponsored-content creator who republishes
the same factual claim across several channels. ContextPatch can begin as a free local content audit;
a later **$9–19/month** team plan could add shared approvals, multiple libraries and evidence exports.
This path is a hypothesis only: the project currently has **0 real users, 0 paying users, $0 revenue,
and no verified willingness to pay**. It does not create a Payhip product or collect payment.

## Demo scenario

Fictional creator Avery moves a workshop launch from September 30 to October 7. Price, session count
and recording access remain unchanged. ContextPatch identifies the affected X, LinkedIn and YouTube
copies, recalls the approved principle to make a visible public correction rather than a silent
edit, and returns exactly three platform-specific date patches for review.

## Evidence statement

The bundled data and video are synthetic. One live Builder proof used the same configured Mind in
three distinct official conversations: one approved-principle store and two new-session recalls.
Both recalls recovered the unpredictable continuity marker or full approved principle without that
principle being repeated in the recall request. Exact outbound/history hashes, strict receipts and
ordered timestamps were verified before the result was accepted. This does not claim real users,
publication, revenue or an award.

## Link placeholders

- Product: `LOCAL_DEMO_OR_DEPLOYED_URL`
- Repository: `PUBLIC_REPOSITORY_URL`
- Demo video: `PUBLIC_VIDEO_URL`
- Technical documentation: `REPOSITORY_URL/tree/main/docs`
