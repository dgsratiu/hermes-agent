from __future__ import annotations

from datetime import date

import pytest


def test_command_registry_exposes_omega_commands():
    from hermes_cli.commands import GATEWAY_KNOWN_COMMANDS, SUBCOMMANDS, resolve_command

    assert resolve_command("omega-goal").name == "omega-goal"
    assert resolve_command("omega_goal").name == "omega-goal"
    assert resolve_command("omega").name == "omega"
    assert "omega-goal" in GATEWAY_KNOWN_COMMANDS
    assert "omega" in GATEWAY_KNOWN_COMMANDS
    assert SUBCOMMANDS["/omega"] == ["status", "proof", "blockers", "stop", "promote"]


def test_parser_accepts_mvp_forms():
    from hermes_cli.omega_goal import parse_command

    create = parse_command(
        '/omega-goal make SO101 push an object --deadline Sunday '
        "--budget-turns 12 --max-workers 3 --dry-run"
    )
    assert create.name == "omega-goal"
    assert create.action == "create"
    assert create.goal_args is not None
    assert create.goal_args.outcome == "make SO101 push an object"
    assert create.goal_args.deadline == "Sunday"
    assert create.goal_args.budget_turns == 12
    assert create.goal_args.max_workers == 3
    assert create.goal_args.dry_run is True

    assert parse_command("/omega status omega-1").mission_id == "omega-1"
    proof = parse_command("/omega proof omega-1 --json")
    assert proof.action == "proof"
    assert proof.json_output is True
    assert parse_command("/omega blockers").action == "blockers"
    assert parse_command("/omega stop omega-1").action == "stop"
    promote = parse_command("/omega promote branch-a omega-1")
    assert promote.action == "promote"
    assert promote.branch == "branch-a"
    assert promote.mission_id == "omega-1"


def test_mission_id_is_deterministic_and_path_safe():
    from hermes_cli.omega_goal import mission_id_for_outcome

    mission_id = mission_id_for_outcome(
        "SO101 push object! / by Sunday",
        on_date=date(2026, 5, 29),
    )
    assert mission_id == "omega-20260529-so101-push-object-by-sunday"
    assert "/" not in mission_id
    assert mission_id.lower() == mission_id


def test_dry_run_creation_creates_board_root_and_unready_graph():
    from hermes_cli import kanban_db as kb
    from hermes_cli.omega_goal import (
        MISSION_PREFIX,
        OmegaGoalArgs,
        create_mission,
        get_active_pointer,
        parse_structured_comment,
    )

    mission = create_mission(
        OmegaGoalArgs("push object forward", dry_run=True),
        session_id="sid-omega",
        source_platform="cli",
        now=date(2026, 5, 29),
    )
    assert mission.mission_id == "omega-20260529-push-object-forward"
    assert mission.dry_run is True
    assert get_active_pointer("sid-omega")["mission_id"] == mission.mission_id

    conn = kb.connect(board=mission.board)
    try:
        root = kb.get_task(conn, mission.root_task_id)
        assert root is not None
        assert root.title == "Omega mission: push object forward"
        assert root.status == "blocked"

        tasks = [
            t
            for t in kb.list_tasks(conn, include_archived=False, order_by="created")
            if t.id != mission.root_task_id
        ]
        assert len(tasks) == 7
        assert {t.status for t in tasks} <= {"blocked", "todo"}
        assert not [t for t in tasks if t.status == "ready"]
        assert any(t.title.startswith("Omega planner:") for t in tasks)
        assert any(t.title.startswith("Omega verifier:") for t in tasks)
        assert any(t.title.startswith("Omega synthesis:") for t in tasks)

        comments = kb.list_comments(conn, mission.root_task_id)
        mission_records = [
            parse_structured_comment(c.body, MISSION_PREFIX)
            for c in comments
            if parse_structured_comment(c.body, MISSION_PREFIX)
        ]
        assert mission_records[-1]["mission_id"] == mission.mission_id
    finally:
        conn.close()


def test_explicit_mission_lookup_ignores_different_active_pointer():
    from hermes_cli.omega_goal import OmegaGoalArgs, create_mission, render_status

    first = create_mission(
        OmegaGoalArgs("first mission"),
        session_id="sid-explicit",
        now=date(2026, 5, 29),
    )
    second = create_mission(
        OmegaGoalArgs("second mission"),
        session_id="sid-explicit",
        now=date(2026, 5, 29),
    )

    assert first.mission_id != second.mission_id
    assert "first mission" in render_status(first.mission_id, session_id="sid-explicit")


