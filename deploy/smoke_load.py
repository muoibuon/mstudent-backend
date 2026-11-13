"""Kiểm tra tải nhanh (SC-003): N yêu cầu đồng thời không gọi AI phải xong dưới 1 giây.

    python deploy/smoke_load.py https://mstudent.<máy>.ts.net
    python deploy/smoke_load.py http://127.0.0.1:8000 --users 5 --concurrency 30 --rounds 3

Tạo vài tài khoản thử (`load-…@loadtest.invalid`), bắn `--concurrency` yêu cầu `GET /api/tasks` cùng lúc (chia đều cho
các tài khoản), lặp `--rounds` lượt, in p50/p95/max và số lỗi, rồi XOÁ các tài khoản thử. Không gọi AI nên không tốn
tiền OpenAI. Đăng ký bị giới hạn 10 lần/giờ mỗi IP, nên mặc định chỉ tạo 3 tài khoản.
"""

from __future__ import annotations

import argparse
import asyncio
import secrets
import statistics
import sys
import time

import httpx

TARGET_P95_S = 1.0


async def register(client: httpx.AsyncClient, base: str) -> tuple[str, str]:
    email = f"load-{secrets.token_hex(4)}@loadtest.invalid"
    r = await client.post(
        f"{base}/api/auth/register",
        json={
            "email": email,
            "password": "Load-" + secrets.token_urlsafe(18),
            "name": "load test",
            "device": "smoke",
        },
    )
    r.raise_for_status()
    return email, r.json()["access_token"]


async def timed_get(client: httpx.AsyncClient, url: str, token: str) -> tuple[float, int | str]:
    t0 = time.perf_counter()
    try:
        r = await client.get(url, headers={"Authorization": f"Bearer {token}"})
        return time.perf_counter() - t0, r.status_code
    except httpx.HTTPError as e:
        return time.perf_counter() - t0, type(e).__name__


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("base", help="Địa chỉ backend, ví dụ https://mstudent.example.ts.net")
    ap.add_argument("--users", type=int, default=3, help="Số tài khoản thử (tối đa 10 vì giới hạn đăng ký)")
    ap.add_argument("--concurrency", type=int, default=30)
    ap.add_argument("--rounds", type=int, default=3)
    a = ap.parse_args()
    base = a.base.rstrip("/")
    users: list[tuple[str, str]] = []
    limits = httpx.Limits(max_connections=a.concurrency, max_keepalive_connections=a.concurrency)
    async with httpx.AsyncClient(timeout=15, limits=limits) as client:
        try:
            for _ in range(max(1, min(a.users, 10))):
                users.append(await register(client, base))
            # Một lượt làm nóng để mở sẵn kết nối, không tính vào kết quả.
            await asyncio.gather(
                *(
                    timed_get(client, f"{base}/api/tasks", users[i % len(users)][1])
                    for i in range(a.concurrency)
                )
            )
            results: list[tuple[float, int | str]] = []
            for _ in range(a.rounds):
                results += await asyncio.gather(
                    *(
                        timed_get(client, f"{base}/api/tasks", users[i % len(users)][1])
                        for i in range(a.concurrency)
                    )
                )
        finally:
            for email, token in users:
                await client.request(
                    "DELETE",
                    f"{base}/api/auth/me",
                    json={"confirm_email": email},
                    headers={"Authorization": f"Bearer {token}"},
                )
    times = sorted(t for t, _ in results)
    errors = [s for _, s in results if s != 200]
    p95 = times[max(0, int(round(0.95 * len(times))) - 1)]
    print(f"{len(results)} yêu cầu ({a.concurrency} đồng thời × {a.rounds} lượt, {len(users)} tài khoản thử)")
    print(
        f"p50 {statistics.median(times) * 1000:.0f} ms · p95 {p95 * 1000:.0f} ms · max {times[-1] * 1000:.0f} ms"
    )
    print(f"lỗi: {len(errors)}" + (f" {sorted(set(map(str, errors)))}" if errors else ""))
    ok = not errors and p95 < TARGET_P95_S
    print("SC-003:", "ĐẠT" if ok else "CHƯA ĐẠT", f"(p95 < {TARGET_P95_S:.0f} s, không lỗi)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
