# Omega Goal implementation design

## Objective

`/omega-goal <outcome>` turns a vague, high-leverage outcome into a durable Hermes mission: scoped workstreams, spawned workers, proof-gated progress, blocker escalation, and terse status updates. `/goal` stays the lightweight one-session loop; `/omega-goal` is for multi-agent campaigns where "done" is invalid without evidence.

Founder concept source: `/founders/omega-goal-concept.md`.

## Constraints

- Reuse Hermes primitives before adding infrastructure: command registry, SessionDB `state_meta`, Kanban boards/tasks/runs/events/comments, gateway dispatcher, gateway notifier, and TUI slash dispatch.
- Do not build a second scheduler. Kanban remains the worker claim, retry, heartbeat, crash, timeout, and dependency engine.
- Work across CLI, gateway, and TUI. Start with a shared command module and thin callers, matching `/goal` and `/kanban`.
- Mission state must survive process restart, profile changes, and gateway restarts.
- "Done" requires accepted proof for every required proof item.

## Command UX

Register two slash commands in `hermes_cli/commands.py`:

- `/omega-goal <outcome>`: create and start a new mission.
- `/omega [status|proof|blockers|stop|promote] ...`: inspect and control the active mission.

Primary forms:

```text
/omega-goal <outcome>
/omega status [mission]
/omega proof [mission] [--json]
/omega blockers [mission]
/omega stop [mission]
/omega promote <branch> [mission]
```

Optional flags for `/omega-goal` can be parsed with `shlex` but should stay small in MVP:

- `--deadline <text>`: stored in the mission brief, not interpreted as a scheduler guarantee.
- `--budget-turns <n>`: total worker-turn soft cap.
- `--max-workers <n>`: mission concurrency cap layered over `kanban.max_spawn`.
- `--dry-run`: produce the mission brief and planned graph without promoting workstreams to `ready`.

CLI and gateway handlers should return the same terse shape:

```text
Omega mission omega-20260529-so101-push-object created
State: planning
Board: omega-20260529-so101-push-object
Next: planner/verifier graph queued
Controls: /omega status | /omega proof | /omega blockers | /omega stop
```

`/omega status` should compress internally large state into:

```text
SO101 push object: active
Done: 3/9 workstreams, proof 2/5 accepted
Blocked: camera mount decision, printer profile
Next: verifier reviews dataset run; builder retries TPU insert print
```

## State and storage model

Use a dedicated Kanban board per mission:

- board slug: `omega-<yyyymmdd>-<safe-outcome-slug>`;
- root task: `Omega mission: <outcome>`;
- root task comments/events are the mission blackboard and audit anchor;
- workstreams are normal Kanban tasks linked to the root or to dependencies;
- workers complete/block via existing `kanban_complete`, `kanban_block`, `kanban_heartbeat`, and comments;
- runs, PIDs, heartbeats, logs, retry counters, and failure counters remain in `task_runs` and task fields.

Store the active mission pointer in SessionDB `state_meta`:

- key: `omega:active:<session_id>`;
- value: JSON with `mission_id`, `board`, `root_task_id`, `created_at`, `source_platform`, and `source_chat`.

Store mission metadata as structured JSON comments on the root task, using prefixes similar to `hermes_cli.kanban_swarm.BLACKBOARD_PREFIX`:

- `[omega:mission] {...}` for brief/status/config;
- `[omega:branch] {...}` for branch tournament state;
- `[omega:proof] {...}` for proof ledger entries;
- `[omega:blocker] {...}` for human-needed blockers;
- `[omega:update] {...}` for compressed updates sent to founders/users.

This avoids schema churn in MVP. If dashboard/query needs grow, promote these records into an `omega.db` or Kanban-adjacent tables later without changing command UX.

Mission record fields:

```json
{
  "mission_id": "omega-20260529-so101-push-object",
  "outcome": "make SO101 push an object forward by Sunday",
  "state": "planning|active|blocked|verifying|paused|completed|cancelled|archived",
  "proof_required": ["demo video", "test log", "physical observation"],
  "deadline": "Sunday",
  "budget": {
    "max_workers": 4,
    "max_tasks": 20,
    "max_branches": 3,
    "max_worker_turns_total": 80,
    "max_runtime_seconds_per_task": 14400
  },
  "root_task_id": "KBN-...",
  "board": "omega-20260529-so101-push-object"
}
```

## Mission lifecycle

1. Ingest: `/omega-goal <outcome>` creates a mission id, board, root task, and active pointer.
2. Brief: planner turns outcome into end state, constraints, proof required, deadline, budget, roles, and first workstream graph.
3. Graph: create Kanban tasks for lanes such as research, build, hardware, ops, data, proof, critic, verifier, and synthesis.
4. Dispatch: gateway Kanban dispatcher picks up `ready` tasks and spawns profile workers.
5. Work loop: workers use existing Kanban lifecycle tools and write structured evidence in completion metadata/comments.
6. Review: critic/verifier tasks inspect handoffs and convert accepted evidence into proof ledger entries.
7. Escalate: blockers become visible only when human leverage is real: decision, money, credentials, physical action, irreversible external side effect.
8. Promote: if branch tournament is active, `/omega promote <branch>` marks the selected branch as canonical and pauses/kills losing branch tasks.
9. Complete: mission can enter `completed` only when verifier accepts all required proof.
10. Archive: final synthesis writes reusable memory/skill suggestions and closes the board or leaves it inspectable.

## Worker orchestration

Roles are profiles, not new agent classes. Add `omega_goal` config with defaults:

