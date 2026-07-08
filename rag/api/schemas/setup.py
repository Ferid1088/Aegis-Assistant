from pydantic import BaseModel


class SetupStatusResponse(BaseModel):
    needs_setup: bool


class SetupAdminCreate(BaseModel):
    username: str
    password: str
