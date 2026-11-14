@AGENTS.md

## Riêng cho Claude Code

- Dùng plan mode (Shift+Tab) trước khi sửa từ 3 file trở lên.
- Giao việc tìm hiểu/đọc nhiều file cho subagent trong `.claude/agents/` để giữ context chính gọn.
- Sau mỗi thay đổi Python: `python -m pytest -q && ruff check .`
