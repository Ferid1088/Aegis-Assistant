import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from rag.api.deps import AuthenticatedUser, require_permission
from rag.api.schemas.admin import (
    AccessLevelCreate, AccessLevelResponse, DepartmentCreate, DepartmentResponse,
    DocumentTypeCreate, DocumentTypeResponse, RoleCreate, RoleGrantCreate,
    RolePermissionCreate, RoleResponse,
)
from rag.crosscutting.security.audit_events import record_admin_change
from rag.infra.stores.sql.base import get_db
from rag.infra.stores.sql.models import AccessLevel, Department, DocumentType, Role, RoleAccessGrant, RolePermission

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


@router.get("/departments/{department_id}/access-levels", response_model=list[AccessLevelResponse])
def list_access_levels(
    department_id: uuid.UUID,
    current: AuthenticatedUser = Depends(require_permission("admin:departments")),
    db: Session = Depends(get_db),
) -> list[AccessLevelResponse]:
    dept = db.get(Department, department_id)
    if dept is None:
        raise HTTPException(status_code=404, detail="department not found")
    levels = db.execute(select(AccessLevel).where(AccessLevel.department_id == department_id)).scalars().all()
    return [AccessLevelResponse(id=str(lv.id), department_id=str(department_id), label=lv.label, rank=lv.rank) for lv in levels]


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


@router.post("/roles", response_model=RoleResponse, status_code=201)
def create_role(
    body: RoleCreate,
    current: AuthenticatedUser = Depends(require_permission("admin:roles")),
    db: Session = Depends(get_db),
) -> RoleResponse:
    role = Role(name=body.name)
    db.add(role)
    db.commit()
    record_admin_change(str(current.user.id), "role_created", f"role:{role.id}", new_value={"name": role.name})
    return RoleResponse(id=str(role.id), name=role.name)


@router.get("/roles", response_model=list[RoleResponse])
def list_roles(
    current: AuthenticatedUser = Depends(require_permission("admin:roles")),
    db: Session = Depends(get_db),
) -> list[RoleResponse]:
    roles = db.execute(select(Role)).scalars().all()
    return [RoleResponse(id=str(r.id), name=r.name) for r in roles]


@router.delete("/roles/{role_id}", status_code=204)
def delete_role(
    role_id: uuid.UUID,
    current: AuthenticatedUser = Depends(require_permission("admin:roles")),
    db: Session = Depends(get_db),
) -> None:
    role = db.get(Role, role_id)
    if role is None:
        raise HTTPException(status_code=404, detail="role not found")
    db.delete(role)
    db.commit()
    record_admin_change(str(current.user.id), "role_deleted", f"role:{role_id}")


@router.post("/roles/{role_id}/grants", status_code=201)
def grant_access_level(
    role_id: uuid.UUID,
    body: RoleGrantCreate,
    current: AuthenticatedUser = Depends(require_permission("admin:roles")),
    db: Session = Depends(get_db),
) -> dict:
    role = db.get(Role, role_id)
    if role is None:
        raise HTTPException(status_code=404, detail="role not found")
    level_id = uuid.UUID(body.access_level_id)
    level = db.get(AccessLevel, level_id)
    if level is None:
        raise HTTPException(status_code=404, detail="access level not found")
    if db.get(RoleAccessGrant, (role_id, level_id)) is not None:
        raise HTTPException(status_code=409, detail="grant already exists")

    grant = RoleAccessGrant(role_id=role_id, access_level_id=level_id, granted_by=current.user.id)
    db.add(grant)
    db.commit()
    record_admin_change(
        str(current.user.id), "role_grant_added", f"role:{role_id}",
        new_value={"access_level_id": str(level_id)},
    )
    return {"role_id": str(role_id), "access_level_id": str(level_id)}


@router.delete("/roles/{role_id}/grants/{access_level_id}", status_code=204)
def revoke_access_level(
    role_id: uuid.UUID,
    access_level_id: uuid.UUID,
    current: AuthenticatedUser = Depends(require_permission("admin:roles")),
    db: Session = Depends(get_db),
) -> None:
    grant = db.get(RoleAccessGrant, (role_id, access_level_id))
    if grant is None:
        raise HTTPException(status_code=404, detail="grant not found")
    db.delete(grant)
    db.commit()
    record_admin_change(
        str(current.user.id), "role_grant_removed", f"role:{role_id}",
        prev_value={"access_level_id": str(access_level_id)},
    )


@router.post("/roles/{role_id}/permissions", status_code=201)
def grant_permission(
    role_id: uuid.UUID,
    body: RolePermissionCreate,
    current: AuthenticatedUser = Depends(require_permission("admin:roles")),
    db: Session = Depends(get_db),
) -> dict:
    role = db.get(Role, role_id)
    if role is None:
        raise HTTPException(status_code=404, detail="role not found")
    if db.get(RolePermission, (role_id, body.permission)) is not None:
        raise HTTPException(status_code=409, detail="permission already granted")

    db.add(RolePermission(role_id=role_id, permission=body.permission))
    db.commit()
    record_admin_change(
        str(current.user.id), "role_permission_added", f"role:{role_id}",
        new_value={"permission": body.permission},
    )
    return {"role_id": str(role_id), "permission": body.permission}


@router.delete("/roles/{role_id}/permissions/{permission}", status_code=204)
def revoke_permission(
    role_id: uuid.UUID,
    permission: str,
    current: AuthenticatedUser = Depends(require_permission("admin:roles")),
    db: Session = Depends(get_db),
) -> None:
    perm = db.get(RolePermission, (role_id, permission))
    if perm is None:
        raise HTTPException(status_code=404, detail="permission not found")
    db.delete(perm)
    db.commit()
    record_admin_change(
        str(current.user.id), "role_permission_removed", f"role:{role_id}",
        prev_value={"permission": permission},
    )


@router.post("/document-types", response_model=DocumentTypeResponse, status_code=201)
def create_document_type(
    body: DocumentTypeCreate,
    current: AuthenticatedUser = Depends(require_permission("admin:document_types")),
    db: Session = Depends(get_db),
) -> DocumentTypeResponse:
    dt = DocumentType(label=body.label)
    db.add(dt)
    db.commit()
    record_admin_change(str(current.user.id), "document_type_created", f"document_type:{dt.id}", new_value={"label": dt.label})
    return DocumentTypeResponse(id=str(dt.id), label=dt.label)


@router.get("/document-types", response_model=list[DocumentTypeResponse])
def list_document_types(
    current: AuthenticatedUser = Depends(require_permission("admin:document_types")),
    db: Session = Depends(get_db),
) -> list[DocumentTypeResponse]:
    types = db.execute(select(DocumentType)).scalars().all()
    return [DocumentTypeResponse(id=str(t.id), label=t.label) for t in types]


@router.delete("/document-types/{document_type_id}", status_code=204)
def delete_document_type(
    document_type_id: uuid.UUID,
    current: AuthenticatedUser = Depends(require_permission("admin:document_types")),
    db: Session = Depends(get_db),
) -> None:
    dt = db.get(DocumentType, document_type_id)
    if dt is None:
        raise HTTPException(status_code=404, detail="document type not found")
    db.delete(dt)
    db.commit()
    record_admin_change(str(current.user.id), "document_type_deleted", f"document_type:{document_type_id}")
