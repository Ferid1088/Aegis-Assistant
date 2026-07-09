"""Projects & Phases — hierarchical, admin-defined (02.1 §5)."""

from dataclasses import dataclass, field


@dataclass
class Project:
    project_id: str
    name: str
    default_metadata: dict = field(default_factory=dict)


@dataclass
class Phase:
    phase_id: str
    project_id: str
    name: str
    parent_phase_id: str | None = None
    default_metadata: dict = field(default_factory=dict)


def validate_phase_assignment(project_id: str | None, phase: Phase | None) -> tuple[bool, str]:
    """Valid cases: project-only, or project + phase where the phase belongs to that
    project. A phase without its project is rejected (02.1 §5 ⭐)."""
    if phase is None:
        return True, "project-only, valid" if project_id else "no project, no phase, valid"
    if project_id is None:
        return False, "phase without project is invalid"
    if phase.project_id != project_id:
        return False, f"phase {phase.phase_id} does not belong to project {project_id}"
    return True, "project + phase, valid"


def resolve_inherited_metadata(
    explicit: dict[str, object | None],
    phase: Phase | None,
    project: Project | None,
) -> dict[str, object | None]:
    """Precedence (later wins): project defaults → phase defaults → explicit override (02.1 §4.2)."""
    resolved: dict[str, object | None] = {}
    if project is not None:
        resolved.update(project.default_metadata)
    if phase is not None:
        resolved.update(phase.default_metadata)
    for key, value in explicit.items():
        if value is not None:
            resolved[key] = value
    return resolved
