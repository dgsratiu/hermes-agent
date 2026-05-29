---
name: codex
description: "Run Codex /goal lanes for source work."
version: 1.1.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [coding-agent, codex, openai, worktrees, goal-mode]
    related_skills: [kanban-codex-lane, hermes-agent, subagent-driven-development]
---

# Codex CLI

Use this skill when a resident Hermes/Garden/Semantage agent needs coding,
source, documentation, tests, repo diagnostics, implementation planning, or
skill-authoring work done in a repository. The resident agent should usually
write a complete Codex prompt, launch Codex in an isolated git worktree, then
verify the result. Codex is the implementation lane; the resident owns scope,
safety, verification, commit hygiene, and final handoff.

## When to Use

Default to a Codex `/goal` lane for:

- Code changes, refactors, migrations, tests, and build fixes.
- Markdown/docs changes that are committed source.
- In-repo `SKILL.md`, generated skill docs, or workflow prompt edits.
- Non-trivial diagnostics where the likely result is a patch or repo change.
- Implementation planning that should become a durable repo artifact.
- Repeated or multi-step verification where Codex should keep objective state.

Direct resident tools remain fine for:

- Status checks, `git status`, `git diff`, test reruns, and artifact inspection.
- Reading redacted logs, checking process health, or non-code operational work.
- `/founders` notes, room messages, or other non-source coordination.
- Very small mechanical edits after reviewing a Codex-produced diff.
- Emergency changes when Codex is unavailable and the user wants the resident to continue.

## Prerequisites

- Codex installed: `npm install -g @openai/codex`
- OpenAI auth configured through `OPENAI_API_KEY` or Codex CLI OAuth.
- A git repository. Codex should not be run for source work outside git.
- `tmux` for durable interactive supervision.
- A clean isolated worktree for Codex writes.

For Hermes itself, `model.provider: openai-codex` uses Hermes-managed Codex
OAuth from `~/.hermes/auth.json` after `hermes auth add openai-codex`. The
standalone Codex CLI may use `~/.codex/auth.json`; do not print token files,
and do not treat a missing `OPENAI_API_KEY` as proof that Codex auth is absent.

## Default Recipe: tmux + Codex /goal

### 1. Create an isolated worktree

Do this before any source edits. Pick the correct base for the repo; for most
resident Garden/Hermes work this is `origin/main`.

```bash
REPO="/path/to/repo"
BASE="origin/main"
SLUG="codex-$(date -u +%Y%m%d%H%M%S)"
BRANCH="codex/$SLUG"
WORKTREE="$REPO/wt/$SLUG"

git -C "$REPO" fetch origin main
git -C "$REPO" worktree add -b "$BRANCH" "$WORKTREE" "$BASE"
git -C "$WORKTREE" status --short --branch
```

If the current checkout is already an isolated task worktree, Codex may work in
that worktree only when it is clean except for intentional resident-owned edits.
Otherwise create a sibling worktree and reconcile later.

### 2. Write the Codex prompt

The prompt is the contract. Include all context Codex needs without relying on
the resident conversation. Save the prompt somewhere outside the repo or in an
ignored artifact path.

```text
/goal Work in this repository only: <absolute WORKTREE>.

Task:
- <clear objective>

Scope:
- Allowed files/directories: <paths>
- Do not touch: secrets, runtime state, unrelated generated outputs, unrelated refactors.
- Preserve repo invariants: <AGENTS.md / CONTRIBUTING.md / project-specific rules>.

Workflow:
1. Inspect the relevant files and existing patterns.
2. Implement the smallest correct change in the isolated worktree.
3. Add or update focused tests/docs/skills as required.
4. Run these verification commands: <commands>.
5. Commit only if requested by the resident prompt; otherwise leave a reviewable diff.

Output:
- Summary of changes.
- Files changed.
- Tests/commands run with exact results.
- Known risks or follow-up.

Stop when the goal is achieved and the Stop/result hooks have finished.
```

For skill changes, include: validate frontmatter, run
`website/scripts/generate-skill-docs.py`, inspect generated docs/catalog diffs,
and run the targeted skill tests.

### 3. Launch Codex under tmux

