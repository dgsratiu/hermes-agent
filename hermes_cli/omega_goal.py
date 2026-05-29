"""Kanban-backed /omega-goal orchestration primitives.

The MVP keeps omega missions deliberately low-tech: one Kanban board per
mission, one blocked root task as the audit anchor, ordinary Kanban tasks for
the first workstream graph, and structured JSON comments on the root task for
mission metadata, proof, blockers, and branch state.
"""

from __future__ import annotations

import json
import re
import shlex
import time
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Iterable


MISSION_PREFIX = "[omega:mission] "
BRANCH_PREFIX = "[omega:branch] "
PROOF_PREFIX = "[omega:proof] "
BLOCKER_PREFIX = "[omega:blocker] "
UPDATE_PREFIX = "[omega:update] "

ACTIVE_META_PREFIX = "omega:active:"

DEFAULT_PROOF_REQUIRED = (
    "mission brief",
    "workstream outputs",
    "verifier acceptance",
)

DEFAULT_WORKSTREAM_LANES = (
    "research",
    "build",
    "ops",
    "proof",
)

VALID_EVIDENCE_TYPES = frozenset(
    {
        "test",
        "file",
        "url",
        "screenshot",
        "commit",
        "deploy",
        "api_response",
        "human_ack",
        "physical_observation",
    }
)

VALID_PROOF_STATUSES = frozenset({"pending", "accepted", "rejected"})


class OmegaGoalError(RuntimeError):
    """User-facing omega command error."""


@dataclass(frozen=True)
class OmegaGoalArgs:
    outcome: str
    deadline: str | None = None
    budget_turns: int | None = None
    max_workers: int | None = None
    dry_run: bool = False


@dataclass(frozen=True)
class OmegaCommand:
    name: str
    action: str
    goal_args: OmegaGoalArgs | None = None
    mission_id: str | None = None
    branch: str | None = None
    json_output: bool = False


@dataclass
class OmegaMission:
    mission_id: str
    outcome: str
    state: str
    proof_required: list[str]
    deadline: str | None
    budget: dict[str, int]
    root_task_id: str
    board: str
    created_at: float
    source_platform: str | None = None
    source_chat: str | None = None
    dry_run: bool = False

    def to_json_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_json_dict(cls, raw: dict[str, Any]) -> "OmegaMission":
        proof_required = raw.get("proof_required") or DEFAULT_PROOF_REQUIRED
        budget = raw.get("budget") or {}
        return cls(
            mission_id=str(raw.get("mission_id") or ""),
            outcome=str(raw.get("outcome") or ""),
            state=str(raw.get("state") or "planning"),
            proof_required=[str(x) for x in proof_required if str(x).strip()],
            deadline=(
                str(raw["deadline"])
                if raw.get("deadline") is not None and str(raw.get("deadline")).strip()
                else None
            ),
            budget={
                "max_workers": int(budget.get("max_workers", 4) or 4),
                "max_tasks": int(budget.get("max_tasks", 20) or 20),
                "max_branches": int(budget.get("max_branches", 3) or 3),
                "max_worker_turns_total": int(
                    budget.get("max_worker_turns_total", 80) or 80
                ),
                "max_runtime_seconds_per_task": int(
                    budget.get("max_runtime_seconds_per_task", 14400) or 14400
                ),
            },
            root_task_id=str(raw.get("root_task_id") or ""),
            board=str(raw.get("board") or raw.get("mission_id") or ""),
            created_at=float(raw.get("created_at", 0.0) or 0.0),
            source_platform=(
                str(raw.get("source_platform"))
                if raw.get("source_platform") is not None
                else None
            ),
            source_chat=(
                str(raw.get("source_chat")) if raw.get("source_chat") is not None else None
            ),
            dry_run=bool(raw.get("dry_run", False)),
        )


