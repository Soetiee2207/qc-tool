---
type: finding
status: confirmed
created: 2026-09-21
updated: 2026-09-21
lang: vi
owner: "@binhhm"
links: [docs/brainstorms/2026-09-18-qc-automation-tool.md, docs/tracking/milestones.md]
tags: [ui, playwright, honesty, evidence]
changelog:
  - 2026-09-21 | manual | 6 lỗi lộ ra khi chạy thật sau khi tích hợp tầng Playwright (P1–P6)
---

# Tích hợp điều khiển trình duyệt — 6 lỗi chỉ lộ khi chạy thật

> Bối cảnh: sau khi thêm 12 verb UI/UX và tầng Playwright đầy đủ, bộ test tự động
> (172 test) **đã xanh hết** — rồi các lượt chạy thật tìm ra sáu lỗi mà không
> test nào bắt được. Ghi lại vì cả sáu đều thuộc loại "test xanh mà sản
> phẩm sai", đúng thứ dự án này tồn tại để chống.

## P1 — Tự đăng nhập khi người dùng không yêu cầu

**Hiện tượng:** chạy `qctool run --web-url http://127.0.0.1:8123` trên mock server
(không có form đăng nhập). Tool vẫn mở `/login` và cố đăng nhập bằng tài khoản trong
`.env`, thất bại, rồi báo:

```
⚠ Không mở được trình duyệt: BrowserError: Không tìm thấy nút đăng nhập trên trang
```

**Nguyên nhân:** chặng chạy và chặng crawl đều có điều kiện `if cfg.username and …`
— tức là chỉ cần `.env` có tài khoản là tự đăng nhập, **bất kể** `auth.mode`.

**Vì sao test không bắt được:** mọi test đều dựng `PipelineConfig` trực tiếp với
`username=None`, nên nhánh này chưa bao giờ chạy trong test.

**Đã sửa:** chỉ đăng nhập khi `auth.mode == "browser"`. `manual` nghĩa là **không
xác thực** — và điều kiện này giờ được kiểm ở cả ba chỗ (crawl, chạy, `qctool run`).

**Bài học trùng với `_default_auth_mode`:** đoán ý người dùng ở chỗ xác thực đã gây
một lần 32 lỗi 401 giả; đây là lần thứ hai. Xác thực phải là lựa chọn **rõ ràng**.

## P2 — Đăng nhập hỏng làm mất luôn trình duyệt

**Hiện tượng:** sau P1, lượt chạy báo `Không mở được trình duyệt` rồi **mọi** case
UI đều `Fail` (không phải `Blocked`), dù phần lớn case không cần đăng nhập.

**Nguyên nhân:** `login()` nằm trong cùng khối `try` với `BrowserSession(...)` và
`start()`. Một exception ở bước đăng nhập làm `browser = None`, xoá luôn trình duyệt
đã mở thành công.

**Đã sửa:** tách khối đăng nhập ra, bắt riêng, set `authenticated = False` và chạy
tiếp. Case cần xác thực → `Blocked` kèm lý do; case không cần → chạy bình thường.

## P3 — Lỗi của tool bị ghi thành `Fail` của sản phẩm

**Hiện tượng:** `assert.axe` trên máy không ra được Internet:

```
[X] Không quét được accessibility: URLError: <urlopen error [SSL: UNEXPECTED_EOF...]>
→ Kết quả: Fail
```

Báo cáo nói "sản phẩm sai" trong khi **sản phẩm chưa hề được kiểm** — bước quét còn
chưa chạy được.

**Đã sửa:** thêm `NeedsEnvironment` (lớp cha của `NeedsLogin`) cho mọi trường hợp
"không chạy được vì môi trường" → `Blocked` kèm hướng dẫn. Kèm theo: `_axe_source()`
giờ ưu tiên file cục bộ (`qctool/execute/axe.min.js`, hoặc `QCTOOL_AXE_PATH`) để máy
CI không cần Internet.

**Đây là biến thể thứ ba của cùng một luật** (xem `AGENTS.md` — Rules): `Fail` là
lời khẳng định về **sản phẩm**, nên mọi thứ thuộc về môi trường phải là `Blocked`.

## P4 (nhỏ) — Báo cáo đếm sai số request lỗi

Dòng "URL lúc fail: …" được ghi vào `evidence.network`, nên mục "Request lỗi" của
báo cáo đếm cả nó. Đã tách thành trường `note` riêng.

## P5 — Lỗi mạng của máy test bị ghi thành `Fail` của sản phẩm

**Hiện tượng:** lượt chạy trên portal thật (65 case, 2026-09-21 14:55), case
`TC_AUTH_001` báo:

