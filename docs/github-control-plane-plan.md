# Dev-Space GitHub Control Plane

## Epic

Build a reusable, repository-owned GitHub control plane in `dev-space`, then
dogfood it on `kmosoti/dev-space` without changing the `learning-os` Project.

This document defines the rollout epic. It is not an implementation issue and
must not own a branch, worktree, or pull request. Every code change is delivered
through a bounded child issue with one branch, one worktree, and one pull
request.

The canonical dogfood checkout is:

```text
/home/kmosoti/src/dev-space
```

Generic tooling must discover a repository from `--repo`, the current working
directory, or Git metadata. The canonical checkout path is an operational
default, not a value stored in `.dev-space/project.toml`.

`learning-os` is excluded from this rollout.

## Delivery rules

- An Epic describes an outcome and groups dependent work. It has no
  implementation branch or pull request.
- A Change, Bug, or Maintenance issue is the smallest independently testable
  implementation slice.
- Every implementation issue identifies its parent Epic, prerequisites,
  acceptance criteria, verification, exclusions, rollout, and rollback.
- Dependencies form a directed acyclic graph. An issue cannot become `Ready`
  while a prerequisite is incomplete.
- One implementation issue maps to exactly one branch, worktree, and pull
  request.
- Decisions that change the contract are resolved in Decision issues before
  dependent implementation begins.
- Epics close only when every child is Done or explicitly Canceled with a
  recorded reason.

## Sources of truth

The control plane has one authority for each kind of data. “Source of truth”
does not mean that the same value is independently editable in several places.

| Concern | Source of truth | Derived projections |
| --- | --- | --- |
| Desired governance, Project schema, actors, lifecycle rules, checks, and reconciliation policy | Versioned `.dev-space/project.toml` on the default branch | Project configuration, repository settings, rulesets, labels, and generated check configuration |
| Live portfolio and workflow state | The dedicated GitHub Project v2 | Current-state labels and CLI reports |
| Scope, acceptance criteria, decisions, dependencies, and hierarchy | GitHub issue bodies plus native issue relationships | Generated session instructions and PR checklists |
| Implementation and review evidence | Git branch, pull request, reviews, and check runs | Project status summaries and completion comments |
| In-flight local operation state | Durable XDG session journal | Human-readable `session status` output |

GitHub Project v2 is therefore the operational source of truth for item
membership and live values of `Status`, `Work Type`, `Execution`, `Risk`, and
`Development Branch`. Labels never drive Project state. A planner-authorized
transition updates Project v2 first and then reconciles labels as projections.
If projection repair fails, the journal records the partial failure and Project
v2 remains authoritative.

The policy file is the desired-state source of truth for how that Project must
be constructed. `project plan` compares the desired schema with a full-fidelity
Project snapshot; `project apply` reconciles only planner-owned configuration
and never treats a label or local cache as a competing authority.

## Contract first

Implementation begins with the project workflow and state-machine contract.
No GitHub mutation, worktree orchestration, or enforcement work starts until
the contract fixtures pass.

### Roles

| Role | Actor | Allowed operations |
| --- | --- | --- |
| Planner/reviewer | `kmosoti` | Create Epics and Decisions, approve specifications, mark work Ready, apply control-plane configuration, resolve or cancel work, approve and merge pull requests |
| Worker | `kz-harbringer` | Start Ready agent work, create a branch/worktree, push implementation commits, maintain a draft pull request, and submit verified work for review |
| Read-only operator | Either configured actor | Run `doctor`, `plan`, and status commands |

The worker cannot mark its own issue Ready, alter planner-owned state, apply
repository rules, enable auto-merge, approve, or merge. It may mark its own
pull request ready for review only through the verified handoff workflow.

### Work types

- `Epic`: an overall plan or outcome; contains child issues and never owns code.
- `Change`: a bounded behavior or capability increment.
- `Bug`: correction of an observed defect with a regression test.
- `Maintenance`: bounded operational or dependency work.
- `Decision`: an unresolved product, architecture, security, or policy choice.

### States and transition ownership

