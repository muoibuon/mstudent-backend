"""Chạy backend trên máy tính để điện thoại thật trong cùng mạng gọi được.

    python run_local.py            # http://0.0.0.0:8000
    python run_local.py --port 9000

In ra địa chỉ LAN để nhập vào màn hình đăng nhập của app.
"""

from __future__ import annotations

import argparse
import socket

import uvicorn

from app import config


def lan_ips() -> list[str]:
    ips = set()
    try:  # địa chỉ của card mạng đang ra Internet (không gửi gói nào thật)
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ips.add(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    try:
        ips.update(i[4][0] for i in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET))
    except OSError:
        pass
    return sorted(i for i in ips if not i.startswith("127."))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--host", default="0.0.0.0")
    args = ap.parse_args()

    config.secret_key()  # tạo khoá nếu chưa có, báo lỗi sớm nếu cấu hình sai
    print("\n📥 MStudent backend")
    print(
        f"   AI: {'LLM trực tiếp (' + config.OPENAI_MODEL + ')' if config.llm_enabled() else '⚠️  OFFLINE (luật) — đặt OPENAI_API_KEY trong .env để AI chạy thật'}"
    )
    print(
        f"   Google Sign-In: {'bật' if config.google_web_client_id() else 'chưa cấu hình (vẫn đăng nhập bằng email/mật khẩu được)'}"
    )
    print(f"   Admin: {', '.join(sorted(config.admin_emails())) or 'chưa đặt MSTUDENT_ADMIN_EMAILS'}")
    print("\n   Nhập MỘT trong các địa chỉ sau vào app (điện thoại cùng Wi-Fi / hotspot với máy này):")
    for ip in lan_ips() or ["<không tìm thấy IP LAN>"]:
        print(f"     http://{ip}:{args.port}")
    print(f"   Trên chính máy này: http://localhost:{args.port}  (web console + /docs)\n")
    uvicorn.run("app.main:app", host=args.host, port=args.port, proxy_headers=False)


if __name__ == "__main__":
    main()