Start Codex interactively so trust prompts, hook prompts, and goal state are
visible. Use a PTY/tmux session rather than a detached `codex exec` for real
repo work.

```bash
SESSION="$SLUG"
PROMPT_FILE="/tmp/$SLUG-codex-goal.txt"

tmux new-session -d -s "$SESSION" -c "$WORKTREE" 'codex --enable goals'
tmux capture-pane -t "$SESSION" -p -S -80
```

If Codex asks whether to trust the worktree, approve only after confirming the
path is the isolated worktree. If Codex asks about hooks, read the hook path and
approve only repo-owned hooks you understand. Reject prompts that request
secrets, global trust for an unknown repo, or uncontrolled external actions.

After trust and hook prompts are handled:

```bash
tmux load-buffer -b codex-goal "$PROMPT_FILE"
tmux paste-buffer -b codex-goal -t "$SESSION"
tmux send-keys -t "$SESSION" Enter
```

### 4. Monitor without taking over

Poll the pane and let Codex work. Do not edit the same worktree while Codex is
running.

```bash
tmux capture-pane -t "$SESSION" -p -S -200
tmux list-panes -t "$SESSION" -F '#{pane_id} dead=#{pane_dead} status=#{pane_dead_status} cmd=#{pane_current_command}'
```

Treat Codex as finished only after one of these is true:

- The pane reports the goal is achieved and Codex is idle.
- Codex exits successfully and the final result is visible.
- Codex explicitly blocks and asks for resident/user input.

If Stop/result hooks are configured, wait until their output or artifacts are
present before killing the session or reconciling the diff. A "Goal achieved"
line is not enough if hooks are still running.

Kill conditions:

- Codex requests secrets or production credentials.
- Codex writes outside the isolated worktree.
- It starts unrelated rewrites or dependency churn.
- It is stuck beyond the task budget with no useful partial artifact.

```bash
tmux kill-session -t "$SESSION"
```

### 5. Verify from the resident session

Codex-run tests are advisory. The resident must inspect and rerun verification.

```bash
git -C "$WORKTREE" status --short --branch
git -C "$WORKTREE" diff --stat
git -C "$WORKTREE" diff --check
git -C "$WORKTREE" diff
# then run the repo's targeted tests, docs checks, or skill validators
```

Check for secrets, runtime files, unrelated generated artifacts, stale lockfiles,
and edits outside the allowed scope. Accept by cherry-picking, merging, or
squashing into the resident-owned branch only after review and tests.

### 6. Clean up or preserve artifacts

Keep the worktree only if it is needed for review. Otherwise remove it after the
accepted diff is safely committed elsewhere.

```bash
git -C "$REPO" worktree remove "$WORKTREE"
git -C "$REPO" branch -D "$BRANCH"
```

## Legacy Fallback: codex exec

`codex exec` is a small one-shot fallback. Use it for throwaway scratch repos,
read-only analysis, or tiny bounded edits where no follow-up objective tracking
is needed. Do not use it as the default for long-running or real repo work.

```bash
codex exec --full-auto "In this clean isolated worktree, make the one-line docs typo fix and report the diff."
```

Avoid `--yolo` for real repositories. If you use it at all, limit it to
disposable scratch directories with no secrets and no production remotes.

## Prompt Quality Checklist

- [ ] Absolute worktree path and branch are stated.
- [ ] Scope and forbidden paths are explicit.
- [ ] Repo instructions and invariants are summarized or pointed to.
- [ ] Verification commands are exact.
- [ ] Commit expectations are explicit.
- [ ] Required final output is specified.
- [ ] Stop/result hook behavior is mentioned.
- [ ] The prompt says Codex must stop after the requested diff/summary.

## Resident Verification Checklist

- [ ] Codex ran in an isolated worktree/branch.
- [ ] Trust and hook prompts were handled deliberately.
- [ ] Resident inspected `git status`, `diff --stat`, and full diff.
- [ ] Resident reran targeted tests or validators.
- [ ] Generated docs/catalogs were regenerated when source skills changed.
- [ ] No secrets, runtime state, caches, or unrelated files are included.
- [ ] The final commit/push facts are reported without claiming deployment.