| From | To | Authorized role | Gate |
| --- | --- | --- | --- |
| — | Inbox | Planner | Issue created and classified |
| Inbox | Needs Definition | Planner | Parent Epic and work type assigned |
| Needs Definition | Ready | Planner | Specification complete, decisions resolved, dependencies Done, supported risk |
| Ready | In Progress | Worker via `session start` | Correct worker identity; no active branch, worktree, session, or pull request |
| In Progress | In Review | Worker via `session handoff` | Checks pass; final branch head is pushed; exactly one pull request is marked ready for review |
| In Review | Done | Planner | Pull request merged by the human actor and completion evidence recorded |
| Any nonterminal state | Blocked | Planner or Worker | Blocker and unblock condition recorded |
| Blocked | Previous active state | Planner | Blocker resolved and all gates still pass |
| Needs Definition or Ready | Canceled | Planner | Reason recorded; no active implementation resources |
| In Progress or In Review | Canceled | Planner | Pull request disposition and cleanup plan recorded |
| In Progress | Needs Definition | Planner | Scope or architecture decision returned to planning |

The Project v2 `Status` value is authoritative. Labels mirror the current
repository-visible state; they are not historical event labels. Readiness
history is recorded as a machine-readable attestation made by the planner actor
so read-only CI can validate it without accessing the user-owned Project.

### Command authorization

| Command | Mutation | Required actor |
| --- | --- | --- |
| `project doctor` | None | Either |
| `project snapshot` | None | Either |
| `project plan` | None | Either |
| `project apply` | Project/repository configuration | Planner |
| `issue create-change` | Issue, hierarchy, Project item | Planner |
| `issue mark-ready` | Status, labels, readiness attestation | Planner |
| `issue transition` | Lifecycle state | Actor allowed by transition table |
| `session status` | None | Either |
| `session start` | Local session plus In Progress state | Worker |
| `session handoff` | Branch, PR ready-for-review state, review request, In Review state | Worker |
| `session recover` | Resume an incomplete operation | Same actor that began it |
| `session cleanup` | Local branch/worktree/session cleanup | Planner unless no remote state exists |

### Transaction and recovery contract

GitHub and Git operations are not transactional. Each mutating command writes
a durable operation journal before its first side effect. Every step records
its idempotency key, observed remote version, result, and next recovery action.

- `session start` reserves and locks session state, validates remote state,
  creates the branch and worktree, configures worktree-local identity, writes
  generated instructions, and moves the issue to In Progress last.
- A pull request may remain draft while implementation commits are collected.
- `session handoff` validates correspondence, runs configured checks, pushes
  the final branch head, creates or updates one draft pull request, marks it
  ready for review, requests review, and moves the issue to In Review last.
- A failed handoff leaves the pull request draft and the issue In Progress; a
  retry resumes from the journal rather than bypassing verification.
- A retry resumes from the journal rather than recreating resources.
- Stale state is inspectable with `session status` and recoverable through
  `session recover`; the CLI never asks users to delete unexplained state.

### Trust boundaries

- Enforcement policy is loaded from the default branch or the base commit
  pinned when the session starts, never from a worker-modifiable checkout.
- Issue content embedded in generated instructions is treated as data; it
  cannot override root policy, actor rules, scope, or verification commands.
- GitHub credentials and SSH key paths never enter tracked configuration.
- Human and worker GitHub actors, SSH routing, commit identity, and repository
  permission are verified independently.
- Git configuration is shared between worktrees unless
  `extensions.worktreeConfig` is enabled. Worker identity and push routing are
  therefore set with worktree-local configuration or explicit SSH push URLs;
  the human `origin` is not rewritten.

## Epic and issue dependency tree

The identifiers below are planning identifiers. Replace them with GitHub issue
numbers when the Epic and children are created, while preserving the dependency
edges.

