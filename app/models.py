"""Kiểu dữ liệu dùng chung cho API, pipeline và LLM. Mọi đầu vào từ client đều có giới hạn độ dài."""

from __future__ import annotations

import re
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class Source(str, Enum):
    email = "email"
    lms = "lms"
    zalo = "zalo"
    manual = "manual"
    classroom = "classroom"
    sheet = "sheet"


class Category(str, Enum):
    deadline = "deadline"  # nộp bài, hạn chót
    exam = "exam"  # thi, kiểm tra
    class_change = "class_change"  # nghỉ học, học bù, đổi phòng
    event = "event"  # hội thảo, cuộc thi, sự kiện
    admin = "admin"  # học phí, đăng ký học phần, khảo sát
    other = "other"


class Priority(str, Enum):
    high = "high"
    medium = "medium"
    low = "low"


class Message(BaseModel):
    """Một thông báo thô từ email / LMS / Zalo."""

    id: str | None = Field(None, max_length=200)
    source: Source = Source.manual
    sender: str = Field("", max_length=300)
    subject: str = Field("", max_length=500)
    body: str = Field(min_length=1, max_length=8000)
    received_at: str | None = Field(None, max_length=40, description="ISO 8601; để trống = bây giờ")


# ---- Schema cho LLM: mọi trường đều bắt buộc (strict JSON schema) ----


class TriageOut(BaseModel):
    relevant: bool = Field(description="Thông báo có cần sinh viên hành động/ghi nhớ không")
    category: Category
    reason: str = Field(description="Một câu ngắn giải thích")


class TaskOut(BaseModel):
    title: str = Field(description="Việc cần làm, ngắn gọn, tiếng Việt, <= 80 ký tự")
    course: str | None = Field(description="Mã hoặc tên môn, null nếu không có")
    category: Category
    due_at: str | None = Field(description="Thời hạn/thời điểm ISO 8601 có múi giờ +07:00, null nếu không có")
    location: str | None = Field(description="Phòng/địa điểm/link, null nếu không có")
    action: str | None = Field(description="Hành động cụ thể sinh viên cần làm")


class ExtractionOut(BaseModel):
    tasks: list[TaskOut]


# ---- Task đã lưu ----


class Task(BaseModel):
    id: int
    title: str
    course: str | None = None
    category: Category = Category.other
    due_at: str | None = None
    location: str | None = None
    action: str | None = None
    priority: Priority = Priority.low
    source: Source = Source.manual
    message_id: str
    status: str = "open"
    reminders: list[str] = []
    updated_from: list[str] = []
    sources: list[str] = []
    note: str | None = None


class TaskPatch(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=200)
    due_at: str | None = Field(None, max_length=40)
    status: str | None = Field(None, pattern="^(open|done)$")


class IngestResult(BaseModel):
    message_id: str
    relevant: bool
    category: Category
    reason: str
    created: list[Task] = []
    updated: list[Task] = []
    mode: str = Field(description="'llm' hoặc 'offline'")
    trace: list[dict] = []
    duplicate: bool = Field(False, description="Tin này đã được xử lý trước đó, không chạy lại agent")


class ChatTurn(BaseModel):
    role: str = Field(pattern="^(user|assistant)$")
    content: str = Field(max_length=6000)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    history: list[ChatTurn] = Field(default_factory=list, max_length=30)


class ToolCall(BaseModel):
    tool: str
    args: dict = {}
    result: str = ""


class ChatResponse(BaseModel):
    reply: str
    mode: str
    tool_calls: list[ToolCall] = []


class ZaloPaste(BaseModel):
    text: str = Field(min_length=1, max_length=20000)
    group: str = Field("Nhóm lớp", max_length=100)


class IcsUrl(BaseModel):
    url: str = Field(max_length=2000)


# ---- Tài khoản ----

EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,255}\.[^@\s]{2,}$")


class Credentials(BaseModel):
    email: str = Field(max_length=320)
    password: str = Field(min_length=1, max_length=128)
    device: str = Field("", max_length=100)

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        v = v.strip().lower()
        if not EMAIL_RE.match(v):
            raise ValueError("Email không hợp lệ")
        return v


class RegisterRequest(Credentials):
    name: str = Field("", max_length=100)


class GoogleLoginRequest(BaseModel):
    id_token: str = Field(min_length=20, max_length=5000)
    server_auth_code: str | None = Field(None, max_length=2000)
    device: str = Field("", max_length=100)


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=20, max_length=200)


class ChangePasswordRequest(BaseModel):
    old_password: str = Field("", max_length=128)
    new_password: str = Field(min_length=1, max_length=128)


class DeleteAccountRequest(BaseModel):
    confirm_email: str = Field(max_length=320)


class UserOut(BaseModel):
    id: int
    email: str
    name: str
    is_admin: bool
    has_password: bool
    google_linked: bool
    gmail_connected: bool


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserOut


class GoogleConnectRequest(BaseModel):
    server_auth_code: str = Field(min_length=4, max_length=2000)


class GmailSyncRequest(BaseModel):
    days: int = Field(7, ge=1, le=30)
    max_messages: int = Field(15, ge=1, le=30)


# ---------------- Đồng bộ tự động (002) ----------------


class ColumnRole(BaseModel):
    index: int = Field(ge=0, le=200)
    role: Literal["course", "title", "due", "time", "note", "ignore"]


class SheetMapping(BaseModel):
    columns: list[ColumnRole]


class SourceCreate(BaseModel):
    kind: Literal["ics", "sheet"]
    url: str = Field(min_length=8, max_length=2000)
    label: str = Field("", max_length=100)


class SourcePatch(BaseModel):
    enabled: bool


class SourceOut(BaseModel):
    id: int
    kind: str
    label: str
    enabled: bool
    last_run_at: str | None = None
    last_ok_at: str | None = None
    last_error: str | None = None
    created_at: str
    last: dict | None = None  # thống kê lượt gần nhất: created / updated / skipped / mode


class PushRegister(BaseModel):
    token: str = Field(max_length=200, pattern=r"^Expo(nent)?PushToken\[[A-Za-z0-9_\-]{1,180}\]$")
    platform: Literal["android", "ios"]
    notify: bool = True
