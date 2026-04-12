"""Connector scaffolding for external-system translation."""

from .github_facts import (
    GitHubConnectorInputError,
    translate_github_artifact_facts,
    translate_github_artifact_references,
    translate_github_branch,
    translate_github_changed_files,
    translate_github_commit,
    translate_github_pull_request,
    translate_github_repository,
)
from .github_artifact_validation import (
    GitHubArtifactLookup,
    GitHubArtifactValidationError,
    GitHubArtifactValidationIssue,
    GitHubArtifactValidationItemResult,
    GitHubArtifactValidationResult,
    GitHubRestArtifactLookup,
    validate_github_artifact_references,
)
from .linear_facts import (
    LinearConnectorInputError,
    translate_linear_facts,
    translate_linear_project,
    translate_linear_task_reference,
    translate_linear_workflow,
)
from .linear_ingress import (
    LinearIngressInputError,
    translate_linear_submission_payload,
)
from .manual_ingress import (
    ManualIngressInputError,
    translate_manual_submission_payload,
)
from .openclaw_ingress import (
    OpenClawIngressInputError,
    translate_openclaw_submission_payload,
)
from .ingress_request_builder import (
    IngressRequestBuilderError,
    IngressSourceContext,
    IngressTaskIntent,
    build_task_reevaluation_payload,
    build_task_submission_payload,
)
from .openclaw_harness_spike import (
    OpenClawHarnessSpikeClient,
    OpenClawHarnessSpikeError,
    OpenClawHarnessSpikeResult,
    OpenClawSourceContext,
    OpenClawTaskIntent,
    run_openclaw_review_gate_spike_flow,
    run_openclaw_spike_flow,
)
from .openclaw_supervisor import (
    OpenClawHarnessSupervisor,
    OpenClawSupervisionActionResult,
    OpenClawSupervisionCycleResult,
    OpenClawSupervisionDecision,
)

__all__ = [
    "GitHubConnectorInputError",
    "GitHubArtifactLookup",
    "GitHubArtifactValidationError",
    "GitHubArtifactValidationIssue",
    "GitHubArtifactValidationItemResult",
    "GitHubArtifactValidationResult",
    "GitHubRestArtifactLookup",
    "IngressRequestBuilderError",
    "IngressSourceContext",
    "IngressTaskIntent",
    "LinearConnectorInputError",
    "LinearIngressInputError",
    "ManualIngressInputError",
    "OpenClawHarnessSpikeClient",
    "OpenClawHarnessSpikeError",
    "OpenClawHarnessSpikeResult",
    "OpenClawHarnessSupervisor",
    "OpenClawIngressInputError",
    "OpenClawSourceContext",
    "OpenClawSupervisionActionResult",
    "OpenClawSupervisionCycleResult",
    "OpenClawSupervisionDecision",
    "OpenClawTaskIntent",
    "build_task_reevaluation_payload",
    "build_task_submission_payload",
    "run_openclaw_review_gate_spike_flow",
    "run_openclaw_spike_flow",
    "translate_github_artifact_facts",
    "validate_github_artifact_references",
    "translate_github_artifact_references",
    "translate_github_branch",
    "translate_github_changed_files",
    "translate_github_commit",
    "translate_github_pull_request",
    "translate_github_repository",
    "translate_linear_facts",
    "translate_manual_submission_payload",
    "translate_openclaw_submission_payload",
    "translate_linear_submission_payload",
    "translate_linear_project",
    "translate_linear_task_reference",
    "translate_linear_workflow",
]
