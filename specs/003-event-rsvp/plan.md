# Implementation Plan: Sự kiện của trường — Tham gia / Không, phù hợp với ngành

**Branch**: `003-event-rsvp` | **Date**: 2026-11-14 | **Spec**: [spec.md](spec.md)

## Summary

Hồ sơ học tập (trường từ bộ dữ liệu 306 trường có tên viết tắt, bậc Đại học/Thạc sĩ/Tiến sĩ, ngành từ danh mục quốc
gia 964 ngành + chương trình riêng của trường) hiện sau đăng nhập. Thông báo sự kiện thành **lời mời** (cột `rsvp`
trên `tasks`) với hai nút theo UI Kit, thông báo có nút hành động; Tham gia → lịch + nhắc + nút mở link + nút đăng ký
Google Form điền sẵn (app tự dựng link); agent MajorFit đánh giá mức phù hợp theo ngành. Chi tiết: [research.md](research.md).

## Technical Context

**Language/Version**: Python 3.12 (FastAPI), TypeScript / Expo SDK 58 · **Storage**: SQLite (thêm cột users, tasks) +
3 file JSON tĩnh · **Testing**: pytest (Runner giả, MockTransport), node:test · **Constraints**: AI chỉ khi cần (sự
kiện), không gửi dữ liệu hồ sơ lên dịch vụ ngoài, không tự gửi form · **Scale**: dữ liệu tĩnh ~150 KB, tải một lần
(ETag)

## Constitution Check (v1.1.0)

| Nguyên tắc | Đánh giá |
|---|---|
| I. Bảo mật & cách ly | ✅ Endpoint mới `current_user`/`ai_limit`; repo lọc `user_id`; giới hạn độ dài hồ sơ; link sự kiện chỉ http(s); tải form qua allowlist + kiểm IP; link điền sẵn dựng trên máy; nội dung sự kiện qua `render()` + GUARD, agent không tool |
| II. Test | ✅ Test cách ly `/api/profile`, `/rsvp`, `/events` trong `test_api.py`; test agent bằng Runner giả |
| III. AI minh bạch | ✅ Mức phù hợp offline ghi rõ "Bộ luật (offline)"; prompt mới trong `DEFAULTS` |
| Ràng buộc kỹ thuật | ✅ `types.ts`/`api.ts` cập nhật; giờ +07:00 |

**PASS**, không ngoại lệ.

## Project Structure

```text
backend/app/data/{schools,majors,programs}.json   # MỚI (từ research R1–R2)
backend/app/routers/profile.py                     # MỚI: catalog, profile, events, rsvp
backend/app/pipeline/events.py                     # MỚI: EventDetails, MajorFit (LLM + luật), Google Form meta
backend/app/{db,repo,models,agent_config}.py · pipeline/{orchestrator,llm_agents}.py · sync/notify.py
mobile/lib/{catalog,events,prefill}.ts (+ test)    # MỚI: tìm trường/ngành, sắp lời mời, dựng link điền sẵn
mobile/app/profile.tsx                             # MỚI: màn khai báo trường/bậc/ngành
mobile/components/InviteCard.tsx                   # MỚI: thẻ lời mời + 2 nút
mobile/app/(tabs)/tasks.tsx · settings.tsx · _layout.tsx · lib/{api,types,store,notifications}.ts
```

## Phân pha

1. Dữ liệu + hồ sơ (US1): data files, cột users, `/api/catalog`, `/api/profile`, màn khai báo. ~1,5 h
2. Lời mời (US2): cột tasks, EventDetails, rsvp, `/api/events`, InviteCard, Google Form điền sẵn, thông báo có nút. ~2,5 h
3. Phù hợp ngành (US3): MajorFit + luật, sắp xếp, tính lại khi đổi ngành. ~1 h
4. Kiểm tra, soát bảo mật, build iOS, triển khai. ~0,5 h
