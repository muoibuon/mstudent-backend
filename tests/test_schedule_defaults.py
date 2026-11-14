"""User-approved class daypart defaults; no provider, key or server required."""

from datetime import datetime

import pytest

from app.models import Category, Message, TaskOut
from app.pipeline import rules

RECEIVED = "2026-11-14T16:43:00+07:00"


def class_task(*, due_at=None, action="Đi học đúng giờ", category=Category.class_change):
    return TaskOut(
        title="Học OOP",
        course="OOP",
        category=category,
        due_at=due_at,
        location=None,
        action=action,
    )


@pytest.mark.parametrize("daypart,hour", [("sáng", 8), ("chiều", 13), ("tối", 19)])
def test_approved_daypart_defaults_are_used_by_offline_time_parser(daypart, hour):
    text = f"thứ 2 tuần sau {daypart} tôi học oop"
    assert rules.default_daypart(text) == (daypart, hour)
    assert rules.find_time(text) == (hour, 0)


@pytest.mark.parametrize("daypart,hour", [("sáng", "08"), ("chiều", "13"), ("tối", "19")])
def test_personal_attendance_is_relevant_class_and_has_next_monday_default(daypart, hour):
    msg = Message(body=f"thứ 2 tuần sau {daypart} tôi học oop", received_at=RECEIVED)
    triage = rules.triage(msg)
    assert triage.relevant and triage.category == Category.class_change
    extracted = rules.extract(msg, triage.category)
    assert len(extracted.tasks) == 1
    assert extracted.tasks[0].due_at == f"2026-11-16T{hour}:00:00+07:00"


def test_class_time_postprocessing_corrects_main_model_date_and_marks_default():
    msg = Message(body="thứ 2 tuần sau sáng tôi học oop", received_at=RECEIVED)
    original = class_task(due_at="2026-11-23T09:00:00+07:00")
    tasks = rules.apply_class_time_defaults(msg, [original])
    assert len(tasks) == 1 and tasks[0].due_at == "2026-11-16T08:00:00+07:00"
    assert "Giờ mặc định" in (tasks[0].action or "")
    assert "Đi học đúng giờ" in tasks[0].action


@pytest.mark.parametrize("action", [None, "Đi học đúng giờ"])
def test_default_note_is_safe_and_not_duplicated(action):
    msg = Message(body="thứ 2 tuần sau chiều tôi học oop", received_at=RECEIVED)
    once = rules.apply_class_time_defaults(msg, [class_task(action=action)])
    twice = rules.apply_class_time_defaults(msg, once)
    assert once == twice
    assert (twice[0].action or "").count("Giờ mặc định") == 1


def test_explicit_clock_beats_daypart_in_offline_and_postprocessing():
    msg = Message(body="thứ 2 tuần sau sáng 9h30 tôi học oop", received_at=RECEIVED)
    assert rules.find_time(msg.body) == (9, 30)
    existing = [class_task(due_at="2026-11-16T09:30:00+07:00")]
    assert rules.apply_class_time_defaults(msg, existing) == existing
    assert "Giờ mặc định" not in (existing[0].action or "")
    assert rules.extract(msg, Category.class_change).tasks[0].due_at == "2026-11-16T09:30:00+07:00"


@pytest.mark.parametrize(
    "text",
    [
        "thứ 2 tuần sau tôi học tối ưu thuật toán",
        "thứ 2 tuần sau tôi học thiết kế sáng tạo",
        "thứ 2 tuần sau tôi học xử lý ánh sáng",
    ],
)
def test_subject_words_are_not_dayparts(text):
    assert rules.default_daypart(text) is None
    assert rules.find_time(text) is None
    existing = [class_task(due_at=None)]
    assert rules.apply_class_time_defaults(Message(body=text, received_at=RECEIVED), existing) == existing


@pytest.mark.parametrize(
    "received,body,expected",
    [
        ("2026-11-29T22:00:00+07:00", "thứ 2 tuần sau sáng tôi học oop", "2026-11-30T08:00:00+07:00"),
        ("2026-12-31T10:00:00+07:00", "thứ 2 tuần sau chiều tôi học oop", "2027-01-04T13:00:00+07:00"),
        ("2027-01-31T23:00:00+07:00", "thứ 2 tuần sau tối tôi học oop", "2027-02-01T19:00:00+07:00"),
        ("2028-02-28T16:00:00+07:00", "ngày mai sáng tôi học oop", "2028-02-29T08:00:00+07:00"),
    ],
)
def test_relative_date_uses_received_time_across_month_year_and_leap_boundaries(received, body, expected):
    msg = Message(body=body, received_at=received)
    result = rules.apply_class_time_defaults(msg, [class_task()])
    assert result[0].due_at == expected
    assert datetime.fromisoformat(result[0].due_at).utcoffset().total_seconds() == 7 * 3600


@pytest.mark.parametrize(
    "body",
    [
        "thứ 2 tuần sau sáng tôi học oop, thứ 3 tôi học CSDL",
        "sáng 16/11 tôi học OOP, 17/11 học CSDL",
        "thứ 2 tuần sau sáng và chiều tôi học oop",
        "tôi học oop vào buổi sáng",  # thiếu ngày, không tự gán ngày nhận tin
    ],
)
def test_ambiguous_or_missing_date_daypart_does_not_change_main_task(body):
    existing = [class_task(due_at="2026-11-20T10:00:00+07:00")]
    assert rules.apply_class_time_defaults(Message(body=body, received_at=RECEIVED), existing) == existing


def test_multiple_tasks_skip_single_class_default_and_empty_output_is_not_fabricated():
    msg = Message(body="thứ 2 tuần sau sáng tôi học oop", received_at=RECEIVED)
    existing = [class_task(), class_task(due_at="2026-11-18T15:00:00+07:00")]
    assert rules.apply_class_time_defaults(msg, existing) == existing
    assert rules.apply_class_time_defaults(msg, []) == []


@pytest.mark.parametrize(
    "category", [Category.deadline, Category.exam, Category.admin, Category.event, Category.other]
)
def test_default_postprocessor_only_changes_class_tasks(category):
    msg = Message(body="thứ 2 tuần sau sáng tôi học oop", received_at=RECEIVED)
    existing = [class_task(category=category, due_at="2026-11-20T23:59:00+07:00")]
    assert rules.apply_class_time_defaults(msg, existing) == existing


@pytest.mark.parametrize(
    "text,category",
    [
        ("thứ 2 tuần sau sáng tôi học oop rồi nộp bài tập", Category.deadline),
        ("thứ 2 tuần sau sáng tôi thi oop", Category.exam),
        ("thứ 2 tuần sau sáng tôi đóng học phí", Category.admin),
        ("thứ 2 tuần sau sáng tôi học oop", Category.class_change),
    ],
)
def test_attendance_pattern_keeps_existing_higher_priority_categories(text, category):
    assert rules.classify(text) == category


def test_explicit_date_uses_daypart_without_changing_the_date():
    msg = Message(body="sáng ngày 02/12/2026 tôi học oop", received_at=RECEIVED)
    assert rules.apply_class_time_defaults(msg, [class_task()])[0].due_at == "2026-12-02T08:00:00+07:00"
