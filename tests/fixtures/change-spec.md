# Add control-plane contracts

## Problem

The workflow is not executable.

## Current Behavior

Rules exist only in prose.

## Required Behavior

Rules are validated before mutation.

## Scope

- Add typed models
- Add lifecycle validation

## Non-goals

- Launch Codex

## Design

Use pure domain functions and typed adapters.

## Affected Components

- CLI
- Project adapter

## Security

Keep planner and worker identities separate.

## Compatibility

Schema version one rejects future versions.

## Tests

- Validate every transition
- Validate actor boundaries

## Rollout

Land the contract before mutating GitHub.

## Rollback

Revert the contract commit before Project apply.

## Dependencies

- #10

## Acceptance Criteria

- [ ] Invalid transitions fail
- [ ] Worker cannot mark Ready

## Unresolved Decisions

None

## Execution

Agent-ready

## Risk

Medium