```yaml
omega_goal:
  enabled: true
  planner_profile: ""
  builder_profile: ""
  researcher_profile: ""
  critic_profile: ""
  verifier_profile: ""
  synthesizer_profile: ""
  concierge_profile: ""
  max_workers: 4
  max_tasks: 20
  max_branches: 3
  require_start_confirm: false
```

Empty profile means current/default profile, matching Kanban's fallback style.

Implementation should add `hermes_cli/omega_goal.py` as the shared orchestration module:

- parse command strings;
- create/load mission records;
- create Kanban board/root/tasks;
- read task/run/comment/event state;
- render terse status/proof/blocker output;
- stop/pause missions by moving unstarted tasks out of `ready` and blocking/cancelling running tasks conservatively;
- promote a branch by updating structured branch records and task statuses.

The first graph can be deterministic and testable:

- planner task;
- 2-5 workstream tasks from planner output or fallback lanes;
- verifier task depending on workstream tasks;
- synthesizer/update task depending on verifier.

Branch tournament support should be represented in state from day one but can be shallow in MVP: branches are labels on task metadata/comments; promotion changes which branch's tasks are eligible to run.

## Proof ledger

Proof item shape:

```json
{
  "proof_id": "proof-001",
  "mission_id": "omega-...",
  "task_id": "KBN-...",
  "run_id": 12,
  "claim": "SO101 pushed the object forward 30 cm twice",
  "evidence_type": "test|file|url|screenshot|commit|deploy|api_response|human_ack|physical_observation",
  "uri": "/abs/path/or/url/or/session-ref",
  "summary": "short human-readable evidence summary",
  "checksum": "optional sha256 for files",
  "status": "pending|accepted|rejected",
  "created_by": "worker-profile",
  "validated_by": "verifier-profile",
  "created_at": 1779999999
}
```

Rules:

- Worker completions may propose proof, but only verifier/critic tasks accept it.
- `/omega proof` lists all proof grouped by required proof category.
- Mission completion checks accepted proof, not task status alone.
- A "blocked/unachievable" completion also needs proof: blocker evidence, attempted actions, and exact human decision needed.

## Safety and budget controls

Use layered controls rather than one global kill switch:

- hard cap mission task count before creating graph;
- cap live workers via `omega_goal.max_workers` and Kanban `max_spawn`;
- per-task `max_runtime_seconds`;
- task `max_retries` and existing Kanban failure circuit breaker;
- per-mission worker-turn counter stored in mission metadata;
- optional model override per task for cheap workers vs strict verifier;
- inherit existing approvals for dangerous tools and slash confirmations;
- stop command should mark future tasks paused/blocked and avoid killing unrelated Kanban work;
- no external send, deploy, purchase, credential request, destructive file action, or physical-world act is considered approved by the mission itself.

Escalation ladder:

- Ask humans only for decisions with real leverage.
- `/omega blockers` filters for `human_required=true`.
- Non-human failures stay inside worker retries, verifier feedback, or branch killing.

## MVP slice

Implement in this order:

1. Shared command registry entries and CLI handler shell for `/omega-goal` and `/omega`.
2. `hermes_cli/omega_goal.py` with deterministic mission id, board creation, root task, active pointer, and status rendering.
3. Kanban-backed mission graph creation with planner, workstreams, verifier, and synthesizer tasks.
4. Structured proof comments/events and `/omega proof`.
5. `/omega blockers` from blocked tasks plus `[omega:blocker]` records.
6. Gateway and TUI slash dispatch parity.
7. Stop/pause control.
8. Branch labels and `/omega promote` as a second PR if needed; keep the state shape in MVP so it is not a migration later.

Deliberately defer:

- dedicated dashboard;
- platform topic/thread auto-creation;
- first-class `omega.db`;
- automatic skill writing at archive time;
- full branch tournament strategy generation.

## Tests

Unit tests:

- command parser accepts `/omega-goal`, `/omega status`, `/omega proof`, `/omega blockers`, `/omega stop`, and `/omega promote <branch>`;
- mission id and board slug generation are deterministic and path-safe;
- mission JSON comment round-trips and ignores malformed unrelated comments;
- proof ledger rejects invalid evidence types and renders pending/accepted/rejected proof;
- completion gate refuses `completed` when required proof lacks accepted evidence;
- blocker rendering shows only `human_required=true` by default.

Kanban integration tests:

- start creates a board, root task, workstream tasks, verifier dependency, and synthesizer dependency;
- dry-run creates the brief/root but does not promote workstreams to `ready`;
- stop prevents future task dispatch without touching unrelated boards;
- status summarizes task counts, blocked tasks, active runs, and proof counts;
- promotion updates branch state and prevents losing branch tasks from running.

CLI/gateway/TUI tests:

- CLI handlers call the shared module and print compact status;
- gateway command bypass works while an agent is running for inspection commands;
- `/omega-goal` queues no ordinary chat turn unless explicitly designed to do so;
- TUI slash dispatch returns structured output and does not depend on the old CLI `_pending_input` queue.

Worker/proof tests:

- worker prompt/context includes mission id, proof requirements, and "no done without proof";
- worker completion metadata with artifacts is visible to the verifier;
- verifier acceptance writes proof records;
- mission done path requires accepted proof.

Failure tests:

- corrupt/missing Kanban board errors are loud and do not silently create a different mission;
- repeated worker crashes respect Kanban failure limits;
- budget exhaustion pauses the mission and appears in `/omega blockers` or `/omega status`;
- malformed mission comments do not crash status/proof commands.
