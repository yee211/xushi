"""Pydantic 请求模型：网页端与小程序端请求体的并集。"""
from pydantic import BaseModel, Field, field_validator


def normalize_email(value: str) -> str:
    """邮箱清洗与格式基本校验。"""
    value = (value or "").strip().lower()
    if "@" not in value or "." not in value.split("@")[-1]:
        raise ValueError("邮箱格式不正确")
    return value


# ---------- 邮箱账号（网页端） ----------

class RegisterIn(BaseModel):
    email: str = Field(max_length=254)
    username: str = Field(min_length=2, max_length=40)
    password: str = Field(min_length=6, max_length=72)

    @field_validator("email")
    @classmethod
    def check_email(cls, value):
        return normalize_email(value)


class EmailLoginIn(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(min_length=6, max_length=72)

    @field_validator("email")
    @classmethod
    def check_email(cls, value):
        return normalize_email(value)


# ---------- 微信登录（小程序端） ----------

class WechatLoginIn(BaseModel):
    code: str = Field(min_length=1, max_length=256)


# ---------- 课表 / 课程 / 调课（两端共用） ----------

class ScheduleUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=80)
    term: str | None = Field(default=None, max_length=80)
    start_date: str | None = None
    end_date: str | None = None

    @field_validator("name")
    @classmethod
    def clean_name(cls, value):
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("课表名称不能为空")
        return value

    @field_validator("term")
    @classmethod
    def clean_term(cls, value):
        return value.strip() if value is not None else None


class CourseIn(BaseModel):
    schedule_id: int = Field(gt=0)
    name: str = Field(min_length=1, max_length=80)
    teacher: str = Field(default="", max_length=40)
    room: str = Field(default="", max_length=40)
    weekday: int = Field(ge=1, le=7)
    start_section: int = Field(ge=1, le=12)
    end_section: int = Field(ge=1, le=12)
    weeks: list[int] = Field(default_factory=list)
    color: str = Field(default="#5B8DEF", pattern=r"^#[0-9A-Fa-f]{6}$")

    @field_validator("name", "teacher", "room")
    @classmethod
    def clean_text(cls, value, info):
        value = str(value or "").strip()
        if info.field_name == "name" and not value:
            raise ValueError("课程名称不能为空")
        return value

    @field_validator("weeks")
    @classmethod
    def valid_weeks(cls, value):
        if any(week < 1 or week > 30 for week in value):
            raise ValueError("周次必须在 1 到 30 之间")
        return sorted(set(value))


class CourseAdjustmentIn(BaseModel):
    week: int = Field(ge=1, le=30)
    weekday: int = Field(ge=1, le=7)
    start_section: int = Field(ge=1, le=12)
    end_section: int = Field(ge=1, le=12)
    room: str = Field(default="", max_length=40)

    @field_validator("room")
    @classmethod
    def clean_room(cls, value):
        return value.strip()


class AdjustmentApplyItem(BaseModel):
    course_id: int
    week: int = Field(ge=1, le=30)
    weekday: int = Field(ge=1, le=7)
    start_section: int = Field(ge=1, le=12)
    end_section: int = Field(ge=1, le=12)
    room: str = Field(default="", max_length=40)


class AdjustmentApplyRequest(BaseModel):
    schedule_id: int
    items: list[AdjustmentApplyItem] = Field(min_length=1, max_length=100)


# ---------- 反馈（两端共用） ----------

class FeedbackIn(BaseModel):
    category: str = Field(default="other", max_length=32)
    description: str = Field(min_length=5, max_length=1000)
    contact: str = Field(default="", max_length=120)
    schedule_id: int | None = None
    client_info: dict = Field(default_factory=dict)


# ---------- Agent 渠道绑定（小程序端） ----------

class AgentMessageIn(BaseModel):
    message: str = Field(min_length=1, max_length=500)


class WeixinLoginPollIn(BaseModel):
    verify_code: str = Field(default="", max_length=20)


class BindingCodeIn(BaseModel):
    provider: str = Field(default="", max_length=32)


class AccountLinkIn(BaseModel):
    """小程序提交的账号互通绑定码。"""
    code: str = Field(min_length=6, max_length=6)
