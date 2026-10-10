# customer_e2e_test_1 — Customer SalonHub: đăng nhập, mua hàng, đặt lịch

Tài liệu lấy từ source SalonHub thật (`/home/soetie/Documents/2026_Document/SalonHub`).
11 AC trong `urd.md` (3 đăng nhập · 4 mua hàng · 4 đặt lịch); `srs.md` là bằng chứng
source; `flows.md` là hành trình; `openapi.yaml` là contract API. Không có testcase viết tay.

**Read-only:** mọi AC dừng trước bước tạo dữ liệu (thêm giỏ khi đã đăng nhập, Đặt hàng,
Xác nhận đặt lịch). Muốn test các bước đó cần mutation policy đã review — xem `urd.md`.

## Chạy

```bash
qctool check customer_e2e_test_1     # offline
qctool run customer_e2e_test_1       # LLM timeout/thinking đặt trong .env
```

`.env` cần `QCTOOL_USERNAME` / `QCTOOL_PASSWORD` (customer có sẵn) và cấu hình DeepSeek.
Thử rẻ trước: thêm `max_intents: 2` vào mục `generation` của config.

## Kết quả và bằng chứng

`artifacts/customer_e2e_test_1/`: `testcases.yaml` / `.xlsx`, `generation.json`
(agent gọi tool nào, lỗi gì), `runs/<thời gian>/results.json` + `report.md`.
Config bật `ui.evidence: always` và `ui.trace: true` → `evidence/<MÃ>-*.png`,
`evidence/<MÃ>.trace.zip`; xem: `uv run playwright show-trace <file>.trace.zip`.
Trace chứa dữ liệu phiên — không chia sẻ ra ngoài.
