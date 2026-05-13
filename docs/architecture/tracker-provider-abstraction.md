# Tracker Provider Abstraction

## Status

Design backlog for Proofline v2.

Linear remains the v1 intended-work provider. This document defines the minimum abstraction needed for future tracker providers without changing `TaskEnvelope` or turning Proofline into a project-management product.

## Problem

Proofline currently treats Linear as the live source of intended structured work. That is the right v1 default because it keeps the product concrete: Linear supplies work intent, GitHub supplies code artifact proof, and Proofline decides whether completion is acceptable.

The v2 risk is that Linear semantics leak into core completion truth. If every future tracker is forced through Linear-shaped names, Proofline will become harder to adapt to GitHub Issues, Jira, or other tracker-backed work queues. If the abstraction is too broad, Proofline drifts into a generic PM integration layer.

The abstraction should therefore normalize tracker facts only far enough for reconciliation.

## Boundary

Proofline v2 should model tracker state as external facts, not as core task truth.

- `TaskEnvelope` remains the canonical task contract.
- tracker providers supply intended-work facts for reconciliation.
- provider-specific fields stay in provider payloads, extensions, or capability metadata.
- tracker state can block, require review, or support acceptance, but it does not directly authorize completion.
- tracker adapters are read-only for reconciliation by default.
- writeback, comments, status changes, and workflow mutations are explicit provider capabilities, not baseline provider requirements.

## Where Linear Assumptions Exist Today

Linear-specific assumptions currently appear in these places:

- public docs that describe Linear as the intended-work source of truth
- live dry-run and reset flows that fetch or update Linear issues
- `linear_facts` payloads used as normalized external facts
- mismatch classes such as `linear_record_not_found` and `linear_state_conflict`
- demo fixtures and read models that use Linear issue identifiers
- setup and secret-management docs that treat `LINEAR_API_KEY` as the tracker credential

These are acceptable v1 assumptions. The v2 preparation is to add a provider-neutral fact shape alongside the existing Linear-specific contract, not to remove Linear support.

## Provider Contract

A tracker provider should expose this narrow interface:

```text
fetch_record(external_ref) -> raw provider record
normalize_record(raw_record) -> TrackerRecordFacts
map_status(record_facts) -> TrackerStatusFacts
list_links(record_ref) -> TrackerLinkFacts
list_comments(record_ref) -> TrackerCommentFacts, when explicitly requested
capabilities() -> TrackerProviderCapabilities
```

The provider contract is intentionally read-oriented. Mutation should be modeled as a separate capability because reconciliation can remain useful even when Proofline cannot or should not write back to the tracker.

## Normalized Tracker Facts

The provider-neutral fact model should contain only facts needed for Proofline reconciliation:

- `provider`: `linear`, `github_issues`, `jira`, `trello`, or another explicit provider key
- `record_id`: provider-native stable ID when available
- `record_key`: human-facing issue key or number
- `url`: canonical provider URL
- `title`: current title or summary
- `description`: current body or description, when available
- `status_name`: provider-native status name
- `status_category`: provider-neutral lifecycle category
- `assignees`: normalized display or account identifiers
- `labels`: normalized label names
- `links`: external artifact or related-work links
- `comments_summary`: optional summary of comments considered during reconciliation
- `timestamps`: provider timestamps relevant to freshness and review
- `provenance`: fetch time, provider, credential scope, and normalization version
- `raw_ref`: pointer or digest for the raw provider payload when retained

The initial `status_category` vocabulary should stay small:

- `unknown`
- `open`
- `active`
- `blocked`
- `in_review`
- `done`
- `canceled`

Provider-native status names remain available for audit, but Proofline policy should reason over the normalized category where possible.

## First Providers

### Linear

Linear is the reference provider and v1 default. Existing Linear facts and live dry-run behavior should continue to work.

### GitHub Issues

GitHub Issues is the best first v2 expansion because Proofline already depends on GitHub for artifact proof. It would test whether one provider can supply both intended-work facts and artifact facts without collapsing those roles.

The boundary must remain explicit:

- GitHub Issues are intended-work tracker facts.
- GitHub pull requests, commits, reviews, branches, and checks are artifact facts.
- a single vendor can provide both classes of facts, but Proofline should not merge their meanings.

### Jira

Jira is a later enterprise provider. It is valuable, but it should come after the provider-neutral model has been proven against GitHub Issues.

### Trello

Trello should stay lower priority. It is useful mainly because some orchestrators support it, but its workflow model is too loose to drive early Proofline policy design.

## Reconciliation Mapping

Tracker facts feed reconciliation by answering these questions:

- does the intended-work record exist?
- does the record still describe the same task?
- does the tracker state contradict Proofline lifecycle state?
- does the tracker point at expected artifacts or execution context?
- does the tracker state require review before acceptance?

Provider-neutral mismatch categories should be introduced alongside existing Linear-specific ones:

- `tracker_record_not_found`
- `tracker_state_conflict`
- `tracker_identity_conflict`
- `tracker_link_conflict`
- `tracker_status_unknown`

The existing Linear-specific mismatch names may remain as compatibility aliases or provider-specific detail fields.

## Minimal Preparatory Refactor

The smallest useful implementation step is to introduce a provider-neutral tracker-facts projection alongside existing `linear_facts`.

Recommended shape:

- keep accepting `linear_facts` for v1 compatibility
- add a normalized `tracker_facts` read/projection object in evaluation input or external facts
- map existing Linear facts into `tracker_facts` internally
- keep persistence/read-model output backward compatible
- do not add provider-specific fields to `TaskEnvelope` core

This refactor gives Proofline a stable target for GitHub Issues without breaking the current Linear path.

## Out Of Scope

This abstraction does not include:

- a generic PM dashboard
- always-on tracker polling
- universal workflow-state modeling
- task planning or decomposition across trackers
- provider writeback as a baseline requirement
- replacing Linear in v1
- changing `TaskEnvelope` to mirror every provider
- accepting tracker `done` as proof of completion

## Acceptance Rule

Tracker reconciliation can support acceptance only when it agrees with Proofline policy and required evidence. A tracker saying "done" remains advisory until Proofline verifies intent, evidence, lifecycle policy, and artifact facts.
