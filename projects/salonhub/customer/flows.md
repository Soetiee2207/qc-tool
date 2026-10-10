---
type: flows
feature: customer
status: source-derived
created: 2026-10-07
updated: 2026-10-07
lang: vi
changelog:
  - 2026-10-07 | source-review | Mô tả hành trình customer không thay đổi dữ liệu
---

# Hành trình customer

Đây là hướng dẫn đối chiếu bảy AC, không thêm coverage flow riêng.
File đặt tại root có chủ ý: ingest đọc AC ở urd.md/srs.md; không thêm một bản
flow dưới srs/*flow*.md để tránh sinh thêm nghĩa vụ trùng.

Mỗi ca dùng context mới. Với AC-001-1/3/4/5/6: mở /login anonymous,
điền email và password từ active_user, bấm login-submit-btn. Backend login hợp lệ
trả 200/success=true; frontend customer tới /. Sau đó, tương ứng từng ca:

- AC-001-1 kết thúc ở /.
- AC-001-3 mở /profile: Thông tin cá nhân, Khách hàng, URL /profile.
- AC-001-4 mở /my-orders: Đơn hàng của tôi, tab Tất cả, URL /my-orders.
- AC-001-5 mở /my-appointments: Lịch hẹn của tôi, tab Tất cả, URL /my-appointments.
- AC-001-6 mở /admin: redirect / vì customer không thuộc allowed roles.

AC-001-2: context anonymous → /login → để hai ô trống → bấm login-submit-btn →
alert Vui lòng điền đầy đủ thông tin; email/password trống; POST /api/auth/login
count=0 trong cửa sổ quan sát submit có giới hạn; URL /login.

AC-001-7: context anonymous → mở /profile → ProtectedRoute chuyển /login.

Không thao tác Save, Cancel, Pay, Review, Register hoặc OTP; không follow luồng
admin. API GET có thể tải danh sách rỗng hoặc có dữ liệu; không áp đặt số lượng.
Source chứng minh route/controls/outcomes như đối chiếu srs.md.
