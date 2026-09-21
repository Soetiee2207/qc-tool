# Báo cáo kiểm thử — Login SSO

> ⚠️ **ĐÂY LÀ VÍ DỤ MINH HOẠ.** Số liệu trong file này là **giả định**, dựng lên để cho thấy
> báo cáo thật sẽ trông thế nào. Chưa có đợt chạy test thật nào cho login-sso.
> Khi tool chạy thật, file này được sinh tự động và số liệu thay bằng số thật.
>
> Nội dung (tên module, mã yêu cầu, tên lỗi) lấy từ tài liệu login-sso thật, nên anh sẽ thấy quen.

**Môi trường:** Dev · **Ngày chạy:** 2026-09-18 15:40 · **Người chạy:** qc-tool

---

## 1. Tóm tắt

> **Chức năng đăng nhập SSO chạy đúng ở luồng chính. Có 4 lỗi, trong đó 1 lỗi nặng
> liên quan tới đăng xuất — nên sửa trước khi lên production.**

| | Số lượng |
|---|---|
| Tổng số test | 42 |
| Đạt | 34 |
| **Lỗi** | **4** |
| Bị chặn | 2 |
| Chưa chạy | 2 |

**Tỉ lệ đạt:** 81% (34/42)

---

## 2. Chi tiết theo module

| Module | Tổng | Đạt | Lỗi | Bị chặn | Chưa chạy |
|---|---|---|---|---|---|
| Cấu hình xác thực (F-01) | 5 | 5 | 0 | 0 | 0 |
| Đăng nhập SSO (F-03) | 9 | 8 | 1 | 0 | 0 |
| Kiểm tra phiên khi mở trang (F-02) | 6 | 5 | 0 | 1 | 0 |
| Tải hồ sơ người dùng (F-04) | 8 | 7 | 1 | 0 | 0 |
| Đăng xuất (F-06) | 5 | 3 | 2 | 0 | 0 |
| Ngôn ngữ ưa thích (F-05) | 4 | 4 | 0 | 0 | 0 |
| Làm mới token (F-07) | 3 | 2 | 0 | 1 | 0 |
| Chặn truy cập theo quyền (F-08, F-09) | 2 | 0 | 0 | 0 | 2 |
| **Tổng** | **42** | **34** | **4** | **2** | **2** |

---

## 3. Danh sách lỗi

### Lỗi 1 — Đăng xuất xong, bấm Back vẫn vào được trang cũ

| | |
|---|---|
| Mã test | TC_AUTH_031 |
| Mức độ | **Cao** |
| Module | Đăng xuất (F-06) |
| Yêu cầu liên quan | F-06, AC-004-1 |

**Làm gì để tái hiện:**
1. Đăng nhập thành công vào portal
2. Bấm Sign Out ở thanh trên
3. Đợi về trang `/login`
4. Bấm nút Back của trình duyệt

**Mong đợi:** Quay lại `/login`. Phiên đã bị xoá, không xem được dữ liệu cũ.

**Thực tế:** Trình duyệt hiển thị lại trang cũ từ cache. Dữ liệu người dùng vẫn nhìn thấy được.

**Bằng chứng:** `evidence/TC_AUTH_031-back-after-logout.png`

**Ghi chú:** Đây là vấn đề bảo mật trên máy dùng chung — đúng như AC-004-1 mô tả
*"session không còn trên máy shared"*. Báo cáo này chỉ nêu hiện tượng, chưa kết luận nguyên nhân.

---

### Lỗi 2 — Bấm Sign Out xong vẫn còn session bên Keycloak

| | |
|---|---|
| Mã test | TC_AUTH_030 |
| Mức độ | **Cao** |
| Module | Đăng xuất (F-06) |
| Yêu cầu liên quan | F-06, AC-004-1 |

**Làm gì để tái hiện:**
1. Đăng nhập portal
2. Bấm Sign Out
3. Mở lại portal ở tab mới

**Mong đợi:** Hiện trang đăng nhập.

**Thực tế:** Tự động đăng nhập lại ngay, không hỏi gì.

**Bằng chứng:** `evidence/TC_AUTH_030-silent-relogin.mp4`

---

### Lỗi 3 — Sai mã phản hồi khi gọi `/auth/me` sai token

