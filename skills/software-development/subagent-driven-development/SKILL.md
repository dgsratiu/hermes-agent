---
name: subagent-driven-development
description: "Coordinate Codex lanes with two-stage review."
version: 1.2.0
author: Hermes Agent (adapted from obra/superpowers)
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [delegation, subagent, implementation, workflow, parallel]
    related_skills: [writing-plans, requesting-code-review, test-driven-development]
---

# Subagent-Driven Development

## Overview

Execute implementation plans by launching a fresh Codex `/goal` lane per task,
then applying systematic two-stage review. For source changes, the implementer
is normally Codex in an isolated worktree. Hermes stays the controller:
it writes the prompt, monitors the lane, reviews the diff, reruns tests, and
decides what to accept.

**Core principle:** Fresh Codex lane per task + two-stage review (spec then
quality) = high quality, inspectable iteration.

## When to Use

Use this skill when:
- You have an implementation plan (from writing-plans skill or user requirements)
- Tasks are mostly independent
- Quality and spec compliance are important
- You want automated review between tasks
- The work changes code, docs, tests, workflows, or in-repo skills

Do not use this as permission for the resident to directly implement source
changes. Direct resident tools remain appropriate for status checks, redacted
logs, non-code ops, and verification. If Codex is unavailable, say that and use
the smallest safe fallback workflow.

**vs. direct resident implementation:**
- Fresh Codex context per task avoids accumulated assumptions
- Isolated worktrees keep untrusted edits reviewable
- Automated review process catches issues early
- Consistent quality checks across all tasks

## The Process

### 1. Read and Parse Plan

Read the plan file. Extract ALL tasks with their full text and context upfront. Create a todo list:

```python
# Read the plan
read_file("docs/plans/feature-plan.md")

# Create todo list with all tasks
todo([
    {"id": "task-1", "content": "Create User model with email field", "status": "pending"},
    {"id": "task-2", "content": "Add password hashing utility", "status": "pending"},
    {"id": "task-3", "content": "Create login endpoint", "status": "pending"},
])
```

**Key:** Read the plan ONCE. Extract everything. The Codex prompt may point at
the plan file, but it must also include the full task text, constraints, allowed
paths, and verification commands so Codex does not have to infer context from
the resident conversation.

### 2. Per-Task Workflow

For EACH task in the plan:

#### Step 1: Launch Implementer Codex Lane

Use the `codex` skill's tmux + `/goal` recipe. Create a clean isolated
worktree, write a complete prompt, launch Codex, and let it produce a diff or
small commits.

Example task prompt:

```text
/goal Work in this repository only: /abs/path/to/worktree.

Implement Task 1: Create User model with email and password_hash fields.

Task from plan:
- Create: src/models/user.py
- Add User class with email (str) and password_hash (str) fields
- Use bcrypt for password hashing
- Include __repr__ for debugging

Follow TDD:
1. Write failing test in tests/models/test_user.py.
2. Run: pytest tests/models/test_user.py -v and confirm it fails for the expected reason.
3. Write minimal implementation.
4. Run: pytest tests/models/test_user.py -v and confirm pass.
5. Run: pytest tests/ -q and report exact result.

Project context:
- Python 3.11, Flask app in src/app.py
- Existing models in src/models/
- Tests use pytest, run from project root
- bcrypt already in requirements.txt

Output summary, files changed, tests run, and risks. Stop after the diff and
wait for Stop/result hooks to finish.
```

Codex-run tests are advisory. The resident must rerun the relevant tests before
accepting or merging the lane.

#### Step 2: Dispatch Spec Compliance Reviewer

After the implementer completes, verify against the original spec:

```python
delegate_task(
    goal="Review if implementation matches the spec from the plan",
    context="""
    ORIGINAL TASK SPEC:
    - Create src/models/user.py with User class
    - Fields: email (str), password_hash (str)
    - Use bcrypt for password hashing
    - Include __repr__

    CHECK:
    - [ ] All requirements from spec implemented?
    - [ ] File paths match spec?
    - [ ] Function signatures match spec?
    - [ ] Behavior matches expected?
    - [ ] Nothing extra added (no scope creep)?

    OUTPUT: PASS or list of specific spec gaps to fix.
    """,
    toolsets=['file']
)
```

**If spec issues found:** Create a focused Codex fix prompt or, for a tiny
mechanical correction, patch it directly after reviewing the diff. Re-run spec
review. Continue only when spec-compliant.

#### Step 3: Dispatch Code Quality Reviewer

After spec compliance passes:

```python
delegate_task(
    goal="Review code quality for Task 1 implementation",
    context="""
    FILES TO REVIEW:
    - src/models/user.py
    - tests/models/test_user.py

    CHECK:
    - [ ] Follows project conventions and style?
    - [ ] Proper error handling?
    - [ ] Clear variable/function names?
    - [ ] Adequate test coverage?
    - [ ] No obvious bugs or missed edge cases?
    - [ ] No security issues?

    OUTPUT FORMAT:
    - Critical Issues: [must fix before proceeding]
    - Important Issues: [should fix]
    - Minor Issues: [optional]
    - Verdict: APPROVED or REQUEST_CHANGES
    """,
    toolsets=['file']
)
```

**If quality issues found:** Create a focused Codex fix prompt or make a small
reviewed follow-up edit, then re-review. Continue only when approved.

#### Step 4: Mark Complete

```python
todo([{"id": "task-1", "content": "Create User model with email field", "status": "completed"}], merge=True)
```

### 3. Final Review

After ALL tasks are complete, dispatch a final integration reviewer:

