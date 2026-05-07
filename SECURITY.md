# Security Policy

Proofline is an early-stage acceptance layer for AI-assisted software work. Treat it as security-sensitive because it evaluates completion claims, external evidence, repository artifacts, and project-tracker facts.

## Supported Versions

Security fixes target the default branch, `main`, until formal releases exist.

## Reporting A Vulnerability

Please report suspected vulnerabilities privately through GitHub private vulnerability reporting when available, or by contacting the maintainer directly.

Do not open a public issue for:

- credential exposure
- authentication or authorization bypass
- unsafe acceptance of executor completion claims
- evidence spoofing or artifact-provenance bypass
- live Linear/GitHub mutation safety issues
- denial-of-service paths in verification, retry, or reconciliation loops

## Security Expectations

Contributors should preserve these boundaries:

- executor and agent summaries are advisory only
- completion acceptance must flow through Proofline verification
- Linear/GitHub facts must be reconciled before trusted completion
- secrets must not be committed, logged, or copied into examples
- live integrations must stay gated behind explicit preflight checks

When in doubt, fail closed and require manual review.
