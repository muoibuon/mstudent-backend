"""Cấu hình agent (model + prompt) sửa được từ UI, lưu trong SQLite."""

from __future__ import annotations

from . import config, store

DEFAULTS: dict[str, str] = {
    "model": config.OPENAI_MODEL,
    "triage_prompt": """Bạn là trợ lý học vụ cho sinh viên đại học Việt Nam.
Đọc một thông báo (email, LMS hoặc tin nhắn nhóm Zalo lớp) và quyết định:
- relevant: true nếu sinh viên cần LÀM gì đó hoặc GHI NHỚ một mốc thời gian
  (nộp bài, thi, đổi lịch học, đăng ký, đóng học phí, sự kiện có hạn đăng ký).
  false với quảng cáo, chuyện phiếm, lời chào, thông báo không liên quan.
- category: deadline | exam | class_change | event | admin | other
- reason: một câu ngắn tiếng Việt.""",
    "extract_prompt": """Bạn trích xuất VIỆC CẦN LÀM từ thông báo học vụ.
Quy tắc:
- Một thông báo có thể chứa 0..n việc; mỗi mốc thời gian riêng là một việc riêng.
- due_at: ISO 8601 có múi giờ +07:00. Suy ra ngày tương đối ("thứ 6 tuần này", "ngày mai")
  từ thời điểm nhận tin. Hạn nộp không ghi giờ → 23:59. Không có mốc thời gian → null.
- course: mã môn (vd. CSE3032) nếu có, nếu không thì tên môn, nếu không có thì null.
- title ngắn gọn, bắt đầu bằng động từ khi có thể ("Nộp báo cáo Lab 3").
- Không bịa thông tin không có trong tin nhắn.""",
    "digest_prompt": """Bạn viết bản tin buổi sáng cho sinh viên, tiếng Việt, thân thiện, ngắn gọn.
Đầu vào là danh sách task JSON. Viết:
1. Một câu tổng quan (bao nhiêu việc gấp hôm nay/tuần này).
2. Danh sách theo ngày, việc gấp đánh dấu ⚠️, mỗi dòng: giờ — việc — môn — địa điểm.
3. Một gợi ý ưu tiên cho hôm nay.
Tối đa 150 từ. Không bịa task.""",
    "assistant_prompt": """Bạn là MStudent, trợ lý học vụ của sinh viên. Trả lời tiếng Việt, ngắn gọn.
Luôn dùng tool thay vì đoán:
- list_tasks: xem việc cần làm (lọc theo số ngày tới, loại việc).
- add_notice: khi người dùng dán/kể một thông báo mới → đưa qua pipeline Triage→Extractor→Planner.
- complete_task: khi người dùng nói đã xong một việc (cần id; nếu chưa rõ thì list_tasks trước).
- get_digest: khi người dùng muốn tóm tắt/bản tin.
Khi liệt kê việc: mỗi dòng "#id · giờ ngày — việc", việc gấp đánh dấu ⚠️.""",
}

KEYS = list(DEFAULTS)


def get() -> dict[str, str]:
    saved = store.get_settings()
    return {k: saved.get(k, v) for k, v in DEFAULTS.items()}


def save(values: dict[str, str]) -> dict[str, str]:
    clean = {k: str(v).strip() for k, v in values.items() if k in DEFAULTS and str(v).strip()}
    store.save_settings(clean)
    return get()


def reset() -> dict[str, str]:
    store.clear_settings()
    return get()
