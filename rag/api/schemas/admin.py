from pydantic import BaseModel


class DepartmentCreate(BaseModel):
    name: str


class DepartmentResponse(BaseModel):
    id: str
    name: str


class AccessLevelCreate(BaseModel):
    label: str
    rank: int


class AccessLevelResponse(BaseModel):
    id: str
    department_id: str
    label: str
    rank: int


class RoleCreate(BaseModel):
    name: str


class RoleResponse(BaseModel):
    id: str
    name: str


class RoleGrantCreate(BaseModel):
    access_level_id: str


class RolePermissionCreate(BaseModel):
    permission: str


class DocumentTypeCreate(BaseModel):
    label: str


class DocumentTypeResponse(BaseModel):
    id: str
    label: str


class UserCreate(BaseModel):
    username: str
    email: str | None = None
    password: str | None = None
    department_id: str | None = None


class UserResponse(BaseModel):
    id: str
    username: str
    email: str | None
    department_id: str | None
    is_active: bool
    mfa_enabled: bool


class UserUpdate(BaseModel):
    email: str | None = None
    department_id: str | None = None
    is_active: bool | None = None


class UserRoleAssign(BaseModel):
    role_id: str


class UserLockRequest(BaseModel):
    reason: str


class SessionResponse(BaseModel):
    id: str
    issued_at: str
    expires_at: str
    ip: str | None
    user_agent: str | None


class AuditEntryResponse(BaseModel):
    actor_user: str
    action: str
    resource: str
    ts: str
    request_id: str
    prev_value: dict | None
    new_value: dict | None


class AuditVerifyResponse(BaseModel):
    valid: bool
    count: int
    error: str