```text
EPIC-CP0  GitHub Control Plane v1
|
+-- EPIC-CP1  Workflow and state-machine contract
|   +-- CP1-01  Decision: workflow vocabulary, roles, and invariants
|   +-- CP1-02  Policy schema v1 and typed domain models          <- CP1-01
|   +-- CP1-03  Pure lifecycle transition engine                 <- CP1-02
|   +-- CP1-04  Actor capability and command authorization       <- CP1-01, CP1-02
|   +-- CP1-05  Operation journal and recovery contract          <- CP1-02, CP1-03
|   `-- CP1-06  Contract fixtures and golden tests               <- CP1-02, CP1-03, CP1-04, CP1-05
|
+-- EPIC-CP2  GitHub read model and reconciliation foundation    <- EPIC-CP1
|   +-- CP2-01  Typed `gh api` adapter and error taxonomy         <- CP1-02, CP1-06
|   +-- CP2-02  Authentication and permission preflight          <- CP1-04, CP2-01
|   +-- CP2-03  Stable Project/repository snapshot model         <- CP2-01
|   +-- CP2-04  Deterministic reconciliation diff engine         <- CP2-03
|   `-- CP2-05  Fake adapter, fixtures, and partial-failure tests <- CP2-01, CP2-04
|
+-- EPIC-CP3  Project bootstrap and drift management             <- EPIC-CP2
|   +-- CP3-01  Project v2 authority and API capability contract <- CP1-06, CP2-01
|   +-- CP3-02  Full-fidelity snapshot/export model              <- CP2-03, CP3-01
|   +-- CP3-03  `project doctor`                                 <- CP2-02, CP3-02
|   +-- CP3-04  `project plan`                                   <- CP2-04, CP2-05, CP3-02
|   +-- CP3-05  Project creation, metadata, identity, and linkage <- CP3-04
|   +-- CP3-06  Fields, options, ordering, and native-field map  <- CP3-04, CP3-05
|   +-- CP3-07  Item membership and field-value round trip       <- CP3-02, CP3-06
|   +-- CP3-08  Views and built-in workflow fidelity/checklist   <- CP3-02, CP3-05, CP3-06
|   +-- CP3-09  Labels as Project-state projections              <- CP3-06
|   `-- CP3-10  Idempotent full-fidelity `project apply`          <- CP3-05, CP3-06, CP3-07, CP3-08, CP3-09
|
+-- EPIC-CP4  Planning issues and readiness                      <- EPIC-CP1, EPIC-CP3
|   +-- CP4-01  Epic, Change, Bug, Maintenance, Decision forms   <- CP1-01
|   +-- CP4-02  Change-spec parser and readiness evaluator       <- CP1-02, CP1-03
|   +-- CP4-03  Native hierarchy/dependency adapter              <- CP2-01
|   +-- CP4-04  `issue create-change`                             <- CP4-01, CP4-02, CP4-03, CP3-10
|   +-- CP4-05  Planner-only `issue mark-ready` and attestation  <- CP1-04, CP4-02, CP4-04
|   `-- CP4-06  General lifecycle transition command             <- CP1-03, CP1-04, CP4-05
|
+-- EPIC-CP5  Worker identity and session start                  <- EPIC-CP1, CP2-02, CP4-05
|   +-- CP5-01  Human/worker identity-lane preflight             <- CP1-04, CP2-02
|   +-- CP5-02  XDG session store, lock, and operation journal   <- CP1-05
|   +-- CP5-03  Worktree-local Git identity and SSH routing      <- CP5-01, CP5-02
|   +-- CP5-04  Branch naming and collision rules                <- CP1-02
|   +-- CP5-05  Issue-scoped instruction generation              <- CP1-02, CP1-06
|   `-- CP5-06  Retry-safe `session start`                        <- CP5-02, CP5-03, CP5-04, CP5-05
|
+-- EPIC-CP6  Verification and ready-for-review handoff          <- EPIC-CP5
|   +-- CP6-01  Focused/full verification runner                 <- CP1-02, CP1-06
|   +-- CP6-02  PR-body model and template validation            <- CP4-02
|   +-- CP6-03  Push and draft-to-ready PR reconciliation        <- CP2-01, CP5-03
|   +-- CP6-04  Retry-safe `session handoff`                      <- CP6-01, CP6-02, CP6-03
|   `-- CP6-05  `session status`, `recover`, and `cleanup`        <- CP5-02, CP6-04
|
+-- EPIC-CP7  Repository enforcement                            <- EPIC-CP3, EPIC-CP4, EPIC-CP6
|   +-- CP7-01  Read-only Control Plane Contract check           <- CP4-05, CP6-02
|   +-- CP7-02  Root AGENTS, CODEOWNERS, and PR template         <- CP1-01, CP6-02
|   +-- CP7-03  Main ruleset reconciliation                      <- CP3-10, CP7-01, CP7-02
|   +-- CP7-04  Disable repository auto-merge                    <- CP3-10
|   +-- CP7-05  Least-privilege release workflow                 <- CP7-02
|   `-- CP7-06  Human-only merge model decision and enforcement  <- CP1-01
|
`-- EPIC-CP8  Dev-space dogfood rollout                         <- EPIC-CP7
    +-- CP8-01  Apply and verify full-fidelity Project v2        <- CP3-07, CP3-08, CP3-10
    +-- CP8-02  Create pilot Epic and bounded Agent-ready Change <- CP4-05, CP8-01
    +-- CP8-03  Run start/handoff pilot through ready PR         <- CP5-06, CP6-05, CP7-03
    +-- CP8-04  Human review, merge, and Done transition          <- CP8-03
    `-- CP8-05  Friction report and follow-up issue tree          <- CP8-04
