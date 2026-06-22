# ADR 002: Mutation measurement, criticality tiers, and ratchet policy

## Status

Proposed for planner approval under issue #64.

## Context

The bootstrap pipeline enforced one 80% Mutmut threshold. That value was a
useful initial guardrail, but it was not derived from a universal engineering
standard and it incorrectly implied that all code, tools, and mutation outcomes
carry equal risk. A universal 100% requirement is also unsound: equivalent,
unviable, and tool-skipped mutants are not killed tests, while forcing them into
the denominator rewards exclusions and implementation-coupled tests.

Coverage remains a separate signal. The repository keeps a 90% branch-coverage
floor, but line or branch execution cannot prove semantic assertions. Mutation
results therefore retain their own denominator, evidence, and non-regression
ratchet.

## Decision

Mutation quality is evaluated per named target under versioned
`.dev-space/quality.toml` policy.

| Tier | Minimum | Target | Intended use |
| --- | ---: | ---: | --- |
| Critical | 90% | 100% | authorization, lifecycle, parsing, recovery, tool boundaries |
| Standard | 80% | 95% | ordinary repository behavior and orchestration |
| Supporting | 70% | 90% | adapters or compatibility code with lower semantic risk |

The existing repository-wide Mutmut target starts at the standard 80% baseline.
This preserves the measured bootstrap ratchet without claiming 80% is the goal.
Contract-critical modules are split into critical targets and raised toward
100% as the scoped adapters land.

The assessed denominator is:

`killed + survived + timeout + suspicious + no_test + runtime_error`

Killed is the numerator. Timeout, suspicious, missing-test, and runtime-error
outcomes remain failures because none demonstrates a detecting assertion.
Unviable and tool-skipped mutants are reported but excluded from the score.
Equivalent mutants are excluded only when a policy entry names the mutant,
owner, rationale, evidence, and expiry. They never count as killed.

A result fails when it has no assessed mutants, contains unknown outcomes,
uses uncovered or expired equivalent exclusions, falls below its tier minimum,
or decreases below the target's recorded baseline. Raising a baseline requires
an intentional policy change; lowering one is prohibited by the comparison
gate added in the QA rollout.

Mutmut and cargo-mutants retain separate raw outcome aliases. Both normalize to
the same canonical result vocabulary without pretending their mutation engines
or unviable behavior are identical.

## Consequences

- One aggregate score can no longer hide critical-path weakness.
- A green pipeline cannot be obtained by silently skipping, reclassifying, or
  expiring difficult mutants.
- Teams can collaborate against explicit targets without turning 100% into a
  vanity metric or accepting score regression.
- QA1-03 and QA1-04 must produce target-specific Mutmut and cargo-mutants
  evidence; QA1-08 will enforce baseline comparison in CI.

## Rejected alternatives

- **Universal 80%:** simple, but risk-blind and not evidence-based.
- **Universal 90%:** better pressure, but still conflates critical and support
  code and can reward shallow exclusion.
- **Universal 100%:** treats equivalent/unviable mutants as test failures and
  incentivizes implementation-coupled tests or hidden exclusions.
- **Coverage alone:** measures execution, not whether assertions detect a
  semantic defect.

## Rollback

Revert the policy evaluator and restore the prior gate only through a reviewed
policy decision. Preserve all result fixtures and survivor/exclusion evidence;
do not lower an accepted baseline to make an existing run pass.
