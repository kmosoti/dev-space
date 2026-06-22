# Bootstrap the GitHub control plane v1

## Problem

The repository has no executable GitHub control plane, isolated worker workflow, or authoritative Project v2 work model.

## Current Behavior

Planning, identity boundaries, lifecycle transitions, Project configuration, and pull-request handoff are informal or absent.

## Required Behavior

The versioned repository contract, live Project v2, native issue tree, worker fork boundary, verification, and read-only enforcement check operate as one recoverable workflow.

## Scope

- Add the workflow and state-machine contract before mutation tooling
- Add Project v2 snapshot, plan, apply, and drift detection
- Add bounded issue specifications, native hierarchy, dependencies, and readiness attestation
- Add isolated worker sessions and gated draft-to-review handoff
- Add repository templates, checks, ownership, and governance reconciliation

## Non-goals

- Merge the bootstrap pull request automatically
- Grant the worker write access to the target repository
- Mutate learning-os or any unrelated repository
- Treat Epics as implementation branches

## Design

Use typed domain contracts around structured GitHub adapters, persist resumable operation journals outside the repository, and structurally separate planner and worker credentials. Repository policy declares desired governance; Project v2 owns live workflow state; issue bodies and native relations own scope.

## Affected Components

- Dev-space CLI and Python control-plane modules
- GitHub Project v2 number 6
- GitHub issue and pull-request templates
- GitHub Actions and repository governance
- Worker fork kz-harbringer/dev-space

## Security

The planner alone authorizes readiness and merge. The worker pushes only to its fork through a dedicated SSH host and isolated gh configuration. CI receives read-only repository permissions and no Project token.

## Compatibility

Policy schema v1 rejects unsupported future versions. Existing unowned Project resources and unrelated repository settings are preserved.

## Tests

- Run the complete Python suite with coverage and snapshot validation
- Run Ruff format and lint checks
- Run Vulture and pip-audit
- Run Rust tests and strict Clippy
- Verify live Project and issue relationship reconciliation idempotently

## Rollout

Open a draft bootstrap pull request from the worker fork. After policy-pinned verification passes, mark it ready and request human review. After human review and merge, activate the main ruleset only when both required checks exist on the default branch.

## Rollback

Close the bootstrap pull request, delete its worker branch, and revert the control-plane commit. Live Project items remain auditable and repository ruleset activation remains gated.

## Dependencies

None

## Acceptance Criteria

- [ ] Repository policy and executable lifecycle contracts agree
- [ ] Project v2 metadata, fields, options, labels, and item state reconcile idempotently
- [ ] The complete Epic and blocked-by issue tree exists with native relationships
- [ ] Worker identity is isolated to a fork and cannot merge the target repository
- [ ] All local quality gates pass
- [ ] A single verified bootstrap pull request is ready for human review

## Unresolved Decisions

None

## Execution

Agent-ready

## Risk

Medium