```
[X] Lỗi khi chạy bước: TimeoutError: Page.goto: Timeout 30000ms exceeded.
[X] URL hiện tại là about:blank — KHÔNG khớp «/login?callback=/projects»
→ Kết quả: Fail
```

Trong khi bằng chứng cho thấy nguyên nhân thật:

```
GET https://dev-qc-portal.datafactory.fit/ → không gửi được (net::ERR_NETWORK_CHANGED)
Bối cảnh lúc hỏng: URL lúc fail: chrome-error://chromewebdata/
```

Mạng của máy chạy test đổi giữa lượt. **Chưa hề chạm được vào portal**, nhưng báo
cáo nói sản phẩm sai.

**Đã sửa:** `goto` phân loại lỗi theo `ENV_ERROR_MARKERS` (ERR_NETWORK_CHANGED,
ERR_NAME_NOT_RESOLVED, ERR_CONNECTION_REFUSED, …) và theo cả trường hợp Chromium
"điều hướng thành công" nhưng dừng ở `chrome-error://`. Cả hai → `NeedsEnvironment`
→ `Blocked` kèm lý do, sau khi đã thử lại 3 lần.

**Điểm đáng chú ý:** code **đã có** retry cho `ERR_NETWORK_CHANGED` từ trước, nhưng
`goto` ném `TimeoutError` (không phải lỗi marker) nên nhánh retry không kích hoạt —
dấu hiệu lỗi nằm ở **log request**, không nằm ở exception. Vì vậy `_is_env_problem`
đọc cả `self._network`, không chỉ đọc exception.

## P6 — "Chập chờn" và "bị chặn" bị ghi cùng lúc

**Hiện tượng:** lượt chạy trên portal thật (15:01) báo cáo tự mâu thuẫn — cùng case
`TC_AUTH_001` nằm ở **cả** Mục 5 (Bị chặn) **và** Mục 6 (Chập chờn):

```
[done] ⚠ 1 test CHẬP CHỜN (chỉ đạt sau khi chạy lại): TC_AUTH_001
```

**Nguyên nhân:** trong `run_case`, vòng lặp thử lại kiểm `again.status != STATUS_FAIL`
— tức là coi cả `Blocked` lẫn `Pass` là "lần này ổn". Case bị đẩy về trang login ở
lần chạy lại (thiếu xác thực) được ghi thành "đạt nhờ chạy lại", tức là **chập chờn**.

**Đã sửa:** chỉ `STATUS_PASS` mới đặt cờ `flaky`. Nếu lần chạy lại là `Blocked`, giữ
`Blocked` kèm vết của cả hai lần:

```
Chạy lại lần 1 thì không chạy được (thiếu điều kiện), nên chưa kết luận được về
sản phẩm. Lần đầu hỏng vì: …
```

**Vì sao đây là lỗi nghiêm trọng, không phải lỗi trình bày:** `flaky` là lời khẳng
định "test này có vấn đề về thời điểm" — gửi người đọc đi tìm race condition. Còn
`Blocked` là "chưa kiểm được". Ghi cả hai là vừa khẳng định vừa phủ nhận, và người
đọc sẽ tin vế sai.

---

## Việc cần làm để không lặp lại

| Việc | Trạng thái |
|---|---|
| Test khẳng định `auth.mode: manual` không tự đăng nhập | **đã có** — `test_manual_auth_mode_never_logs_in`; đã kiểm chứng: khôi phục bug thì test đỏ |
| Test khẳng định đăng nhập hỏng ⇒ case khác vẫn chạy | một phần (`test_environment_problem_is_blocked_not_failed`) |
| Test khẳng định lỗi tool ⇒ `Blocked` | đã có |
| Test khẳng định trang không mở được ⇒ `Blocked` | **đã có** — `test_page_unreachable_is_blocked_not_failed` + kiểm trên Chromium thật với host không tồn tại |
| Test khẳng định chạy lại mà bị chặn ⇒ không đặt `flaky` | **đã có** — `test_retry_stops_when_rerun_is_blocked` |
| Chạy thật ít nhất một lượt trên mock **trước khi** báo xong | đã làm — tìm ra P1–P4 |
| Chạy thật lượt nữa trên portal thật **sau khi** sửa | đã làm — tìm ra P5, P6 |

**Nhận xét chung:** cả 6 lỗi đều thuộc một họ — *một thứ không phải kết luận về sản
phẩm bị ghi thành kết luận về sản phẩm*. Bộ test tự động không bắt được vì test chỉ
kiểm những nhánh mình nghĩ tới; chỉ lượt chạy thật mới chạm được nhánh "mạng hỏng",
"`.env` có tài khoản", "trang không có form đăng nhập", "lượt chạy lại không xác thực".