@dataclass
class ProofEntry:
    proof_id: str
    mission_id: str
    claim: str
    evidence_type: str
    uri: str
    summary: str
    status: str = "pending"
    requirement: str | None = None
    task_id: str | None = None
    run_id: int | None = None
    checksum: str | None = None
    created_by: str | None = None
    validated_by: str | None = None
    created_at: float = field(default_factory=lambda: float(time.time()))

    def to_json_dict(self) -> dict[str, Any]:
        data = asdict(self)
        return {k: v for k, v in data.items() if v is not None}

    @classmethod
    def from_json_dict(cls, raw: dict[str, Any]) -> "ProofEntry":
        return cls(
            proof_id=str(raw.get("proof_id") or ""),
            mission_id=str(raw.get("mission_id") or ""),
            task_id=str(raw["task_id"]) if raw.get("task_id") else None,
            run_id=int(raw["run_id"]) if raw.get("run_id") is not None else None,
            claim=str(raw.get("claim") or ""),
            evidence_type=str(raw.get("evidence_type") or ""),
            uri=str(raw.get("uri") or ""),
            summary=str(raw.get("summary") or ""),
            checksum=str(raw["checksum"]) if raw.get("checksum") else None,
            status=str(raw.get("status") or "pending"),
            requirement=str(raw["requirement"]) if raw.get("requirement") else None,
            created_by=str(raw["created_by"]) if raw.get("created_by") else None,
            validated_by=(
                str(raw["validated_by"]) if raw.get("validated_by") else None
            ),
            created_at=float(raw.get("created_at", 0.0) or time.time()),
        )


@dataclass
class BlockerEntry:
    blocker_id: str
    mission_id: str
    summary: str
    human_required: bool = True
    task_id: str | None = None
    decision_needed: str | None = None
    evidence: str | None = None
    created_at: float = field(default_factory=lambda: float(time.time()))

    def to_json_dict(self) -> dict[str, Any]:
        data = asdict(self)
        return {k: v for k, v in data.items() if v is not None}

    @classmethod
    def from_json_dict(cls, raw: dict[str, Any]) -> "BlockerEntry":
        return cls(
            blocker_id=str(raw.get("blocker_id") or ""),
            mission_id=str(raw.get("mission_id") or ""),
            task_id=str(raw["task_id"]) if raw.get("task_id") else None,
            summary=str(raw.get("summary") or ""),
            human_required=bool(raw.get("human_required", True)),
            decision_needed=(
                str(raw["decision_needed"]) if raw.get("decision_needed") else None
            ),
            evidence=str(raw["evidence"]) if raw.get("evidence") else None,
            created_at=float(raw.get("created_at", 0.0) or time.time()),
        )


def _today_utc() -> date:
    return datetime.now(timezone.utc).date()


def safe_outcome_slug(outcome: str, *, max_len: int = 56) -> str:
    """Return a lowercase, path-safe slug for a mission outcome."""
    normalized = unicodedata.normalize("NFKD", outcome)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_text.lower()).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)
    if not slug:
        slug = "mission"
    return slug[:max_len].rstrip("-") or "mission"


def mission_id_for_outcome(outcome: str, *, on_date: date | datetime | None = None) -> str:
    """Create the deterministic board/mission id for an outcome."""
    if on_date is None:
        day = _today_utc()
    elif isinstance(on_date, datetime):
        day = on_date.date()
    else:
        day = on_date
    return f"omega-{day:%Y%m%d}-{safe_outcome_slug(outcome)}"


def parse_command(command: str) -> OmegaCommand:
    """Parse /omega-goal and /omega slash command text."""
    text = (command or "").strip()
    if not text:
        raise OmegaGoalError("Usage: /omega-goal <outcome> or /omega status")
    if text.startswith("/"):
        text = text[1:]
    try:
        tokens = shlex.split(text)
    except ValueError as exc:
        raise OmegaGoalError(f"Could not parse omega command: {exc}") from exc
    if not tokens:
        raise OmegaGoalError("Usage: /omega-goal <outcome> or /omega status")

    name = tokens[0].lower().replace("_", "-")
    rest = tokens[1:]
    if name == "omega-goal":
        return OmegaCommand(
            name="omega-goal",
            action="create",
            goal_args=_parse_goal_args(rest),
        )
    if name != "omega":
        raise OmegaGoalError("Usage: /omega-goal <outcome> or /omega status")
    return _parse_omega_args(rest)


