from pydantic import BaseModel


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    mfa_required: bool
    mfa_pending_token: str | None = None
    access_token: str | None = None
    refresh_token: str | None = None


class MfaVerifyRequest(BaseModel):
    mfa_pending_token: str
    totp_code: str


class RefreshRequest(BaseModel):
    refresh_token: str


class RefreshResponse(BaseModel):
    access_token: str
    refresh_token: str


class MfaEnrollResponse(BaseModel):
    secret: str
    provisioning_uri: str


class MeResponse(BaseModel):
    id: str
    username: str
    roles: list[str]
    effective_levels: list[str]


class SessionUser(BaseModel):
    id: str
    username: str
    name: str
    role: str
    department: str | None
    status: str


class SessionNav(BaseModel):
    chat: bool
    search: bool
    documents: bool
    admin: bool
    evaluation: bool
    audit: bool
    system: bool


class SessionResponse(BaseModel):
    user: SessionUser
    edition: str
    nav: SessionNav
