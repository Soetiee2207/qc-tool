---
type: urd
feature: customer_e2e_test_1
status: source-derived
created: 2026-10-09
updated: 2026-10-09
lang: vi
changelog:
  - 2026-10-09 | claude | Ba hành trình customer: đăng nhập, mua hàng, đặt lịch (read-only)
---

# URD — Customer SalonHub E2E: đăng nhập, mua hàng, đặt lịch

## Phạm vi

Website: `https://salonhub-soe.vercel.app`. Tài liệu lấy từ source SalonHub thật
(`frontend/src`, `backend/routes`). Ba hành trình của role **Customer**, mỗi AC là
một intent độc lập, mỗi testcase bắt đầu phiên riêng.

**Không ghi dữ liệu.** Mọi AC dừng **trước** bước tạo dữ liệu thật (thêm vào giỏ khi
đã đăng nhập, Đặt hàng, Xác nhận đặt lịch). Xem mục *Ngoài phạm vi*.

### US-001 — Khách hàng đăng nhập

**As a** khách hàng SalonHub
**I want** đăng nhập bằng tài khoản của mình
**So that** dùng được giỏ hàng, đơn hàng và đặt lịch

**Acceptance Criteria**

| ID | Given | When | Then |
| --- | --- | --- | --- |
| AC-001-1 | Phiên anonymous ở /login; tài khoản customer đang hoạt động và mật khẩu đúng từ fixture active_user | Nhập email; nhập password; bấm Đăng nhập ở form login | POST /api/auth/login trả 200 với success=true; URL chuyển tới / |
| AC-001-2 | Phiên anonymous ở /login; cả hai ô email và mật khẩu trống | Bấm Đăng nhập ở form login | Email và mật khẩu vẫn trống; hiển thị Vui lòng điền đầy đủ thông tin; không gửi POST /api/auth/login; URL vẫn ở /login |
| AC-001-3 | Phiên anonymous chưa đăng nhập | Mở /cart | URL chuyển tới /login |

### US-002 — Khách hàng xem sản phẩm và giỏ hàng trước khi đặt hàng

**As a** khách hàng SalonHub
**I want** xem sản phẩm, giỏ hàng và đơn hàng của mình
**So that** chuẩn bị đặt mua sản phẩm chăm sóc tóc

**Acceptance Criteria**

| ID | Given | When | Then |
| --- | --- | --- | --- |
| AC-002-1 | Phiên anonymous chưa đăng nhập | Mở /products | Hiển thị Sản phẩm chăm sóc tóc; hiển thị ô Tìm kiếm sản phẩm...; URL ở /products |
| AC-002-2 | Phiên anonymous ở /products; danh sách có ít nhất một sản phẩm còn hàng | Bấm Thêm vào giỏ của một sản phẩm còn hàng | Hiển thị Vui lòng đăng nhập để thêm vào giỏ hàng; không gửi POST /api/cart; URL chuyển tới /login |
| AC-002-3 | Phiên anonymous ở /login; tài khoản customer đang hoạt động và mật khẩu đúng từ fixture active_user | Nhập email; nhập password; bấm Đăng nhập ở form login; mở /cart | URL ở /cart |
| AC-002-4 | Phiên anonymous ở /login; tài khoản customer đang hoạt động và mật khẩu đúng từ fixture active_user | Nhập email; nhập password; bấm Đăng nhập ở form login; mở /my-orders | Hiển thị Đơn hàng của tôi; hiển thị nút Tất cả của danh sách đơn hàng; URL ở /my-orders |

### US-003 — Khách hàng đặt lịch hẹn dịch vụ

**As a** khách hàng SalonHub
**I want** xem dịch vụ, mở trang đặt lịch và xem lịch hẹn của mình
**So that** chuẩn bị đặt lịch làm tóc

**Acceptance Criteria**

| ID | Given | When | Then |
| --- | --- | --- | --- |
| AC-003-1 | Phiên anonymous chưa đăng nhập | Mở /services | Hiển thị Dịch vụ của chúng tôi; hiển thị ô Tìm kiếm dịch vụ...; URL ở /services |
| AC-003-2 | Phiên anonymous chưa đăng nhập | Mở /book-appointment | URL chuyển tới /login |
| AC-003-3 | Phiên anonymous ở /login; tài khoản customer đang hoạt động và mật khẩu đúng từ fixture active_user | Nhập email; nhập password; bấm Đăng nhập ở form login; mở /book-appointment | Hiển thị Đặt lịch hẹn; hiển thị tiêu đề bước Chọn dịch vụ; nút Tiếp theo bị vô hiệu hoá khi chưa chọn dịch vụ; URL ở /book-appointment |
| AC-003-4 | Phiên anonymous ở /login; tài khoản customer đang hoạt động và mật khẩu đúng từ fixture active_user | Nhập email; nhập password; bấm Đăng nhập ở form login; mở /my-appointments | Hiển thị Lịch hẹn của tôi; hiển thị nút Tất cả của danh sách lịch hẹn; URL ở /my-appointments |

## Dữ liệu và giới hạn

AC-001-1, AC-002-3/4, AC-003-3/4 dùng account customer có sẵn trong `.env`
qua alias `active_user.email` / `active_user.password`; tài liệu không chứa credential.
Người dùng xác nhận account là customer đang hoạt động (DECLARED). Khai báo không phải
kết quả chạy: testcase vẫn kiểm HTTP/URL/UI thật. Thiếu env → Blocked, không Fail.
AC-001-2/3, AC-002-1/2, AC-003-1/2 không cần account.

Không khẳng định số lượng sản phẩm, dịch vụ, đơn hàng, lịch hẹn, hay giỏ hàng rỗng/có
hàng. AC-002-2 chỉ cần một sản phẩm còn hàng bất kỳ đang hiển thị; không cố định ID.
Expected không được sửa theo những gì website đang hiển thị.

## Ngoài phạm vi (cần mutation policy đã review)

- Thêm vào giỏ khi đã đăng nhập (POST /api/cart), đổi số lượng, xoá khỏi giỏ.
- Tiến hành thanh toán → /checkout → **Đặt hàng** (POST /api/orders).
- Chọn dịch vụ/chi nhánh/thợ/ngày giờ rồi **Xác nhận đặt lịch** (POST /api/appointments),
  đặt cọc, áp mã giảm giá.
- Đăng ký/OTP, quên mật khẩu, đánh giá, sửa hồ sơ/địa chỉ, thao tác admin.

Các bước này tạo bản ghi thật trên production. Không tạo obligation, không tuyên bố covered.
