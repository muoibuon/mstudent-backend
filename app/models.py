"""Kiểu dữ liệu dùng chung cho API, pipeline và LLM."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class Source(str, Enum):
    email = "email"
    lms = "lms"
    zalo = "zalo"
    manual = "manual"


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

    id: str | None = None
    source: Source = Source.manual
    sender: str = ""
    subject: str = ""
    body: str
    received_at: str | None = Field(None, description="ISO 8601; để trống = bây giờ")


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


class IngestResult(BaseModel):
    message_id: str
    relevant: bool
    category: Category
    reason: str
    created: list[Task] = []
    updated: list[Task] = []
    mode: str = Field(description="'llm' hoặc 'offline'")
    trace: list[dict] = []


class ChatTurn(BaseModel):
    role: str = Field(description="'user' hoặc 'assistant'")
    content: str


class ChatRequest(BaseModel):
    message: str
    history: list[ChatTurn] = []


class ToolCall(BaseModel):
    tool: str
    args: dict = {}
    result: str = ""


class ChatResponse(BaseModel):
    reply: str
    mode: str
    tool_calls: list[ToolCall] = []
