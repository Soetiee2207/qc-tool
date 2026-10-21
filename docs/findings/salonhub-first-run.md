---
type: finding
status: active
created: 2026-10-10
updated: 2026-10-10
lang: vi
changelog:
  - 2026-10-10 | claude | Đo lại 5 feature sau sửa: 16 → 25 case tự động, 24 Pass
  - 2026-10-10 | claude | Trace lượt đầu 11 feature SalonHub: 43/83 tự động, nguyên nhân + sửa
---

# SalonHub — lượt chạy đầu (2026-10-10 12:58–14:12)

`qctool run salonhub`, DeepSeek, Chromium, chế độ safe. Báo cáo: `projects/salonhub/summary/2026-10-10_12-58-13/`.

| Tổng AC | Case tự động | Đạt | Lỗi | Bị chặn | Chưa chạy |
|---|---|---|---|---|---|
| 83 | 43 | 42 | 1 (giả) | 1 | 39 |

**Không có lỗi sản phẩm thật.** Nguồn: `<feature>/artifacts/3-generate/generation.json → agent_history`
(`stop_reason`: TOKEN_BUDGET 23, MODEL_ABSTAINED 13, REPEATED_ERROR 3 — agent lặp trên lỗi chặn tới hết budget).

| Nguyên nhân | Intent | Sửa |
|---|---|---|
| Socket.IO (`SocketContext.jsx`, `transports: ['polling','websocket']`, chỉ khi đã đăng nhập, retry 10×/2s) gửi `POST /socket.io/` → `safety._route` coi là ghi chưa duyệt → MỌI click sau đăng nhập lỗi "forbidden origin or unreviewed write" | 18 | `exploration.background_paths` (mặc định `/socket.io/`): chặn lặng, không tính critical |
| Assert "không gửi POST X" cần operation trong contract, nhưng OpenAPI cố ý bỏ API ghi → "Capture is not grounded" | 13 | API ghi vào OpenAPI với `x-qc-observe-only: true` |
| Ô password chỉ nhận fixture alias; case âm tính viết mật khẩu giả literal | 5 | `account.test_values` → fixture `ac_<id>` |
| `HIGH_RISK` (register/đăng ký/logout) chặn control chỉ điều hướng | 6 | `exploration.safe_controls` (testid đã review) |
| Capture login 10s < cold start Render → TC_AUTH_001 Blocked `UI_RESPONSE_TIMEOUT` (khả dĩ nhất; case login không có trace) | 1 | capture mặc định = `run.timeout_seconds`, thoát sớm 1s sau response; warm-up GET đầu crawl |
| TC_CONTACT_005 Fail giả: `contact-submit-success` luôn có trong DOM (sr-only) → `assert.not_visible` luôn sai | 1 | Then đổi thành "không chứa Cảm ơn…" |
| 11 AC ghi dữ liệu thật — chặn đúng thiết kế | 11 | Mới: `--write` / `mode: write` |

Finding sản phẩm (đã ghi trong `contact/srs.md`): form Liên hệ không gọi API — tin nhắn không tới salon.

## Đo lại sau khi sửa (2026-10-10 14:56, `summary/2026-10-10_14-56-33/`)

Chỉ 5 feature hỏng nhiều nhất (addresses, auth, contact, notifications, orders), chế độ safe:

| | Case tự động | Pass | Fail | Blocked |
|---|---|---|---|---|
| Lượt đầu | 16 / 35 | 15 | 1 (giả) | 1 |
| Sau sửa | 25 / 35 | 24 | 1 (giả) | 0 |

TC_CONTACT_005 vẫn Fail giả với cách viết khác: `assert.not_visible {target: contact-submit-success,
by_name: "Cảm ơn…"}` — runner bỏ qua `by_name`, kiểm `to_be_hidden` trên vùng sr-only luôn tồn tại. Ảnh
bằng chứng xác nhận trình duyệt chặn submit, không có chữ cảm ơn. Đã sửa `browser.not_visible`: testid +
chữ → "ẩn HOẶC không chứa chữ". `qctool step exec` lại trên site thật: contact 5/5 Pass.

10 case còn lại: 4 AC ghi (đúng thiết kế ở safe), 1 do `/register` bị coi là đường dẫn rủi ro (đã thêm
`exploration.safe_paths`), 5 lỗi lẻ của agent (timeout locator, schema sai) — dao động theo lượt.

Chưa chạy lại toàn bộ 11 feature.
