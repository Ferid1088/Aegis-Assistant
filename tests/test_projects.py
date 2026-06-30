from rag.domain.projects import Phase, Project, resolve_inherited_metadata, validate_phase_assignment


def test_project_only_is_valid():
    ok, reason = validate_phase_assignment(project_id="P1", phase=None)
    assert ok
    assert "project-only" in reason


def test_no_project_no_phase_is_valid():
    ok, _ = validate_phase_assignment(project_id=None, phase=None)
    assert ok


def test_project_plus_matching_phase_is_valid():
    phase = Phase(phase_id="F1", project_id="P1", name="Phase 1")
    ok, reason = validate_phase_assignment(project_id="P1", phase=phase)
    assert ok
    assert "valid" in reason


def test_phase_without_project_is_rejected():
    phase = Phase(phase_id="F1", project_id="P1", name="Phase 1")
    ok, reason = validate_phase_assignment(project_id=None, phase=phase)
    assert not ok
    assert "without project" in reason


def test_phase_belonging_to_different_project_is_rejected():
    phase = Phase(phase_id="F1", project_id="P1", name="Phase 1")
    ok, reason = validate_phase_assignment(project_id="P2", phase=phase)
    assert not ok
    assert "does not belong" in reason


def test_subphase_under_phase_under_project():
    parent = Phase(phase_id="F1", project_id="P1", name="Phase 1")
    sub = Phase(phase_id="F2", project_id="P1", parent_phase_id="F1", name="Subphase 1.1")
    ok, _ = validate_phase_assignment(project_id="P1", phase=sub)
    assert ok
    assert sub.parent_phase_id == "F1"


def test_inheritance_precedence_project_then_phase_then_explicit():
    project = Project(project_id="P1", name="Project 1", default_metadata={"department": "hr", "access_level": ["L1"]})
    phase = Phase(phase_id="F1", project_id="P1", name="Phase 1", default_metadata={"access_level": ["L2"]})
    resolved = resolve_inherited_metadata(
        explicit={"document_type": "manual"}, phase=phase, project=project,
    )
    assert resolved["department"] == "hr"       # from project, untouched by phase
    assert resolved["access_level"] == ["L2"]    # phase overrides project
    assert resolved["document_type"] == "manual"  # explicit overrides everything


def test_explicit_none_does_not_override_inherited_value():
    project = Project(project_id="P1", name="Project 1", default_metadata={"department": "hr"})
    resolved = resolve_inherited_metadata(explicit={"department": None}, phase=None, project=project)
    assert resolved["department"] == "hr"


def test_no_project_no_phase_uses_only_explicit():
    resolved = resolve_inherited_metadata(explicit={"department": "legal"}, phase=None, project=None)
    assert resolved == {"department": "legal"}
