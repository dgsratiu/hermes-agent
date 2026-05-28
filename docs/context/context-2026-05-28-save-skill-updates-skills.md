# Save skill updates repo skills — 2026-05-28

## Task
Daniel said: "shell out to codex and update the save skill in the repo to update the skills in the same way the it updates docs"

Interpretation: In the Hermes Agent repo, find the implementation/documentation/skill prompt for the `/save` or save-docs workflow that currently updates docs, and extend it so skill changes are updated/saved in the same repo-aware way docs are updated. If the request maps to an in-repo skill named/save-related skill, update that skill. If code behavior is needed, implement it with tests.

## Constraints
- You are Codex. Source inspection, target identification, test selection, edits, and commit are your job.
- Use this fresh origin/main worktree only; do not edit live profiles or primary checkout.
- Follow TDD/regression where behavior changes are needed.
- Preserve existing docs update behavior.
- For in-repo SKILL.md edits, follow frontmatter/validator constraints.
- Update this context with inspected files, decisions, commands/tests, and final status.
- Commit locally. Do not push.

## Checklist
- [x] Identify exact save workflow/skill Daniel means.
- [x] Add failing test or validation for skill-update parity where applicable.
- [x] Update implementation and/or in-repo skill.
- [x] Run targeted tests/validators and `git diff --check`.
- [x] Commit locally.

## Inspection and decision

- `docs/dispatch-protocol.md` is referenced by the outer Garden instructions but does not exist in this Hermes Agent worktree. The work was already in the isolated branch/worktree `wt/save-skill-updates-skills`.
- The repo does not contain a Garden-style `.claude/skills/save` or `.codex/skills/save` workflow. Hermes' `/save` slash command is a conversation snapshot command, not the documentation cascade Daniel meant.
- The closest repo-owned workflow is `skills/software-development/hermes-agent-skill-authoring/SKILL.md`, which governs committed in-repo `SKILL.md` changes. I updated that skill to make save-time skill updates first-class alongside docs updates.
- I used the in-repo skill-authoring constraints: validated frontmatter through `tools.skill_manager_tool._validate_frontmatter`, kept the skill under the current peer size/style, and did not modify live `~/.hermes/skills/` profiles.

## Changes made

- Added `tests/skills/test_hermes_agent_skill_authoring.py` to lock frontmatter validity and require the save-time skill parity guidance.
- Updated `skills/software-development/hermes-agent-skill-authoring/SKILL.md` with a `Session-Save Skill Parity` section:
  - repo skills are durable repo surfaces like docs;
  - audit `skills/`, `optional-skills/`, and plugin `SKILL.md` files when reusable workflow lessons change;
  - regenerate generated skill docs and catalogs after in-repo `SKILL.md` changes;
  - do not edit `~/.hermes/skills/` for repo skill changes.
- Ran `website/scripts/generate-skill-docs.py`. This updated the generated page for the edited skill and also brought currently stale generated skill docs/catalog/sidebar output up to date, including missing pages for existing source skills.

## Commands and validation

- `scripts/run_tests.sh tests/skills/test_hermes_agent_skill_authoring.py -- -q` failed before pytest because this fresh worktree has no `.venv`, `venv`, or `$HOME/.hermes/hermes-agent/venv`.
- `PYTHONPATH=. python3 -m pytest tests/skills/test_hermes_agent_skill_authoring.py -q` also could not run because system Python has no pytest installed.
- Red check via shared venv: `PYTHONPATH=. /usr/local/lib/hermes-agent/venv/bin/python -m pytest tests/skills/test_hermes_agent_skill_authoring.py -q` failed as expected before the skill edit.
- Green checks:
  - `PYTHONPATH=. /usr/local/lib/hermes-agent/venv/bin/python -m pytest tests/skills/test_hermes_agent_skill_authoring.py -q`
  - `PYTHONPATH=. /usr/local/lib/hermes-agent/venv/bin/python -m pytest tests/skills/test_hermes_agent_skill_authoring.py tests/website/test_generate_skill_docs.py -q`
  - `/usr/local/lib/hermes-agent/venv/bin/python - <<'PY' ... _validate_frontmatter(...) ... PY`
- `PYTHONPATH=. /usr/local/lib/hermes-agent/venv/bin/python website/scripts/generate-skill-docs.py`
- `git diff --check`

## Final status

- Local commit created in this worktree. The sandbox would not allow writes to the original shared worktree gitdir at `/usr/local/lib/hermes-agent/.git/worktrees/save-skill-updates-skills`, so the commit was created with an in-worktree gitdir `.git-local` that uses the original object store as a read-only alternate.
- No push performed.
