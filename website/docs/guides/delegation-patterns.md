---
sidebar_position: 13
title: "Delegation & Parallel Work"
description: "When and how to use subagent delegation — patterns for parallel research, code review, and multi-file work"
---

# Delegation & Parallel Work

Hermes can spawn isolated child agents to work on tasks in parallel. Each subagent gets its own conversation, terminal session, and toolset. Only the final summary comes back — intermediate tool calls never enter your context window.

For source-changing work, prefer a Codex `/goal` prompt in an isolated git
worktree under tmux. Use Hermes `delegate_task` for research, read-only review,
fresh-context analysis, and synthesis. Codex should be the default implementation
lane for code, committed docs, in-repo skills, tests, migrations, and diagnostics
likely to produce a patch.

For the full feature reference, see [Subagent Delegation](/user-guide/features/delegation).

---

## When to Delegate

**Good candidates for delegation:**
- Reasoning-heavy subtasks (debugging, code review, research synthesis)
- Tasks that would flood your context with intermediate data
- Parallel independent workstreams (research A and B simultaneously)
- Fresh-context tasks where you want the agent to approach without bias

**Use something else:**
- Single tool call → just use the tool directly
- Mechanical multi-step work with logic between steps → `execute_code`
- Tasks needing user interaction → subagents can't use `clarify`
- Source edits, docs edits, skill edits, tests, and implementation planning → create a Codex `/goal` prompt in an isolated worktree
- Durable long-running work that must outlive the current turn → `cronjob` or `terminal(background=True, notify_on_complete=True)`. `delegate_task` is **synchronous**: if the parent turn is interrupted, active children are cancelled and their work is discarded.

---

## Pattern: Parallel Research

Research three topics simultaneously and get structured summaries back:

```
Research these three topics in parallel:
1. Current state of WebAssembly outside the browser
2. RISC-V server chip adoption in 2025
3. Practical quantum computing applications

Focus on recent developments and key players.
```

Behind the scenes, Hermes uses:

```python
delegate_task(tasks=[
    {
        "goal": "Research WebAssembly outside the browser in 2025",
        "context": "Focus on: runtimes (Wasmtime, Wasmer), cloud/edge use cases, WASI progress",
        "toolsets": ["web"]
    },
    {
        "goal": "Research RISC-V server chip adoption",
        "context": "Focus on: server chips shipping, cloud providers adopting, software ecosystem",
        "toolsets": ["web"]
    },
    {
        "goal": "Research practical quantum computing applications",
        "context": "Focus on: error correction breakthroughs, real-world use cases, key companies",
        "toolsets": ["web"]
    }
])
```

All three run concurrently. Each subagent searches the web independently and returns a summary. The parent agent then synthesizes them into a coherent briefing.

---

## Pattern: Source Work via Codex /goal

For code, docs, tests, or skill changes, make the implementation lane a Codex
goal. The resident writes the prompt and verifies the result.

```bash
git -C "$REPO" fetch origin main
git -C "$REPO" worktree add -b codex/auth-review "$WORKTREE" origin/main
```

```text
/goal Work in this repository only: <WORKTREE>.
Review src/auth/ for security issues and fix any confirmed issue.
Focus on SQL injection, JWT validation, password handling, and session management.
Run: pytest tests/auth/ -v.
Report root cause, files changed, tests run, and risks. Stop after the diff.
Wait for Stop/result hooks before finalizing.
```

:::warning The Context Problem
Codex and subagents know **absolutely nothing** about your conversation. They
start fresh. If you hand off "fix the bug we were discussing," they have no idea
what bug you mean. Always pass file paths, error messages, project structure,
constraints, and verification commands explicitly.
:::

After Codex stops, the resident verifies:

```bash
git -C "$WORKTREE" status --short --branch
git -C "$WORKTREE" diff --stat
git -C "$WORKTREE" diff
git -C "$WORKTREE" diff --check
(cd "$WORKTREE" && pytest tests/auth/ -v)
```

---

## Pattern: Compare Alternatives

Evaluate multiple approaches to the same problem in parallel, then pick the best:

```
I need to add full-text search to our Django app. Evaluate three approaches
in parallel:
1. PostgreSQL tsvector (built-in)
2. Elasticsearch via django-elasticsearch-dsl
3. Meilisearch via meilisearch-python

For each: setup complexity, query capabilities, resource requirements,
and maintenance overhead. Compare them and recommend one.
```

Each subagent researches one option independently. Because they're isolated, there's no cross-contamination — each evaluation stands on its own merits. The parent agent gets all three summaries and makes the comparison.

---

## Pattern: Multi-File Refactoring

Split a large refactoring task across separate Codex worktrees only when the
file sets are independent. Do not run two implementation lanes against the same
files.

```text
Codex lane A:
/goal Work in <WORKTREE_A>. Refactor only src/handlers/users.py,
src/handlers/auth.py, src/handlers/billing.py to use APIResponse.
Run pytest tests/handlers/ -v.

Codex lane B:
/goal Work in <WORKTREE_B>. Update only sdk/python/client.py,
sdk/python/models.py, and sdk/python/tests/test_client.py for response handling.
Run pytest sdk/python/tests/test_client.py -v.

Codex lane C:
/goal Work in <WORKTREE_C>. Update only docs/api/ response examples and add the
Response Format section to docs/api/overview.md. Do not touch code.
```

