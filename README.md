# MStudent — backend

Máy chủ của MStudent, AI inbox cho sinh viên: đọc thông báo từ Gmail, Google Classroom, bảng lớp, LMS và nhóm Zalo,
lọc tin nhiễu rồi biến thành **việc có hạn, ưu tiên, nhắc việc và lời mời sự kiện**.

- **Repo này:** FastAPI · SQLite · agent AI (lọc: Gemini Decision, trả lời: OpenAI) · web console · triển khai VPS.
- **App điện thoại (Expo):** https://github.com/muoibuon/mstudent-app

## Chạy trong 3 phút

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # điền OPENAI_API_KEY (và GEMINI_API_KEY nếu có); không có key: MSTUDENT_OFFLINE=1
python run_local.py             # in ra địa chỉ LAN, vd. http://192.168.1.5:8000 — nhập vào app
```

Web console (trace từng agent, sửa prompt, chạy eval): http://localhost:8000

## Trước khi push

```bash
python -m pytest -q && ruff check . && ruff format .
MSTUDENT_OFFLINE=1 python -m eval.run_eval      # baseline bộ luật
```

## Quy trình làm việc trong nhóm

1. Hai nhánh chính: **`master`** (bản ổn định, đang chạy trên máy chủ) và **`dev`** (bản đang phát triển).
   Tạo nhánh việc từ `dev`: `git checkout dev && git pull && git checkout -b <việc-ngắn-gọn>` (vd. `fix-gmail-sync`),
   mở PR vào `dev`. Không push thẳng vào `master`; `dev` → `master` bằng PR khi đã thử xong.
2. Mỗi PR một việc; test và lint phải xanh; mô tả ngắn: làm gì, test ra sao, chưa kiểm tra được gì.
3. **Đổi API** (`app/models.py`, `app/routers/`): ghi rõ trong PR và mở PR kèm ở repo app (`lib/types.ts`, `lib/api.ts`).
4. Không commit `.env`, `.secret_key`, `*.db`, khoá API. Quy tắc đầy đủ: [`AGENTS.md`](AGENTS.md).

## Triển khai (VPS Ubuntu)

```bash
rsync -az --delete --exclude .git --exclude .venv --exclude __pycache__ --exclude '*.db*' --exclude .env \
  --exclude .secret_key ./ <user>@<máy-chủ>:~/mstudent/backend/
ssh <user>@<máy-chủ> 'cd ~/mstudent && sudo bash backend/deploy/install.sh'
```

Bật AI lọc Gemini: trên máy chủ chạy `sudo bash ~/mstudent/backend/deploy/set_gemini_key.sh`.

## Tài liệu

| File | Nội dung |
|---|---|
| [`AGENTS.md`](AGENTS.md) | Cấu trúc mã, quy tắc bắt buộc (bảo mật, AI), vai trò cho coding agent |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Sơ đồ, agent, schema, API |
| [`docs/SECURITY.md`](docs/SECURITY.md) | Đã làm gì (kèm tên test) và chưa làm gì |
| [`docs/DEMO_RUNBOOK.md`](docs/DEMO_RUNBOOK.md) | Kịch bản demo, checklist trước giờ, xử lý sự cố |
| [`docs/GOOGLE_CLOUD_SETUP.md`](docs/GOOGLE_CLOUD_SETUP.md) | Từng bước trên Google Cloud Console |
| [`docs/PITCH.md`](docs/PITCH.md) | Bằng chứng người dùng, thị trường |
| [`specs/`](specs/) | Spec Kit: spec, plan, tasks của từng tính năng (cả backend lẫn app) |

Lịch sử trước khi tách repo: https://github.com/muoibuon/mst-codex-hackathon
