from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class AccountUpdate(BaseModel):
    """ฟิลด์ที่ผู้ใช้แก้ได้ที่ PUT /api/account (ส่งเฉพาะฟิลด์ที่ต้องการเปลี่ยนได้)"""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    display_name: str | None = Field(default=None, max_length=60)
    avatar_key: str | None = Field(default=None, max_length=40, pattern=r"^[A-Za-z0-9_-]+$")
    school: str | None = Field(default=None, max_length=120)
    grade_level: str | None = Field(default=None, max_length=40)
    classroom: str | None = Field(default=None, max_length=40)
    interested_faculties: list[str] | None = Field(default=None, max_length=10)
    notify_prefs: dict[str, bool] | None = None


class InviteCreate(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    label: str | None = Field(default=None, max_length=60)
    max_uses: int | None = Field(default=None, ge=1, le=1000)
    expires_in_days: int | None = Field(default=None, ge=1, le=365)


class InviteRedeem(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    code: str = Field(min_length=4, max_length=40, pattern=r"^[A-Za-z0-9_-]+$")
