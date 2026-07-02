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