| | |
|---|---|
| Mã test | TC_AUTH_018 |
| Mức độ | Trung bình |
| Module | Tải hồ sơ người dùng (F-04) |
| Yêu cầu liên quan | F-04 |

**Làm gì để tái hiện:**
1. Gọi `GET /api/v1/auth/me` với token bị sửa 1 ký tự

**Mong đợi:** HTTP 401, mã lỗi `UNAUTHORIZED`.

**Thực tế:** Đúng HTTP 401 và đúng mã `UNAUTHORIZED`, **nhưng** cấu trúc trả về là
`detail.error.code` (lồng 3 tầng), trong khi SRS §3.2.4 chỉ ghi `detail`. FE đọc theo SRS sẽ không lấy được mã lỗi.

**Bằng chứng:** `evidence/TC_AUTH_018-response.json`

**Ghi chú:** Đây nhiều khả năng là **lỗi tài liệu, không phải lỗi code** — xem
`docs/findings/2026-09-18-login-sso-doc-review.md` phát hiện P8.

---

### Lỗi 4 — Nút "Sign in with Keycloak" bấm được 2 lần liên tiếp

| | |
|---|---|
| Mã test | TC_AUTH_007 |
| Mức độ | Thấp |
| Module | Đăng nhập SSO (F-03) |
| Yêu cầu liên quan | F-03 |

**Làm gì để tái hiện:**
1. Mở `/login`, xoá cache trình duyệt
2. Bấm nút đăng nhập 2 lần thật nhanh

**Mong đợi:** Nút bị khoá ngay sau lần bấm đầu (theo `ssoBusy`), lần 2 không có tác dụng.

**Thực tế:** Cả 2 lần đều kích hoạt, mở 2 lượt chuyển hướng tới Keycloak.

**Bằng chứng:** `evidence/TC_AUTH_007-double-click.gif`

---

## 4. Chưa chạy được

| Mã test | Lý do | Cần gì để chạy được | Ai xử lý |
|---|---|---|---|
| TC_AUTH_012 | Cần tắt Keycloak để test nhánh lỗi (AC-001-4) | Một môi trường dev có `keycloak_enabled=false` | @binhhm + dev BE |
| TC_AUTH_027 | Token hết hạn sau 5 phút, không chờ được trong 1 lượt chạy | Cách rút ngắn hạn token trên môi trường test | @binhhm + IT |

---

## 5. Độ phủ yêu cầu

| | |
|---|---|
| Yêu cầu có test | 19 / 27 (70%) |
| Yêu cầu **chưa có test nào** | 8 |
| Test **không gắn với yêu cầu nào** | 3 |

**Yêu cầu chưa được test:**

| ID | Tên yêu cầu | Vì sao chưa test |
|---|---|---|
| NFR-SEC-01 | JWT kiểm tra qua JWKS, từ chối token bị sửa | Cần token giả — chưa có cách sinh |
| NFR-SEC-02 | Chặn open redirect ở return URL | Cần bộ dữ liệu URL độc hại |
| NFR-AVAIL-01 | IdP sập → hiện màn hình lỗi rõ ràng | Cần giả lập IdP sập |
| NFR-AVAIL-02 | Cache JWKS trong tiến trình | Không kiểm chứng được từ bên ngoài |
| NFR-OBS-01 | Theo dõi được tỉ lệ 401/403 | **Chưa rõ cách đo** — tài liệu không nêu |
| NFR-OBS-02 | Lỗi xác thực hiện qua i18n, không lộ stack | Cần biết các mã i18n |
| F-10 | Nhắc đăng nhập lại khi đang upload | Cần phiên upload đang chạy |
| AC-002-2 | Vào `/users` khi thiếu quyền → `/forbidden` | **Ngoài phạm vi SRS** — xem findings P6 |

---

## 6. Ghi chú

- Module **Tải hồ sơ người dùng** chạy hơi chậm (trung bình 380ms, ngưỡng NFR-PERF-02 là 250ms).
  Chưa đủ dữ liệu để kết luận, nhưng đáng theo dõi.
- Hai case đăng xuất (Lỗi 1 và Lỗi 2) có thể cùng một nguyên nhân. Nên xem chung.
- Ba test không gắn yêu cầu nào nằm ở module đăng nhập SSO — cần rà lại xem là test thừa hay thiếu tài liệu.

---

*Nguồn số liệu: `results.csv` · `junit.xml` · bằng chứng: `evidence/`*
