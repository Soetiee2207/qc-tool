---
type: urd
feature: customer
status: source-derived
created: 2026-10-07
updated: 2026-10-07
lang: vi
changelog:
  - 2026-10-07 | config | Tin cậy account operator xác nhận, bỏ verification probe
  - 2026-10-07 | source-review | Thêm bảy AC customer từ mã nguồn SalonHub
---

# URD — Customer SalonHub

## Phạm vi

Website: `https://salonhub-soe.vercel.app`. Đây là fixture tài liệu từ source
SalonHub thật, không phải app mẫu hư cấu và chưa phải kết luận deployment đạt.
Một hành trình nhỏ: đăng nhập → xem thông tin của mình → kiểm tra ranh giới truy cập.
Bảy AC dưới đây là bảy intent độc lập; không yêu cầu sẵn đơn hàng/lịch hẹn.

### US-001 — Khách hàng đăng nhập và xem khu vực cá nhân

**As a** khách hàng SalonHub
**I want** đăng nhập và xem hồ sơ, đơn hàng, lịch hẹn của mình
**So that** sử dụng khu vực cá nhân với đúng quyền truy cập

**Acceptance Criteria**

| ID | Given | When | Then |
| --- | --- | --- | --- |
| AC-001-1 | Phiên anonymous ở /login; tài khoản customer đang hoạt động và mật khẩu đúng từ fixture active_user | Nhập email; nhập password; bấm Đăng nhập ở form login | POST /api/auth/login trả 200 với success=true; URL chuyển tới / |
| AC-001-2 | Phiên anonymous ở /login; cả hai ô email và mật khẩu trống | Bấm Đăng nhập ở form login | Email và mật khẩu vẫn trống; hiển thị Vui lòng điền đầy đủ thông tin; không gửi POST /api/auth/login; URL vẫn ở /login |
| AC-001-3 | Phiên anonymous ở /login; tài khoản customer đang hoạt động và mật khẩu đúng từ fixture active_user | Nhập email; nhập password; bấm Đăng nhập ở form login; mở /profile | Hiển thị Thông tin cá nhân; hiển thị Khách hàng; URL ở /profile |
| AC-001-4 | Phiên anonymous ở /login; tài khoản customer đang hoạt động và mật khẩu đúng từ fixture active_user | Nhập email; nhập password; bấm Đăng nhập ở form login; mở /my-orders | Hiển thị Đơn hàng của tôi; hiển thị nút Tất cả của danh sách đơn hàng; URL ở /my-orders |
| AC-001-5 | Phiên anonymous ở /login; tài khoản customer đang hoạt động và mật khẩu đúng từ fixture active_user | Nhập email; nhập password; bấm Đăng nhập ở form login; mở /my-appointments | Hiển thị Lịch hẹn của tôi; hiển thị nút Tất cả của danh sách lịch hẹn; URL ở /my-appointments |
| AC-001-6 | Phiên anonymous ở /login; tài khoản customer đang hoạt động và mật khẩu đúng từ fixture active_user | Nhập email; nhập password; bấm Đăng nhập ở form login; mở /admin | URL chuyển tới / |
| AC-001-7 | Phiên anonymous chưa đăng nhập | Mở /profile | URL chuyển tới /login |

## Dữ liệu và giới hạn

AC-001-1/3/4/5/6 dùng cùng account customer có sẵn: alias `active_user.email`
và `active_user.password`, lấy từ env, không có giá trị credential trong tài liệu.
Không dùng account admin/staff thay customer. Người dùng xác nhận account trong env
là customer hợp lệ, đang hoạt động và mật khẩu đúng; config tin cậy khai báo này
(DECLARED), không bắt buộc live verification trước resolution. Khai báo không phải
kết quả execution: testcase vẫn phải kiểm tra HTTP/URL/UI thật. Thiếu giá trị env
thì giữ blocker; account bị từ chối lúc chạy không được đổi expected để coi là đạt.
AC-001-2/7 không cần account. Mỗi testcase bắt đầu phiên riêng; không dựa vào case
trước đã login. Expected outcome không thay đổi theo kết quả quan sát website.

Không khẳng định số đơn/lịch, có đơn/lịch cụ thể, dữ liệu rỗng, hay quyền sở hữu
của từng record đã được kiểm chứng chỉ bằng việc nhìn thấy tiêu đề trang.

## Ngoài phạm vi

- Đăng ký/OTP, xác minh email, quên mật khẩu: **OUT_OF_SCOPE_FOR_CUSTOMER_SMOKE**,
  cần tương tác mailbox/OTP; không tạo obligation, không tuyên bố covered.
- Tạo/hủy lịch hẹn, mua/thanh toán/hủy đơn, đánh giá, đổi mật khẩu, lưu hồ sơ,
  upload avatar và thao tác admin: thay đổi dữ liệu hoặc cần trạng thái riêng.
- Wrong-password/locked-account: không có fixture đã xác nhận riêng trong phạm vi này.

## Nguồn

Root: `/home/soetie/Documents/2026_Document/SalonHub`.
`frontend/src/App.jsx`, `components/common/ProtectedRoute.jsx`, `pages/auth/Login.jsx`,
`pages/auth/Profile.jsx`, `pages/orders/MyOrders.jsx`,
`pages/appointments/MyAppointments.jsx`; `backend/controllers/authController.js`.
Chi tiết đối chiếu nằm trong `srs.md`.
