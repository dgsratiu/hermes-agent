# Omega Goal design memory - 2026-05-29

## Task
Design, then implement, the Hermes `/omega-goal` feature from `/founders/omega-goal-concept.md` and `docs/plans/2026-05-29-omega-goal-implementation-design.md`.

User constraints:

- Create a fresh worktree from `origin/main`.
- Branch: `wt/omega-goal-design`.
- Worktree path: `/usr/local/lib/hermes-agent/wt/omega-goal-design`.
- Original pass was planning/design only.
- Follow-up implementation pass requested MVP code in this same worktree.
- Do not push.
- Write this execution-memory file and a concise implementation design artifact covering command UX, state/storage, mission lifecycle, worker orchestration, proof ledger, safety/budgets, MVP, and tests.

## Worktree

- Created with `git worktree add -b wt/omega-goal-design /usr/local/lib/hermes-agent/wt/omega-goal-design origin/main`.
- Base commit: `be27c3edc docs(skills): prefer Codex goal lanes for source work`.
- Root checkout had unrelated untracked `wt/` directory from existing worktrees; left untouched.

## Founder source

Read `/founders/omega-goal-concept.md`.

Core interpretation:

- `/goal` remains the one-session standing objective loop.
- `/omega-goal` is a durable mission operating system: mission room, war council, workstream graph, proof ledger, branch tournament, escalation ladder, and compressed founder updates.
- Non-negotiable: no "done" without proof.

## Repo surfaces inspected

- `AGENTS.md` for Hermes repo conventions and command architecture.
- `hermes_cli/commands.py` for slash command registry and generated downstream surfaces.
- `cli.py` `/goal`, `/subgoal`, `/background`, `/agents`, and queue handling.
- `gateway/run.py` `/goal`, command dispatch, Kanban notifier, and Kanban dispatcher loops.
- `tui_gateway/server.py` `/goal` and slash command behavior in the TUI bridge.
- `hermes_cli/goals.py` for current `/goal` state, judge, continuation, and budget model.
- `hermes_cli/kanban.py`, `hermes_cli/kanban_db.py`, and `hermes_cli/kanban_swarm.py` for durable task graphs, boards, workers, runs, events, comments, and swarms.
- `hermes_cli/config.py` for `goals` and `kanban` config patterns.
- Existing `docs/context/*` and `docs/plans/*` documents for artifact style.

## Design decision

Do not create a second scheduler. Design `/omega-goal` as an orchestration layer over the existing Kanban board, worker, run, event, notification, and dispatcher machinery.

MVP storage should use:

- one dedicated Kanban board per mission;
- a mission root task as the audit anchor;
- Kanban task links for the workstream graph;
- structured task comments/events for mission metadata, branch state, proof items, and blocker summaries;
- SessionDB `state_meta` only for the active mission pointer per chat/session.

A future version can promote proof items into first-class `omega_proofs` tables if query volume or dashboard needs justify it, but the first implementation should avoid new scheduling infrastructure.

## Artifact

Wrote implementation design:

- `docs/plans/2026-05-29-omega-goal-implementation-design.md`

## Implementation pass - 2026-05-29

Source of truth:

- `docs/plans/2026-05-29-omega-goal-implementation-design.md`

Implemented MVP:

- Registered `/omega-goal` and `/omega` in `hermes_cli/commands.py`; `/omega_goal` is an alias for Telegram-compatible underscore command names.
- Added `hermes_cli/omega_goal.py` as the shared orchestration module.
- Added CLI dispatch in `cli.py`.
- Added gateway dispatch in `gateway/run.py`.
- Added TUI `command.dispatch` parity in `tui_gateway/server.py`; `/omega-goal` and `/omega` bypass the slash-worker path like `/goal`.
- Added `omega_goal` defaults to `hermes_cli/config.py`.
- Added focused tests in `tests/hermes_cli/test_omega_goal.py`.
- Added TUI parity test in `tests/tui_gateway/test_omega_goal_command.py`.

MVP behavior:

- `/omega-goal <outcome>` creates deterministic mission/board ids like `omega-20260529-push-object-forward`.
- Each mission gets one dedicated Kanban board, one blocked root audit task, a planner task, four deterministic workstream tasks (`research`, `build`, `ops`, `proof`), a verifier task, and a synthesis task.
- Dry-run missions create the same graph but leave all dispatchable work unready.
- Active mission pointer is stored in `SessionDB.state_meta` under `omega:active:<session_id>`.
- Root comments store structured records:
  - `[omega:mission]`
  - `[omega:branch]`
  - `[omega:proof]`
  - `[omega:blocker]`
  - `[omega:update]`
- Proof ledger validates evidence types/status, renders required proof categories, and completion is gated on accepted proof for every required item.
- `/omega blockers` shows only `human_required=true` blockers by default.
- `/omega stop` blocks future/non-terminal tasks on the mission board without touching unrelated boards.
- `/omega promote <branch>` records shallow branch promotion state for future branch-tournament expansion.

Deferred:

- Dashboard surface.
- First-class omega DB tables.
- Automatic branch tournament task killing beyond recording promoted branch state.
- Automatic verifier extraction from worker completion comments.
- Skill/archive synthesis automation.

## Validation

- `uv run --extra dev python -m py_compile hermes_cli/omega_goal.py` passed.
- `uv run --extra dev ruff check hermes_cli/omega_goal.py cli.py gateway/run.py tui_gateway/server.py tests/hermes_cli/test_omega_goal.py tests/tui_gateway/test_omega_goal_command.py` passed.
- `scripts/run_tests.sh tests/hermes_cli/test_omega_goal.py tests/tui_gateway/test_omega_goal_command.py` passed: 11 tests.
- `scripts/run_tests.sh tests/tui_gateway/test_goal_command.py tests/gateway/test_gateway_command_help.py tests/cli/test_cli_prefix_matching.py` passed: 26 tests.
- `make check` could not run because this checkout has no `check` target.

## Final status

- Design docs written in the requested worktree.
- MVP implementation completed.
- Commit pending only if final verification remains green.
- No push performed.