:::tip
Each Codex lane gets its own worktree and tmux session. If two lanes might touch
the same file, serialize them or merge the first accepted diff before launching
the second.
:::

---

## Pattern: Gather Then Analyze

Use `execute_code` for mechanical data gathering, then delegate the reasoning-heavy analysis:

```python
# Step 1: Mechanical gathering (execute_code is better here — no reasoning needed)
execute_code("""
from hermes_tools import web_search, web_extract

results = []
for query in ["AI funding Q1 2026", "AI startup acquisitions 2026", "AI IPOs 2026"]:
    r = web_search(query, limit=5)
    for item in r["data"]["web"]:
        results.append({"title": item["title"], "url": item["url"], "desc": item["description"]})

# Extract full content from top 5 most relevant
urls = [r["url"] for r in results[:5]]
content = web_extract(urls)

# Save for the analysis step
import json
with open("/tmp/ai-funding-data.json", "w") as f:
    json.dump({"search_results": results, "extracted": content["results"]}, f)
print(f"Collected {len(results)} results, extracted {len(content['results'])} pages")
""")

# Step 2: Reasoning-heavy analysis (delegation is better here)
delegate_task(
    goal="Analyze AI funding data and write a market report",
    context="""Raw data at /tmp/ai-funding-data.json contains search results and
    extracted web pages about AI funding, acquisitions, and IPOs in Q1 2026.
    Write a structured market report: key deals, trends, notable players,
    and outlook. Focus on deals over $100M.""",
    toolsets=["terminal", "file"]
)
```

This is often the most efficient pattern: `execute_code` handles the 10+ sequential tool calls cheaply, then a subagent does the single expensive reasoning task with a clean context.

---

## Toolset Selection

Choose toolsets based on what the subagent needs:

| Task type | Toolsets | Why |
|-----------|----------|-----|
| Web research | `["web"]` | web_search + web_extract only |
| Source-changing code/docs/skills work | Codex `/goal` worktree | Durable objective tracking and isolated diff |
| Read-only code review | `["file"]` or Codex read-only prompt | Fresh context without mutation |
| Full-stack implementation | Codex `/goal` worktree, optionally with web context in prompt | Keeps edits isolated |
| Read-only analysis | `["file"]` | Can only read files, no shell |

Restricting toolsets keeps the subagent focused and prevents accidental side effects (like a research subagent running shell commands).

---

## Constraints

- **Default 3 parallel tasks**: batches default to 3 concurrent subagents (configurable via `delegation.max_concurrent_children` in config.yaml, no hard ceiling, only a floor of 1)
- **Nested delegation is opt-in**: leaf subagents (default) cannot call `delegate_task`, `clarify`, `memory`, `send_message`, or `execute_code`. Orchestrator subagents (`role="orchestrator"`) retain `delegate_task` for further delegation, but only when `delegation.max_spawn_depth` is raised above the default of 1 (1-3 supported); the other four remain blocked. Disable globally via `delegation.orchestrator_enabled: false`.

### Tuning Concurrency and Depth

| Config | Default | Range | Effect |
|--------|---------|-------|--------|
| `max_concurrent_children` | 3 | >=1 | Parallel batch size per `delegate_task` call |
| `max_spawn_depth` | 1 | 1-3 | How many delegation levels can spawn further |

Example: running 30 parallel workers with nested subagents:

```yaml
delegation:
  max_concurrent_children: 30
  max_spawn_depth: 2
```

- **Separate terminals** — each subagent gets its own terminal session with separate working directory and state
- **No conversation history** — subagents see only the `goal` and `context` the parent agent passes when calling `delegate_task`
- **Default 50 iterations** — set `max_iterations` lower for simple tasks to save cost
- **Not durable** — `delegate_task` is synchronous and runs inside the parent turn. If the parent is interrupted (new user message, `/stop`, `/new`), all active children are cancelled (`status="interrupted"`) and their work is discarded. For work that must outlive the current turn, use `cronjob` or `terminal(background=True, notify_on_complete=True)`.

---

## Tips

**Be specific in goals.** "Fix the bug" is too vague. "Fix the TypeError in api/handlers.py line 47 where process_request() receives None from parse_body()" gives the subagent enough to work with.

**Include file paths.** Codex and subagents don't know your project structure.
Always include absolute paths to relevant files, the project root, allowed scope,
forbidden paths, and the test command.

**Use delegation for context isolation.** Sometimes you want a fresh perspective. Delegating forces you to articulate the problem clearly, and the subagent approaches it without the assumptions that built up in your conversation.

**Check results.** Codex and subagent summaries are just that — summaries. If an
agent says "fixed the bug and tests pass," verify by running the tests yourself
and reading the diff.

---

*For the complete delegation reference — all parameters, ACP integration, and advanced configuration — see [Subagent Delegation](/user-guide/features/delegation).*