def _parse_goal_args(tokens: list[str]) -> OmegaGoalArgs:
    deadline: str | None = None
    budget_turns: int | None = None
    max_workers: int | None = None
    dry_run = False
    outcome: list[str] = []

    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok == "--dry-run":
            dry_run = True
            i += 1
            continue
        if tok in {"--deadline", "--budget-turns", "--max-workers"}:
            if i + 1 >= len(tokens):
                raise OmegaGoalError(f"{tok} requires a value")
            value = tokens[i + 1]
            if tok == "--deadline":
                deadline = value
            elif tok == "--budget-turns":
                budget_turns = _positive_int(value, tok)
            elif tok == "--max-workers":
                max_workers = _positive_int(value, tok)
            i += 2
            continue
        if tok.startswith("--"):
            raise OmegaGoalError(f"Unknown /omega-goal option: {tok}")
        outcome.append(tok)
        i += 1

    outcome_text = " ".join(outcome).strip()
    if not outcome_text:
        raise OmegaGoalError("Usage: /omega-goal <outcome>")
    return OmegaGoalArgs(
        outcome=outcome_text,
        deadline=deadline,
        budget_turns=budget_turns,
        max_workers=max_workers,
        dry_run=dry_run,
    )


def _parse_omega_args(tokens: list[str]) -> OmegaCommand:
    if not tokens:
        return OmegaCommand(name="omega", action="status")
    action = tokens[0].lower()
    rest = tokens[1:]
    if action not in {"status", "proof", "blockers", "stop", "promote"}:
        raise OmegaGoalError(
            "Usage: /omega [status|proof|blockers|stop|promote] ..."
        )
    json_output = False
    mission_id: str | None = None
    branch: str | None = None

    if action == "promote":
        if not rest:
            raise OmegaGoalError("Usage: /omega promote <branch> [mission]")
        branch = rest[0]
        if len(rest) > 1:
            mission_id = rest[1]
        if len(rest) > 2:
            raise OmegaGoalError("Usage: /omega promote <branch> [mission]")
    else:
        for tok in rest:
            if tok == "--json" and action == "proof":
                json_output = True
                continue
            if tok.startswith("--"):
                raise OmegaGoalError(f"Unknown /omega {action} option: {tok}")
            if mission_id is not None:
                raise OmegaGoalError(f"Too many arguments for /omega {action}")
            mission_id = tok

    return OmegaCommand(
        name="omega",
        action=action,
        mission_id=mission_id,
        branch=branch,
        json_output=json_output,
    )


