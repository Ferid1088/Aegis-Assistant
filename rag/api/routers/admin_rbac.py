import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from rag.api.deps import AuthenticatedUser, require_permission
from rag.api.schemas.admin import (
    AccessLevelCreate, AccessLevelResponse, DepartmentCreate, DepartmentResponse,
)
from rag.crosscutting.security.audit_events import record_admin_change
from rag.storage.sql.base import get_db
from rag.storage.sql.models import AccessLevel, Department

router = APIRouter()


@router.post("/departments", response_model=DepartmentResponse, status_code=201)
def create_department(
    body: DepartmentCreate,
    current: AuthenticatedUser = Depends(require_permission("admin:departments")),
    db: Session = Depends(get_db),
) -> DepartmentResponse:
    dept = Department(name=body.name)
    db.add(dept)
    db.commit()
    record_admin_change(str(current.user.id), "department_created", f"department:{dept.id}", new_value={"name": dept.name})
    return DepartmentResponse(id=str(dept.id), name=dept.name)


@router.get("/departments", response_model=list[DepartmentResponse])
def list_departments(
    current: AuthenticatedUser = Depends(require_permission("admin:departments")),
    db: Session = Depends(get_db),
) -> list[DepartmentResponse]:
    depts = db.execute(select(Department)).scalars().all()
    return [DepartmentResponse(id=str(d.id), name=d.name) for d in depts]


@router.delete("/departments/{department_id}", status_code=204)
def delete_department(
    department_id: uuid.UUID,
    current: AuthenticatedUser = Depends(require_permission("admin:departments")),
    db: Session = Depends(get_db),
) -> None:
    dept = db.get(Department, department_id)
    if dept is None:
        raise HTTPException(status_code=404, detail="department not found")
    db.delete(dept)
    db.commit()
    record_admin_change(str(current.user.id), "department_deleted", f"department:{department_id}")


@router.post("/departments/{department_id}/access-levels", response_model=AccessLevelResponse, status_code=201)
def create_access_level(
    department_id: uuid.UUID,
    body: AccessLevelCreate,
    current: AuthenticatedUser = Depends(require_permission("admin:departments")),
    db: Session = Depends(get_db),
) -> AccessLevelResponse:
    dept = db.get(Department, department_id)
    if dept is None:
        raise HTTPException(status_code=404, detail="department not found")
    level = AccessLevel(department_id=department_id, label=body.label, rank=body.rank)
    db.add(level)
    db.commit()
    record_admin_change(
        str(current.user.id), "access_level_created", f"access_level:{level.id}",
        new_value={"department_id": str(department_id), "label": level.label, "rank": level.rank},
    )
    return AccessLevelResponse(id=str(level.id), department_id=str(department_id), label=level.label, rank=level.rank)


@router.delete("/access-levels/{access_level_id}", status_code=204)
def delete_access_level(
    access_level_id: uuid.UUID,
    current: AuthenticatedUser = Depends(require_permission("admin:departments")),
    db: Session = Depends(get_db),
) -> None:
    level = db.get(AccessLevel, access_level_id)
    if level is None:
        raise HTTPException(status_code=404, detail="access level not found")
    db.delete(level)
    db.commit()
    record_admin_change(str(current.user.id), "access_level_deleted", f"access_level:{access_level_id}")