```python
delegate_task(
    goal="Review the entire implementation for consistency and integration issues",
    context="""
    All tasks from the plan are complete. Review the full implementation:
    - Do all components work together?
    - Any inconsistencies between tasks?
    - All tests passing?
    - Ready for merge?
    """,
    toolsets=['terminal', 'file']
)
```

### 4. Verify and Commit

```bash
# Run full test suite
pytest tests/ -q

# Review all changes
git diff --stat

# Final commit if needed
git add -A && git commit -m "feat: complete [feature name] implementation"
```

## Task Granularity

**Each task = 2-5 minutes of focused work.**

**Too big:**
- "Implement user authentication system"

**Right size:**
- "Create User model with email and password fields"
- "Add password hashing function"
- "Create login endpoint"
- "Add JWT token generation"
- "Create registration endpoint"

## Red Flags — Never Do These

- Start implementation without a plan
- Skip reviews (spec compliance OR code quality)
- Proceed with unfixed critical/important issues
- Start multiple Codex implementation lanes for tasks that touch the same files
- Make Codex infer the plan from conversation history (provide full task text in the prompt)
- Skip scene-setting context (Codex needs to understand where the task fits)
- Ignore Codex questions or trust/hook prompts (answer or decide before letting it proceed)
- Accept "close enough" on spec compliance
- Skip review loops (reviewer found issues → implementer fixes → review again)
- Let implementer self-review replace actual review (both are needed)
- **Start code quality review before spec compliance is PASS** (wrong order)
- Move to next task while either review has open issues

## Handling Issues

### If Subagent Asks Questions

- Answer clearly and completely
- Provide additional context if needed
- Don't rush them into implementation

### If Reviewer Finds Issues

- A focused Codex fix lane (or a tiny reviewed resident follow-up) fixes them
- Reviewer reviews again
- Repeat until approved
- Don't skip the re-review

### If Subagent Fails a Task

- Launch a new focused Codex fix prompt with specific instructions about what went wrong
- Don't directly rewrite substantial source in the controller session (context pollution and weak audit trail)

## Efficiency Notes

**Why fresh Codex lane per task:**
- Prevents context pollution from accumulated state
- Each Codex prompt gets clean, focused context
- No confusion from prior tasks' code or reasoning
- Each diff is isolated in a worktree/branch until accepted

**Why two-stage review:**
- Spec review catches under/over-building early
- Quality review ensures the implementation is well-built
- Catches issues before they compound across tasks

**Cost trade-off:**
- More agent invocations (Codex implementer + 2 reviewers per task)
- But catches issues early (cheaper than debugging compounded problems later)

## Integration with Other Skills

### With writing-plans

This skill EXECUTES plans created by the writing-plans skill:
1. User requirements → writing-plans → implementation plan
2. Implementation plan → Codex `/goal` lanes → Hermes review/tests → working code

### With test-driven-development

Codex implementer prompts should require TDD:
1. Write failing test first
2. Implement minimal code
3. Verify test passes
4. Commit

Include TDD instructions in every implementer context.

### With requesting-code-review

The two-stage review process IS the code review. For final integration review, use the requesting-code-review skill's review dimensions.

### With systematic-debugging

If Codex encounters bugs during implementation:
1. Follow systematic-debugging process
2. Find root cause before fixing
3. Write regression test
4. Resume implementation

## Example Workflow

```
[Read plan: docs/plans/auth-feature.md]
[Create todo list with 5 tasks]

--- Task 1: Create User model ---
[Start Codex implementer lane]
  Codex: "Should email be unique?"
  You: "Yes, email must be unique"
  Codex: Implemented, 3/3 tests passing, diff ready.

[Dispatch spec reviewer]
  Spec reviewer: ✅ PASS — all requirements met

[Dispatch quality reviewer]
  Quality reviewer: ✅ APPROVED — clean code, good tests

[Mark Task 1 complete]

--- Task 2: Password hashing ---
[Start Codex implementer lane]
  Codex: No questions, implemented, 5/5 tests passing.

[Dispatch spec reviewer]
  Spec reviewer: ❌ Missing: password strength validation (spec says "min 8 chars")

[Implementer fixes]
  Codex fix lane: Added validation, 7/7 tests passing.

[Dispatch spec reviewer again]
  Spec reviewer: ✅ PASS

[Dispatch quality reviewer]
  Quality reviewer: Important: Magic number 8, extract to constant
  Codex fix lane: Extracted MIN_PASSWORD_LENGTH constant
  Quality reviewer: ✅ APPROVED

[Mark Task 2 complete]

... (continue for all tasks)

[After all tasks: dispatch final integration reviewer]
[Run full test suite: all passing]
[Done!]
```

## Remember

```
Fresh Codex lane per task
Two-stage review every time
Spec compliance FIRST
Code quality SECOND
Never skip reviews
Catch issues early
```

**Quality is not an accident. It's the result of systematic process.**

## Further reading (load when relevant)

When the orchestration involves significant context usage, long review loops, or complex validation checkpoints, load these references for the specific discipline:

- **`references/context-budget-discipline.md`** — Four-tier context degradation model (PEAK / GOOD / DEGRADING / POOR), read-depth rules that scale with context window size, and early warning signs of silent degradation. Load when a run will clearly consume significant context (multi-phase plans, many subagents, large artifacts).
- **`references/gates-taxonomy.md`** — The four canonical gate types (Pre-flight, Revision, Escalation, Abort) with behavior, recovery, and examples. Load when designing or reviewing any workflow that has validation checkpoints — use the vocabulary explicitly so each gate has defined entry, failure behavior, and resumption rules.

Both references adapted from gsd-build/get-shit-done (MIT © 2025 Lex Christopherson).
