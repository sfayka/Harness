# Execution Packet

## Status

Design/spec only. This document does not add schema validation, API behavior, storage, or an importer.

Addresses: [GitHub issue #412](https://github.com/sfayka/Proofline/issues/412)

## Purpose

Define a lightweight Proofline Execution Packet: a portable bundle that connects user intent, specification, plan, task breakdown, acceptance criteria, validation commands, required evidence, and linked external artifacts.

The packet is inspired by spec-driven development tools such as GitHub Spec Kit, but Proofline does not depend on Spec Kit. Spec Kit, a human-authored plan, a Linear issue, a GitHub issue, or another planning tool may all produce packet-shaped input.

Proofline's role is not to become the planning tool. Proofline uses the packet to preserve traceability from intended work to evidence-backed completion.

## Boundary

An Execution Packet is an upstream work bundle and audit aid. It is not:

- a replacement for `TaskEnvelope`
- a new lifecycle authority
- a planner runtime
- an executor-native prompt format
- completion evidence by itself
- a requirement for every small task

`TaskEnvelope` remains the canonical task contract once work enters Proofline.

## Design Goals

- preserve traceability from intent to acceptance criteria to evidence
- support both small tasks and larger spec-driven efforts
- keep Spec Kit and similar tools as optional producers
- avoid turning Proofline into a generic project-management or planning surface
- allow later import/linking without changing TaskEnvelope core prematurely

## Conceptual Flow

```text
idea / request / issue
        |
        v
specification
        |
        v
technical plan
        |
        v
task breakdown
        |
        v
Execution Packet
        |
        v
TaskEnvelope(s)
        |
        v
execution artifacts + validation evidence
        |
        v
Proofline verification and reconciliation
```

## Minimal Packet Schema

The first packet shape should be intentionally small:

```json
{
  "packet_id": "exec-packet-123",
  "schema_version": "0.1",
  "source": {
    "system": "spec-kit",
    "type": "spec_driven_bundle",
    "id": "feature-photos-albums",
    "url": "https://example.invalid/specs/feature-photos-albums"
  },
  "intent": {
    "summary": "Build date-grouped photo albums with drag-and-drop organization.",
    "requester": "user-or-system-id"
  },
  "work_items": [
    {
      "work_item_id": "task-1",
      "title": "Create album data model",
      "description": "Define persistent album and photo metadata records.",
      "acceptance_criteria": [
        {
          "id": "ac-1",
          "description": "Albums can be grouped by date and never nest inside other albums."
        }
      ],
      "required_evidence": [
        {
          "type": "pull_request",
          "description": "PR containing model changes and tests."
        }
      ],
      "validation_commands": [
        {
          "command": "pnpm test",
          "required": true
        }
      ]
    }
  ]
}
```

This is an architecture example, not a committed JSON Schema.

## Required Fields

The minimal required packet fields should be:

| Field | Required | Purpose |
| --- | --- | --- |
| `packet_id` | yes | stable packet identity |
| `schema_version` | yes | packet schema compatibility |
| `source.system` | yes | upstream producer or authoring system |
| `source.type` | yes | producer shape, such as `spec_driven_bundle`, `linear_issue`, or `manual_packet` |
| `source.id` | yes | upstream identifier |
| `intent.summary` | yes | concise statement of the user intent |
| `work_items` | yes | one or more task-shaped items |
| `work_items[].work_item_id` | yes | stable item identity inside the packet |
| `work_items[].title` | yes | short work label |
| `work_items[].description` | yes | task description |
| `work_items[].acceptance_criteria` | yes | one or more completion conditions |

## Optional Fields

Optional fields should stay outside TaskEnvelope core until proven universal:

- `source.url`
- `source.repository`
- `source.branch`
- `intent.requester`
- `intent.problem_statement`
- `intent.non_goals`
- `principles`
- `spec_artifacts`
- `technical_plan`
- `dependencies`
- `risks`
- `assumptions`
- `required_evidence`
- `validation_commands`
- `linked_artifacts`
- `linear_refs`
- `github_refs`
- `metadata`

## Work Item Shape

Each `work_items[]` entry represents a candidate TaskEnvelope or child task.

Expected fields:

- `work_item_id`
- `title`
- `description`
- `objective`
- `constraints`
- `acceptance_criteria`
- `dependencies`
- `required_capabilities`
- `required_evidence`
- `validation_commands`
- `linked_artifacts`
- `metadata`

Small tasks may include one work item. Larger spec-driven features may include many work items with dependency edges.

## Mapping To Proofline Concepts

| Execution Packet concept | Proofline concept |
| --- | --- |
| `packet_id` | packet provenance in `origin` or `extensions` |
| `source` | `TaskEnvelope.origin` |
| `intent.summary` | `TaskEnvelope.objective.summary` |
| `work_items[]` | one or more `TaskEnvelope` records |
| `work_items[].acceptance_criteria` | `TaskEnvelope.acceptance_criteria` |
| `work_items[].dependencies` | `TaskEnvelope.dependencies` |
| `work_items[].required_evidence` | `artifacts.completion_evidence.required_artifact_types` plus policy notes |
| `work_items[].validation_commands` | validation expectations in artifacts/evidence policy or a future validation-plan surface |
| `linked_artifacts.github_refs` | artifact records or reconciliation inputs |
| `linked_artifacts.linear_refs` | coordination/reconciliation inputs |
| `technical_plan` | `plan_artifact` or planner output context |
| `assumptions` / `risks` | constraints, clarification inputs, or review notes |

The mapping should be one-way at first: packet into TaskEnvelope and artifacts. Proofline should not require every TaskEnvelope to retain a full packet copy.

## Evidence Traceability

The packet should make evidence requirements explicit before execution starts.

Each required evidence item should describe:

- expected artifact type
- why the artifact matters
- whether it is required for completion
- expected source system when known
- how it should be validated

Example:

```json
{
  "type": "pull_request",
  "required_for_completion": true,
  "source_system": "github",
  "description": "A PR links implementation work to the task and exposes reviewable code changes.",
  "validation": {
    "method": "github_readback",
    "must_match_branch": true,
    "must_reference_work_item": true
  }
}
```

This maps naturally to Proofline's artifact and completion evidence model. It should not bypass later GitHub/Linear reconciliation.

## Validation Command Semantics

Validation commands are expectations, not trusted proof by themselves.

Each command should record:

- command text
- working directory or target when known
- required/optional status
- expected artifact or output
- whether failure blocks completion

An executor may report that a command passed, but Proofline should treat that as advisory unless the command output is captured as an artifact or independently verified.

## Spec Kit Import Strategy

Spec Kit-style output can be imported or linked later without becoming a dependency.

Initial importer behavior should be conservative:

1. Read a local or repository-hosted spec bundle.
2. Extract intent/spec summary.
3. Extract technical plan summary if present.
4. Extract task list and dependencies if present.
5. Convert each task into a packet `work_item`.
6. Preserve source file paths, commit SHAs, or URLs as packet provenance.
7. Attach the original spec/plan/tasks as `plan_artifact` or linked references.
8. Submit candidate TaskEnvelope records through canonical intake/planning paths.

The importer should not:

- execute implementation commands
- trust generated tasks as complete
- mark evidence satisfied
- mutate Linear or GitHub state by default
- require Spec Kit files for normal Proofline usage

## Lightweight Packet For Small Tasks

Proofline should support a minimal packet for simple work:

```json
{
  "packet_id": "exec-packet-small-1",
  "schema_version": "0.1",
  "source": {
    "system": "manual",
    "type": "manual_packet",
    "id": "small-1"
  },
  "intent": {
    "summary": "Fix a broken README link."
  },
  "work_items": [
    {
      "work_item_id": "readme-link",
      "title": "Fix README link",
      "description": "Correct the stale architecture-doc link.",
      "acceptance_criteria": [
        {
          "id": "ac-link-valid",
          "description": "README link resolves to an existing file."
        }
      ]
    }
  ]
}
```

No extra process ceremony should be required for small tasks.

## Future Implementation Touchpoints

Recommended follow-up issues:

1. JSON Schema draft
   - add `schemas/execution_packet.schema.json`
   - validate examples in tests

2. Packet-to-intake mapper
   - convert minimal packet work items into canonical intake payloads
   - keep original packet provenance in `origin` or `extensions`

3. Spec Kit link/import spike
   - read local spec/plan/tasks files
   - create packet examples without executing implementation steps

4. Evidence policy mapping
   - translate `required_evidence` into completion evidence policy defaults
   - preserve artifact/reconciliation boundaries

5. Dashboard/read-model projection
   - show packet provenance and evidence traceability read-only
   - do not create a packet editing surface

## Out Of Scope

- making Spec Kit mandatory
- adding a broad planner UI
- storing every planning document in TaskEnvelope core
- accepting generated tasks without Proofline validation
- executing implementation commands from packet import
- treating validation command self-reports as verified evidence

## Related Documents

- [TaskEnvelope Contract](task-envelope.md)
- [Intake To TaskEnvelope Mapping](intake-to-task-envelope.md)
- [Planner Contract](planner-contract.md)
- [Artifact And Completion Evidence](artifact-and-completion-evidence.md)
- [Verification And Completion Enforcement](verification-and-completion-enforcement.md)
