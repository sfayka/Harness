# KNO-167 Hosted Ingress Proof — Artifact Contract Correction

## Why This Document Exists

A prior status report for KNO-167 included a PR URL that was **not created by that hosted proof run**. This document corrects the artifact record so completion proof stays auditable and aligned with the Codex Cloud execution contract.

## Correction

For the hosted proof execution that submitted and inspected `task-openclaw-hosted-proof-20260403-191752`:

- **No new branch was created by that run.**
- **No new commit was created by that run.**
- **No new PR was created by that run.**

Because no repository artifact was created in that execution, a historical/previously merged PR must **not** be cited as proof for that run.

## Hosted Proof Scope (What Was Valid)

The hosted ingress proof itself remained valid for backend/dashboard visibility checks:

- submission through hosted ingress (`POST /ingress/openclaw`)
- persisted task visibility in hosted inspection surfaces
- hosted dashboard API visibility for the same task id

This correction is only about repository artifact attribution, not about the hosted API visibility evidence.

## Required Completion Artifact Rule

If a run does not create new repository artifacts, it must be reported explicitly as:

- Repository: present (target repo)
- Branch: **not created in this run**
- Commit SHA: **not created in this run**
- PR URL: **not created in this run**

and it must **not** substitute historical PRs.
