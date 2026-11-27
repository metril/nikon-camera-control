"""Schemas for the sign-in endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AuthStatusOut(BaseModel):
    auth_required: bool = Field(description="True when a password or API key is set")
    password_set: bool = Field(description="True when an app password exists (or is locked)")
    api_key_set: bool
    authenticated: bool = Field(description="Whether this request's credentials are accepted")
    session_kind: Literal["browser", "kiosk"] | None = Field(
        description="Kind of the session cookie in use, if any"
    )


class LoginIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    password: str | None = Field(default=None, max_length=1024, description="The app password")
    api_key: str | None = Field(
        default=None,
        max_length=1024,
        description="The API key; accepted only while no password is set",
    )

    @model_validator(mode="after")
    def _one(self) -> Self:
        if (self.password is None) == (self.api_key is None):
            raise ValueError("send exactly one of password or api_key")
        return self


class PasswordSetIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current: str | None = Field(
        default=None,
        max_length=1024,
        description="The current password; required only when a password is already set",
    )
    new: str = Field(min_length=8, max_length=256, description="The new password")


class PasswordDeleteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current: str = Field(max_length=1024, description="The current password")


class KioskPairIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str = Field(max_length=1024, description="The kiosk device token")


class AuthSessionOut(BaseModel):
    id: str = Field(description="Public handle; not a credential")
    kind: Literal["browser", "kiosk"]
    created: datetime
    last_seen: datetime
    user_agent: str | None
    current: bool = Field(description="True for the session making this request")


class AuthSessionListOut(BaseModel):
    sessions: list[AuthSessionOut]


class RevokedOut(BaseModel):
    revoked: int = Field(ge=0, description="Number of sessions revoked")
