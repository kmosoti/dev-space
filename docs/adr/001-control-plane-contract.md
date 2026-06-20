# ADR-001: GitHub control-plane contract

## Status

Accepted for the v1 rollout.

## Decision

The default-branch `.dev-space/project.toml` is authoritative for desired
governance and Project v2 schema. The dedicated `dev-space` Project v2 is
authoritative for live item membership and workflow values. GitHub issues are
authoritative for specifications and native hierarchy. Pull requests and check
runs are authoritative for implementation and verification evidence.

`kmosoti` is the planner, reviewer, and merge authority. `kz-harbringer` is the
worker. The worker cannot authorize readiness, apply repository governance,
approve, enable auto-merge, or merge.

The lifecycle and command-capability matrices are executable domain contracts.
All mutation services must call them rather than reimplementing state rules.
Mutating multi-system commands must journal intent before their first side
effect and make retries resume the journal.

Epics describe outcomes and contain dependency-ordered child issues. Epics do
not receive implementation branches, worktrees, or pull requests. Every
implementation issue receives exactly one of each.

## Consequences

- Labels are projections and cannot overwrite Project v2 state.
- A worker branch cannot change the policy used to validate its own session.
- Project API gaps are explicit human-action results, never silent omissions.
- GitHub and Git partial failures are recoverable without duplicate resources.
- The initial bootstrap is implemented locally before live Project mutation.
