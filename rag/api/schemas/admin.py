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