def test_proof_ledger_validation_and_rendering():
    from hermes_cli import kanban_db as kb
    from hermes_cli.omega_goal import (
        OmegaGoalArgs,
        ProofEntry,
        append_proof,
        create_mission,
        render_proof,
    )

    mission = create_mission(
        OmegaGoalArgs("collect physical proof"),
        session_id="sid-proof",
        now=date(2026, 5, 29),
    )
    conn = kb.connect(board=mission.board)
    try:
        append_proof(
            conn,
            mission,
            ProofEntry(
                proof_id="proof-001",
                mission_id=mission.mission_id,
                requirement="mission brief",
                claim="Planner wrote the brief",
                evidence_type="file",
                uri="/tmp/brief.md",
                summary="Brief artifact exists",
                status="accepted",
            ),
        )
        append_proof(
            conn,
            mission,
            ProofEntry(
                proof_id="proof-002",
                mission_id=mission.mission_id,
                requirement="workstream outputs",
                claim="Workstream produced data",
                evidence_type="test",
                uri="run:12",
                summary="Dataset run pending verifier",
                status="pending",
            ),
        )
        with pytest.raises(ValueError, match="invalid evidence_type"):
            append_proof(
                conn,
                mission,
                ProofEntry(
                    proof_id="proof-bad",
                    mission_id=mission.mission_id,
                    requirement="verifier acceptance",
                    claim="bad",
                    evidence_type="spreadsheet",
                    uri="x",
                    summary="bad",
                ),
            )
    finally:
        conn.close()

    rendered = render_proof(mission.mission_id)
    assert "Accepted: 1/3 required" in rendered
    assert "mission brief: accepted proof-001" in rendered
    assert "workstream outputs: pending proof-002" in rendered
    assert "verifier acceptance: missing" in rendered


def test_completion_gate_requires_accepted_proof_for_every_requirement():
    from hermes_cli import kanban_db as kb
    from hermes_cli.omega_goal import (
        OmegaGoalArgs,
        ProofEntry,
        append_proof,
        completion_gate,
        create_mission,
        list_proofs,
        mark_completed,
    )

    mission = create_mission(
        OmegaGoalArgs("finish only with proof"),
        session_id="sid-complete",
        now=date(2026, 5, 29),
    )
    conn = kb.connect(board=mission.board)
    try:
        ok, missing = completion_gate(mission, list_proofs(conn, mission))
        assert ok is False
        assert missing == mission.proof_required

        for idx, req in enumerate(mission.proof_required, start=1):
            append_proof(
                conn,
                mission,
                ProofEntry(
                    proof_id=f"proof-{idx:03d}",
                    mission_id=mission.mission_id,
                    requirement=req,
                    claim=f"{req} accepted",
                    evidence_type="test",
                    uri=f"run:{idx}",
                    summary=f"{req} evidence accepted",
                    status="accepted",
                ),
            )
        ok, missing = completion_gate(mission, list_proofs(conn, mission))
        assert ok is True
        assert missing == []
    finally:
        conn.close()

    assert "completed" in mark_completed(mission.mission_id)


def test_completion_gate_refuses_mark_completed_when_proof_missing():
    from hermes_cli.omega_goal import OmegaGoalArgs, OmegaGoalError, create_mission, mark_completed

    mission = create_mission(
        OmegaGoalArgs("missing verifier proof"),
        session_id="sid-missing",
        now=date(2026, 5, 29),
    )

    with pytest.raises(OmegaGoalError, match="missing accepted proof"):
        mark_completed(mission.mission_id)


def test_blockers_render_human_required_by_default():
    from hermes_cli import kanban_db as kb
    from hermes_cli.omega_goal import (
        BlockerEntry,
        OmegaGoalArgs,
        append_blocker,
        create_mission,
        list_blockers,
        render_blockers,
    )

    mission = create_mission(
        OmegaGoalArgs("resolve camera blocker"),
        session_id="sid-block",
        now=date(2026, 5, 29),
    )
    conn = kb.connect(board=mission.board)
    try:
        append_blocker(
            conn,
            mission,
            BlockerEntry(
                blocker_id="blk-human",
                mission_id=mission.mission_id,
                summary="camera mount decision",
                decision_needed="choose desk clamp or wall mount",
                human_required=True,
            ),
        )
        append_blocker(
            conn,
            mission,
            BlockerEntry(
                blocker_id="blk-retry",
                mission_id=mission.mission_id,
                summary="worker retry needed",
                human_required=False,
            ),
        )

        human = list_blockers(conn, mission)
        all_blockers = list_blockers(conn, mission, human_only=False)
        assert [b.blocker_id for b in human] == ["blk-human"]
        assert {b.blocker_id for b in all_blockers} >= {"blk-human", "blk-retry"}
    finally:
        conn.close()

    rendered = render_blockers(mission.mission_id)
    assert "camera mount decision" in rendered
    assert "worker retry needed" not in rendered


def test_stop_blocks_future_mission_work_without_touching_other_boards():
    from hermes_cli import kanban_db as kb
    from hermes_cli.omega_goal import OmegaGoalArgs, create_mission, stop_mission

    mission = create_mission(
        OmegaGoalArgs("stop scoped mission"),
        session_id="sid-stop",
        now=date(2026, 5, 29),
    )
    kb.create_board("unrelated-board")
    unrelated_conn = kb.connect(board="unrelated-board")
    try:
        unrelated = kb.create_task(unrelated_conn, title="unrelated ready task")
    finally:
        unrelated_conn.close()

    output = stop_mission(mission.mission_id)
    assert "stopped" in output

    conn = kb.connect(board=mission.board)
    try:
        tasks = [
            t
            for t in kb.list_tasks(conn, include_archived=False)
            if t.id != mission.root_task_id
        ]
        assert tasks
        assert {t.status for t in tasks} == {"blocked"}
    finally:
        conn.close()

    unrelated_conn = kb.connect(board="unrelated-board")
    try:
        assert kb.get_task(unrelated_conn, unrelated).status == "ready"
    finally:
        unrelated_conn.close()