def _positive_int(value: str, flag: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise OmegaGoalError(f"{flag} must be a positive integer") from exc
    if parsed <= 0:
        raise OmegaGoalError(f"{flag} must be a positive integer")
    return parsed


def structured_comment(prefix: str, payload: dict[str, Any]) -> str:
    return prefix + json.dumps(payload, sort_keys=True, ensure_ascii=False)


def parse_structured_comment(body: str, prefix: str) -> dict[str, Any] | None:
    if not body or not body.startswith(prefix):
        return None
    raw = body[len(prefix) :].strip()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def iter_structured_comments(
    comments: Iterable[Any],
    prefix: str,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for comment in comments:
        parsed = parse_structured_comment(getattr(comment, "body", "") or "", prefix)
        if parsed is not None:
            out.append(parsed)
    return out


def create_mission(
    args: OmegaGoalArgs,
    *,
    session_id: str | None = None,
    source_platform: str | None = None,
    source_chat: str | None = None,
    now: date | datetime | None = None,
) -> OmegaMission:
    """Create or update the Kanban-backed omega mission skeleton."""
    from hermes_cli import kanban_db as kb

    mission_id = mission_id_for_outcome(args.outcome, on_date=now)
    cfg = _omega_config()
    budget = {
        "max_workers": int(args.max_workers or cfg.get("max_workers", 4) or 4),
        "max_tasks": int(cfg.get("max_tasks", 20) or 20),
        "max_branches": int(cfg.get("max_branches", 3) or 3),
        "max_worker_turns_total": int(args.budget_turns or 80),
        "max_runtime_seconds_per_task": 14400,
    }

    kb.create_board(
        mission_id,
        name=f"Omega: {args.outcome[:72]}",
        description=f"Omega mission for: {args.outcome}",
        icon="omega",
        color="#d97706",
    )
    conn = kb.connect(board=mission_id)
    try:
        root_id = kb.create_task(
            conn,
            title=f"Omega mission: {args.outcome}",
            body=_root_task_body(args.outcome),
            assignee=None,
            created_by="omega-goal",
            workspace_kind="scratch",
            tenant="omega",
            idempotency_key=_root_key(mission_id),
            initial_status="blocked",
            session_id=session_id,
            board=mission_id,
        )
        mission = OmegaMission(
            mission_id=mission_id,
            outcome=args.outcome,
            state="planning",
            proof_required=list(DEFAULT_PROOF_REQUIRED),
            deadline=args.deadline,
            budget=budget,
            root_task_id=root_id,
            board=mission_id,
            created_at=float(time.time()),
            source_platform=source_platform,
            source_chat=source_chat,
            dry_run=args.dry_run,
        )
        _write_mission_record(conn, mission)
        _create_initial_graph(conn, mission, dry_run=args.dry_run, session_id=session_id)
        kb.add_comment(
            conn,
            root_id,
            "omega-goal",
            structured_comment(
                BRANCH_PREFIX,
                {
                    "mission_id": mission_id,
                    "branches": [],
                    "promoted": None,
                    "created_at": mission.created_at,
                },
            ),
        )
    finally:
        conn.close()

    if session_id:
        set_active_mission(session_id, mission)
    return mission


def _omega_config() -> dict[str, Any]:
    try:
        from hermes_cli.config import load_config

        cfg = load_config()
    except Exception:
        return {}
    omega_cfg = cfg.get("omega_goal") if isinstance(cfg, dict) else None
    return omega_cfg if isinstance(omega_cfg, dict) else {}


def _root_task_body(outcome: str) -> str:
    return (
        "Omega mission audit root.\n\n"
        f"Outcome: {outcome}\n\n"
        "This card anchors structured [omega:*] comments. Do not dispatch this "
        "root as worker work; use child tasks for planner, workstreams, verifier, "
        "and synthesis. Done is invalid without accepted proof for every required "
        "proof item."
    )


def _root_key(mission_id: str) -> str:
    return f"omega:{mission_id}:root"


def _task_key(mission_id: str, key: str) -> str:
    return f"omega:{mission_id}:task:{key}"


def _write_mission_record(conn: Any, mission: OmegaMission) -> None:
    from hermes_cli import kanban_db as kb

    kb.add_comment(
        conn,
        mission.root_task_id,
        "omega-goal",
        structured_comment(MISSION_PREFIX, mission.to_json_dict()),
    )


def _create_initial_graph(
    conn: Any,
    mission: OmegaMission,
    *,
    dry_run: bool,
    session_id: str | None,
) -> None:
    from hermes_cli import kanban_db as kb

    runtime = int(mission.budget.get("max_runtime_seconds_per_task", 14400))
    planner = kb.create_task(
        conn,
        title=f"Omega planner: {mission.outcome}",
        body=_planner_body(mission),
        assignee=None,
        created_by="omega-goal",
        tenant="omega",
        priority=100,
        idempotency_key=_task_key(mission.mission_id, "planner"),
        initial_status="blocked" if dry_run else "running",
        max_runtime_seconds=runtime,
        session_id=session_id,
        board=mission.board,
    )
    kb.add_comment(
        conn,
        planner,
        "omega-goal",
        structured_comment(
            UPDATE_PREFIX,
            {
                "mission_id": mission.mission_id,
                "role": "planner",
                "dry_run": dry_run,
            },
        ),
    )

    workstreams: list[str] = []
    for lane in DEFAULT_WORKSTREAM_LANES:
        tid = kb.create_task(
            conn,
            title=f"Omega {lane}: {mission.outcome}",
            body=_workstream_body(mission, lane),
            assignee=None,
            created_by="omega-goal",
            tenant="omega",
            priority=80,
            parents=(planner,),
            idempotency_key=_task_key(mission.mission_id, f"workstream:{lane}"),
            max_runtime_seconds=runtime,
            session_id=session_id,
            board=mission.board,
        )
        kb.add_comment(
            conn,
            tid,
            "omega-goal",
            structured_comment(
                UPDATE_PREFIX,
                {
                    "mission_id": mission.mission_id,
                    "role": "workstream",
                    "lane": lane,
                    "branch": "main",
                },
            ),
        )
        workstreams.append(tid)

    verifier = kb.create_task(
        conn,
        title=f"Omega verifier: {mission.outcome}",
        body=_verifier_body(mission),
        assignee=None,
        created_by="omega-goal",
        tenant="omega",
        priority=70,
        parents=tuple(workstreams),
        idempotency_key=_task_key(mission.mission_id, "verifier"),
        max_runtime_seconds=runtime,
        session_id=session_id,
        board=mission.board,
    )
    kb.add_comment(
        conn,
        verifier,
        "omega-goal",
        structured_comment(
            UPDATE_PREFIX,
            {"mission_id": mission.mission_id, "role": "verifier"},
        ),
    )

    synthesizer = kb.create_task(
        conn,
        title=f"Omega synthesis: {mission.outcome}",
        body=_synthesis_body(mission),
        assignee=None,
        created_by="omega-goal",
        tenant="omega",
        priority=60,
        parents=(verifier,),
        idempotency_key=_task_key(mission.mission_id, "synthesis"),
        max_runtime_seconds=runtime,
        session_id=session_id,
        board=mission.board,
    )
    kb.add_comment(
        conn,
        synthesizer,
        "omega-goal",
        structured_comment(
            UPDATE_PREFIX,
            {"mission_id": mission.mission_id, "role": "synthesis"},
        ),
    )


def _planner_body(mission: OmegaMission) -> str:
    return (
        f"Mission: {mission.outcome}\n"
        f"Mission id: {mission.mission_id}\n"
        f"Deadline: {mission.deadline or 'none'}\n\n"
        "Produce the mission brief, constraints, first workstream graph, and "
        "proof plan. No done without proof."
    )


def _workstream_body(mission: OmegaMission, lane: str) -> str:
    return (
        f"Mission: {mission.outcome}\n"
        f"Mission id: {mission.mission_id}\n"
        f"Lane: {lane}\n\n"
        "Execute the next useful work in this lane. Complete with concrete "
        "handoff notes and propose proof only when evidence exists. No done "
        "without proof."
    )


def _verifier_body(mission: OmegaMission) -> str:
    required = "\n".join(f"- {item}" for item in mission.proof_required)
    return (
        f"Mission: {mission.outcome}\n"
        f"Mission id: {mission.mission_id}\n\n"
        "Verify completed workstreams and accept or reject proof. Required proof:\n"
        f"{required}\n\n"
        "Mission completion is allowed only after every required proof item has "
        "accepted evidence."
    )


def _synthesis_body(mission: OmegaMission) -> str:
    return (
        f"Mission: {mission.outcome}\n"
        f"Mission id: {mission.mission_id}\n\n"
        "Write the compressed mission update, reusable lessons, and archive-ready "
        "summary after verifier acceptance."
    )


def set_active_mission(session_id: str, mission: OmegaMission) -> None:
    db = _session_db()
    if db is None:
        return
    payload = {
        "mission_id": mission.mission_id,
        "board": mission.board,
        "root_task_id": mission.root_task_id,
        "created_at": mission.created_at,
        "source_platform": mission.source_platform,
        "source_chat": mission.source_chat,
    }
    db.set_meta(ACTIVE_META_PREFIX + session_id, json.dumps(payload, sort_keys=True))


def get_active_pointer(session_id: str | None) -> dict[str, Any] | None:
    if not session_id:
        return None
    db = _session_db()
    if db is None:
        return None
    raw = db.get_meta(ACTIVE_META_PREFIX + session_id)
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _session_db() -> Any | None:
    try:
        from hermes_state import SessionDB

        return SessionDB()
    except Exception:
        return None


def load_mission(
    mission_id: str | None = None,
    *,
    session_id: str | None = None,
) -> tuple[OmegaMission, Any]:
    """Load a mission and return ``(mission, open_kanban_connection)``."""
    from hermes_cli import kanban_db as kb

    pointer = None if mission_id else get_active_pointer(session_id)
    resolved = mission_id or (pointer or {}).get("mission_id")
    if not resolved:
        raise OmegaGoalError("No active omega mission. Start one with /omega-goal <outcome>.")

    board = str((pointer or {}).get("board") or resolved)
    conn = kb.connect(board=board)
    try:
        root_id = str((pointer or {}).get("root_task_id") or "")
        if mission_id or not root_id:
            root_id = _find_root_task_id(conn, resolved)
        if not root_id:
            raise OmegaGoalError(f"Omega mission not found: {resolved}")
        comments = kb.list_comments(conn, root_id)
        records = iter_structured_comments(comments, MISSION_PREFIX)
        if not records:
            raise OmegaGoalError(f"Omega mission metadata missing: {resolved}")
        mission = OmegaMission.from_json_dict(records[-1])
        mission.root_task_id = root_id
        mission.board = board
    except Exception:
        conn.close()
        raise
    return mission, conn


def _find_root_task_id(conn: Any, mission_id: str) -> str:
    row = conn.execute(
        "SELECT id FROM tasks WHERE idempotency_key = ? AND status != 'archived' "
        "ORDER BY created_at ASC LIMIT 1",
        (_root_key(mission_id),),
    ).fetchone()
    return str(row["id"]) if row else ""


def list_proofs(conn: Any, mission: OmegaMission) -> list[ProofEntry]:
    from hermes_cli import kanban_db as kb

    comments = kb.list_comments(conn, mission.root_task_id)
    entries: list[ProofEntry] = []
    for raw in iter_structured_comments(comments, PROOF_PREFIX):
        try:
            entry = ProofEntry.from_json_dict(raw)
            validate_proof_entry(entry)
        except (TypeError, ValueError):
            continue
        if entry.mission_id == mission.mission_id:
            entries.append(entry)
    return entries


def append_proof(conn: Any, mission: OmegaMission, proof: ProofEntry | dict[str, Any]) -> int:
    from hermes_cli import kanban_db as kb

    entry = proof if isinstance(proof, ProofEntry) else ProofEntry.from_json_dict(proof)
    if not entry.mission_id:
        entry.mission_id = mission.mission_id
    validate_proof_entry(entry)
    return kb.add_comment(
        conn,
        mission.root_task_id,
        entry.created_by or "omega-proof",
        structured_comment(PROOF_PREFIX, entry.to_json_dict()),
    )


def validate_proof_entry(entry: ProofEntry) -> None:
    if not entry.proof_id:
        raise ValueError("proof_id is required")
    if not entry.mission_id:
        raise ValueError("mission_id is required")
    if entry.evidence_type not in VALID_EVIDENCE_TYPES:
        raise ValueError(f"invalid evidence_type: {entry.evidence_type}")
    if entry.status not in VALID_PROOF_STATUSES:
        raise ValueError(f"invalid proof status: {entry.status}")
    if not entry.claim.strip():
        raise ValueError("claim is required")
    if not entry.summary.strip():
        raise ValueError("summary is required")


def completion_gate(
    mission: OmegaMission,
    proofs: Iterable[ProofEntry],
) -> tuple[bool, list[str]]:
    accepted_requirements = {
        (p.requirement or "").strip().lower()
        for p in proofs
        if p.status == "accepted"
    }
    missing = [
        req
        for req in mission.proof_required
        if req.strip().lower() not in accepted_requirements
    ]
    return not missing, missing


def mark_completed(mission_id: str | None = None, *, session_id: str | None = None) -> str:
    mission, conn = load_mission(mission_id, session_id=session_id)
    try:
        proofs = list_proofs(conn, mission)
        ok, missing = completion_gate(mission, proofs)
        if not ok:
            raise OmegaGoalError(
                "Cannot complete omega mission; missing accepted proof: "
                + ", ".join(missing)
            )
        mission.state = "completed"
        _write_mission_record(conn, mission)
        return f"Omega mission {mission.mission_id} completed."
    finally:
        conn.close()


def list_blockers(conn: Any, mission: OmegaMission, *, human_only: bool = True) -> list[BlockerEntry]:
    from hermes_cli import kanban_db as kb

    comments = kb.list_comments(conn, mission.root_task_id)
    entries: list[BlockerEntry] = []
    for raw in iter_structured_comments(comments, BLOCKER_PREFIX):
        entry = BlockerEntry.from_json_dict(raw)
        if entry.mission_id != mission.mission_id:
            continue
        if human_only and not entry.human_required:
            continue
        entries.append(entry)

    if not human_only:
        known_task_ids = {b.task_id for b in entries if b.task_id}
        for task in kb.list_tasks(conn, status="blocked", include_archived=False):
            if task.id == mission.root_task_id or task.id in known_task_ids:
                continue
            entries.append(
                BlockerEntry(
                    blocker_id=f"task-{task.id}",
                    mission_id=mission.mission_id,
                    task_id=task.id,
                    summary=task.title,
                    human_required=False,
                )
            )
    return entries


def append_blocker(
    conn: Any,
    mission: OmegaMission,
    blocker: BlockerEntry | dict[str, Any],
) -> int:
    from hermes_cli import kanban_db as kb

    entry = blocker if isinstance(blocker, BlockerEntry) else BlockerEntry.from_json_dict(blocker)
    if not entry.mission_id:
        entry.mission_id = mission.mission_id
    if not entry.blocker_id:
        raise ValueError("blocker_id is required")
    if not entry.summary.strip():
        raise ValueError("summary is required")
    return kb.add_comment(
        conn,
        mission.root_task_id,
        "omega-blocker",
        structured_comment(BLOCKER_PREFIX, entry.to_json_dict()),
    )


def render_created(mission: OmegaMission) -> str:
    suffix = " (dry-run)" if mission.dry_run else ""
    return (
        f"Omega mission {mission.mission_id} created\n"
        f"State: {mission.state}{suffix}\n"
        f"Board: {mission.board}\n"
        "Next: planner/verifier graph queued\n"
        "Controls: /omega status | /omega proof | /omega blockers | /omega stop"
    )


def render_status(mission_id: str | None = None, *, session_id: str | None = None) -> str:
    from hermes_cli import kanban_db as kb

    mission, conn = load_mission(mission_id, session_id=session_id)
    try:
        tasks = [
            t
            for t in kb.list_tasks(conn, include_archived=False, order_by="created")
            if t.id != mission.root_task_id
        ]
        done = sum(1 for t in tasks if t.status == "done")
        total = len(tasks)
        running = sum(1 for t in tasks if t.status == "running")
        proofs = list_proofs(conn, mission)
        ok, missing = completion_gate(mission, proofs)
        accepted_count = len(mission.proof_required) - len(missing)
        blockers = list_blockers(conn, mission, human_only=True)
        blocked_tasks = [t.title for t in tasks if t.status == "blocked"]
        blocked = [b.summary for b in blockers] + blocked_tasks[:3]
        next_items = [t.title for t in tasks if t.status in {"ready", "todo", "running"}]
        next_text = "; ".join(_shorten(x, 72) for x in next_items[:2]) or "no queued tasks"
        blocked_text = ", ".join(_shorten(x, 56) for x in blocked[:3]) or "none"
        proof_status = "complete" if ok else f"{accepted_count}/{len(mission.proof_required)} accepted"
        return (
            f"{mission.outcome}: {mission.state}\n"
            f"Done: {done}/{total} tasks, proof {proof_status}\n"
            f"Blocked: {blocked_text}\n"
            f"Next: {next_text}"
            + (f"\nRunning: {running}" if running else "")
        )
    finally:
        conn.close()


def render_proof(
    mission_id: str | None = None,
    *,
    session_id: str | None = None,
    json_output: bool = False,
) -> str:
    mission, conn = load_mission(mission_id, session_id=session_id)
    try:
        proofs = list_proofs(conn, mission)
        ok, missing = completion_gate(mission, proofs)
        if json_output:
            payload = {
                "mission_id": mission.mission_id,
                "proof_required": mission.proof_required,
                "proof": [p.to_json_dict() for p in proofs],
                "can_complete": ok,
                "missing": missing,
            }
            return json.dumps(payload, indent=2, sort_keys=True)

        by_req: dict[str, list[ProofEntry]] = {req: [] for req in mission.proof_required}
        other: list[ProofEntry] = []
        for proof in proofs:
            key = proof.requirement or ""
            matched = next(
                (req for req in mission.proof_required if req.lower() == key.lower()),
                None,
            )
            if matched:
                by_req[matched].append(proof)
            else:
                other.append(proof)

        accepted_count = len(mission.proof_required) - len(missing)
        lines = [
            f"Proof for {mission.mission_id}",
            f"Accepted: {accepted_count}/{len(mission.proof_required)} required",
        ]
        for req in mission.proof_required:
            entries = by_req.get(req) or []
            if not entries:
                lines.append(f"- {req}: missing")
                continue
            rendered = "; ".join(_render_proof_entry(p) for p in entries)
            lines.append(f"- {req}: {rendered}")
        if other:
            lines.append("Other proof:")
            lines.extend(f"- {_render_proof_entry(p)}" for p in other)
        return "\n".join(lines)
    finally:
        conn.close()


def _render_proof_entry(proof: ProofEntry) -> str:
    return (
        f"{proof.status} {proof.proof_id} - "
        f"{_shorten(proof.summary or proof.claim, 96)}"
    )


def render_blockers(mission_id: str | None = None, *, session_id: str | None = None) -> str:
    mission, conn = load_mission(mission_id, session_id=session_id)
    try:
        blockers = list_blockers(conn, mission, human_only=True)
        if not blockers:
            return f"No human blockers for {mission.mission_id}."
        lines = [f"Human blockers for {mission.mission_id}:"]
        for blocker in blockers:
            task = f" (task {blocker.task_id})" if blocker.task_id else ""
            decision = (
                f" Decision: {blocker.decision_needed}"
                if blocker.decision_needed
                else ""
            )
            lines.append(f"- {_shorten(blocker.summary, 120)}{task}.{decision}")
        return "\n".join(lines)
    finally:
        conn.close()


def stop_mission(mission_id: str | None = None, *, session_id: str | None = None) -> str:
    from hermes_cli import kanban_db as kb

    mission, conn = load_mission(mission_id, session_id=session_id)
    paused = 0
    try:
        tasks = [
            t
            for t in kb.list_tasks(conn, include_archived=False)
            if t.id != mission.root_task_id and t.status not in {"done", "archived", "blocked"}
        ]
        for task in tasks:
            if task.status in {"ready", "running"}:
                if kb.block_task(conn, task.id, reason="omega mission stopped"):
                    paused += 1
                continue
            with kb.write_txn(conn):
                cur = conn.execute(
                    "UPDATE tasks SET status = 'blocked' "
                    "WHERE id = ? AND status IN ('todo', 'scheduled', 'review')",
                    (task.id,),
                )
                if cur.rowcount:
                    paused += 1
            if task.status in {"todo", "scheduled", "review"}:
                kb.add_comment(conn, task.id, "omega-goal", "BLOCKED: omega mission stopped")

        mission.state = "cancelled"
        _write_mission_record(conn, mission)
        kb.add_comment(
            conn,
            mission.root_task_id,
            "omega-goal",
            structured_comment(
                UPDATE_PREFIX,
                {
                    "mission_id": mission.mission_id,
                    "state": "cancelled",
                    "paused_tasks": paused,
                    "created_at": time.time(),
                },
            ),
        )
    finally:
        conn.close()
    return f"Omega mission {mission.mission_id} stopped.\nPaused: {paused} future task(s)."


def promote_branch(
    branch: str,
    mission_id: str | None = None,
    *,
    session_id: str | None = None,
) -> str:
    from hermes_cli import kanban_db as kb

    clean_branch = safe_outcome_slug(branch, max_len=40)
    mission, conn = load_mission(mission_id, session_id=session_id)
    try:
        kb.add_comment(
            conn,
            mission.root_task_id,
            "omega-goal",
            structured_comment(
                BRANCH_PREFIX,
                {
                    "mission_id": mission.mission_id,
                    "promoted": clean_branch,
                    "selected_at": time.time(),
                },
            ),
        )
    finally:
        conn.close()
    return f"Omega mission {mission.mission_id}: promoted branch {clean_branch}."


def run_slash(
    command: str,
    *,
    session_id: str | None = None,
    source_platform: str | None = None,
    source_chat: str | None = None,
) -> str:
    parsed = parse_command(command)
    if parsed.name == "omega-goal":
        assert parsed.goal_args is not None
        mission = create_mission(
            parsed.goal_args,
            session_id=session_id,
            source_platform=source_platform,
            source_chat=source_chat,
        )
        return render_created(mission)

    if parsed.action == "status":
        return render_status(parsed.mission_id, session_id=session_id)
    if parsed.action == "proof":
        return render_proof(
            parsed.mission_id,
            session_id=session_id,
            json_output=parsed.json_output,
        )
    if parsed.action == "blockers":
        return render_blockers(parsed.mission_id, session_id=session_id)
    if parsed.action == "stop":
        return stop_mission(parsed.mission_id, session_id=session_id)
    if parsed.action == "promote":
        assert parsed.branch is not None
        return promote_branch(
            parsed.branch,
            parsed.mission_id,
            session_id=session_id,
        )
    raise OmegaGoalError(f"Unsupported omega action: {parsed.action}")


def _shorten(text: str, max_len: int) -> str:
    clean = " ".join(str(text).split())
    if len(clean) <= max_len:
        return clean
    return clean[: max_len - 3].rstrip() + "..."