```

Work may proceed in parallel only where the tree permits it. Completion of an
Epic means all of its child issues have reached a terminal state; it does not
replace their acceptance evidence.

## Bounded issue specifications

### EPIC-CP1: Workflow and state-machine contract

Outcome: a versioned, executable contract shared by the CLI, reconciler,
templates, and CI.

- `CP1-01` records the vocabulary and invariants in an ADR. No runtime code.
- `CP1-02` adds `.dev-space/project.toml` schema v1 and Pydantic models for
  policy, actor identity, issue specification, lifecycle state, operation
  result, and reconciliation result.
- `CP1-03` implements a pure transition function with no filesystem, GitHub, or
  subprocess dependencies.
- `CP1-04` maps commands and transitions to roles and returns typed denials.
- `CP1-05` defines durable journal records and recovery outcomes without yet
  creating Git worktrees.
- `CP1-06` supplies valid/invalid policy fixtures, every legal and illegal
  transition, actor-separation cases, and schema compatibility tests.

Exit gate: all contract tests pass and every later Epic consumes these types
rather than redefining lifecycle rules.

### EPIC-CP2: GitHub read model and reconciliation foundation

Outcome: side-effect-free discovery plus a typed mutation boundary.

The adapter uses structured `gh api` JSON only. Read and mutation interfaces
are separate so tests can prove `plan` has no mutation path. Errors distinguish
authentication, authorization, unsupported API behavior, conflict, validation,
rate limiting, and partial failure.

Exit gate: a fixture-backed snapshot produces byte-stable JSON/JSONL and
Markdown reconciliation reports without network mutation.

### EPIC-CP3: Project bootstrap and drift management

Outcome: deterministic, full-fidelity creation and maintenance of the dedicated
user-owned GitHub Project v2 named `dev-space`, with no silent loss between the
declared design, live Project, and exported snapshot.

`CP3-01` records a capability matrix for every Project v2 concern. Each concern
is classified as API read/write, API read-only, UI-only, unsupported, or human
action required. Unsupported capabilities do not disappear from the plan: they
produce an exact manual procedure and subsequent verification result.

`project snapshot` emits a versioned JSON document and readable Markdown report
covering all discoverable Project v2 state:

- owner, number, node ID, title, short description, README, visibility, URL,
  lifecycle/closed state, and repository linkage;
- every custom field, data type, stable node ID, ordering, and configuration;
- every single-select option including name, description, color, ordering, and
  stable option ID;
- native fields and their mapping to repository, assignees, milestones, parent
  issues, and sub-issue progress;
- Project items, content identity, archive state, and all field values;
- configured views, filters, grouping, sorting, slicing, visible fields, and
  layout when exposed by the API;
- built-in Project workflows and automation when exposed by the API; and
- an explicit capability/omission record for every value the API cannot read.

Secrets, tokens, and user-local credential paths are excluded from snapshots.
Snapshot serialization is deterministic so two equivalent Projects produce the
same normalized document after volatile timestamps and node IDs are separated
into the identity registry.

The desired Project model contains:

- `Status`: Inbox, Needs Definition, Ready, In Progress, In Review, Blocked,
  Done, Canceled
- `Work Type`: Epic, Change, Bug, Maintenance, Decision
- `Execution`: Agent-ready, Agent-assisted, Human-only
- `Risk`: Low, Medium, High
- `Development Branch`: text
- native repository, assignee, milestone, parent issue, and sub-issue progress

The policy also declares Project title, short description, README, visibility,
repository linkage, field and option order, option colors/descriptions, desired
views, and desired built-in workflows. This is sufficient to create a new
Project v2 from an empty account state rather than merely attach to one that a
human has preconfigured.

The Project number/node ID and managed field/option IDs are persisted in local
operator state after bootstrap and checked against the owner/title marker.
Labels and rulesets use description or name markers where supported. Fields
inherit ownership from the uniquely identified managed Project; they are not
assumed to support descriptions. Unknown resources are reported and preserved
in v1.

`project plan` reports create, update, unchanged, conflict, unsupported, and
human action required for every full-fidelity concern. `project apply` creates
the Project when absent, reconciles every API-writable concern, emits a
deterministic checklist for UI-only views/workflows, and then snapshots the live
Project again. Apply succeeds only when the post-apply snapshot matches policy
or every remaining difference is explicitly classified as verified human
action required.

Item membership and live field values are round-tripped to prove the snapshot
is complete, but bulk `project apply` does not overwrite operational work state.
Those values change only through authorized lifecycle and issue commands. This
preserves Project v2 as the operational source of truth while still detecting
drift and orphaned items.

Exit gate: starting with no `dev-space` Project, the tooling creates the full
declared Project v2; a post-apply snapshot accounts for every declared setting;
repeated `project apply` is unchanged; duplicate Projects become a conflict;
item/value round-trip tests lose no information; and API-inaccessible view or
workflow settings produce an exact, verifiable UI checklist.

### EPIC-CP4: Planning issues and readiness

Outcome: planners can create a complete issue hierarchy and workers cannot
self-authorize.

Issue Forms cover Epics, Changes, Bugs, Maintenance, and Decisions. The Change
specification includes problem, current/required behavior, scope, non-goals,
design, affected components, security, compatibility, tests, rollout,
rollback, dependencies, acceptance criteria, and unresolved decisions.

`issue mark-ready` requires the planner identity and writes both the Project
status and repository-visible readiness label/attestation. The attestation
contains the issue, actor, accepted specification hash, dependency snapshot,
and timestamp. This is the evidence consumed by read-only CI.

Exit gate: an incomplete or dependency-blocked issue cannot become Ready under
either identity, and a worker cannot issue a valid readiness attestation.

### EPIC-CP5: Worker identity and session start

Outcome: one Ready issue becomes one isolated, recoverable worker session.

Worktrees live at:

```text
${XDG_DATA_HOME:-~/.local/share}/dev-space/worktrees/<owner>/<repo>/<issue>
```

Session journals live at:

```text
${XDG_STATE_HOME:-~/.local/state}/dev-space/sessions/<owner>/<repo>/<issue>/
```

The session pins the default-branch policy commit and accepted issue-spec hash.
Generated instructions contain the bounded specification and exclusions but
cannot replace tracked root policy.

Exit gate: retries converge on one branch/worktree/session, stale state is
diagnosable, and the human remote and identity remain unchanged.

### EPIC-CP6: Verification and ready-for-review handoff

Outcome: a worker can hand off verified work without receiving merge authority.

The handoff runs configured focused checks followed by full checks, records
structured results, pushes through the worker SSH route, and creates or updates
exactly one draft pull request. Only after those gates pass does it mark the
pull request ready and request the configured human reviewer. The body links
exactly one implementation issue and contains scope, acceptance evidence,
verification, risks, compatibility, rollback, and confirmation that unrelated
work is excluded.

Exit gate: interruption at every external step can be resumed without a second
branch or pull request, and no code path calls merge or enables auto-merge.

### EPIC-CP7: Repository enforcement

Outcome: repository-visible rules reject malformed worker pull requests while
privileged Project mutation stays local.

The Control Plane Contract check uses read-only repository permissions. It
validates branch/issue correspondence, one implementation issue, readiness
attestation predating work, author identity for Agent-ready work, complete PR
sections, acceptance criteria, and verification evidence. It does not query the
user-owned Project because repository `GITHUB_TOKEN` cannot access it.

The ruleset targets only `main` and requires pull requests, one CODEOWNER
approval from `@kmosoti`, stale-approval dismissal, resolved conversations,
unique `Fast QA Feedback` and `Control Plane Contract` checks, no force pushes,
no deletion of `main`, and no bypass actors. Repository auto-merge is disabled
as a separate setting.

`CP7-06` must resolve the remaining authority choice before activation:

1. use a worker-owned fork so `kz-harbringer` has no target-repository write
   permission and human-only merge is structurally enforced; or
2. retain target write permission and explicitly classify non-merge as a
   monitored procedural invariant, because standard rules do not reserve the
   merge action for one write-enabled collaborator.

Exit gate: the enforcement model matches the chosen authority guarantee and
the ruleset is activated only after both required checks exist on `main`.

### EPIC-CP8: Dev-space dogfood rollout

Outcome: one real, bounded change reaches a human-reviewed pull request and
then Done through the new workflow.

The pilot stops on any contract failure. Friction is recorded as new bounded
issues under a follow-up Epic; it is not silently folded into the pilot branch.
No `learning-os` resource is read for mutation or changed.

## Required verification

Each implementation issue selects the smallest relevant subset and declares it
in advance. The full gate is:

```text
uv run pytest --capture=sys
uv run ruff check .
uv run ruff format --check .
uv run vulture
PYO3_PYTHON=${PWD}/.venv/bin/python cargo test
PYO3_PYTHON=${PWD}/.venv/bin/python cargo clippy --all-targets --all-features -- -D warnings
```

Additional contract tests must cover:

- all legal and illegal lifecycle transitions;
- planner/worker authorization boundaries;
- missing or forged readiness attestations;
- deterministic, side-effect-free planning;
- idempotent apply and duplicate-resource conflicts;
- empty-account Project v2 creation followed by full-fidelity snapshot
  comparison;
- lossless Project field, option, item, and field-value round trips;
- explicit reporting and verification of API-inaccessible views and built-in
  workflows;
- proof that label drift is repaired from Project v2 and never overwrites it;
- wrong GitHub/SSH/commit identities;
- branch, worktree, PR, and operation-journal collisions;
- restart after every external side effect;
- policy pinning against worker-branch modification;
- API partial failure and unsupported capability reporting;
- workflow, Issue Form, PR-template, CODEOWNERS, and generated-instruction
  validation.

## Completion criteria

This rollout Epic is Done when:

- contract fixtures and all implementation checks pass;
- the dedicated `dev-space` Project v2 can be created from policy, exists, is
  uniquely identified, and has a complete post-apply snapshot;
- Project v2 is demonstrably authoritative for membership and live workflow
  values, while `.dev-space/project.toml` is authoritative for its desired
  schema and governance;
- every field, option, native-field mapping, item value, view, and built-in
  workflow is reconciled or explicitly recorded as verified human action;
- the full child issue/dependency tree is represented with native hierarchy
  where supported;
- one Agent-ready pilot Change completes start, handoff, human review, merge,
  and Done transition;
- no agent command, workflow, or bot can merge or enable auto-merge under the
  chosen authority model;
- repeated `doctor`, `plan`, and `apply` report no unexplained drift;
- the friction report and any follow-up Epic are recorded; and
- `learning-os` remains unchanged.
