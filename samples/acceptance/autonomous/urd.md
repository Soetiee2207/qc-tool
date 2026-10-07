---
type: urd
feature: autonomous
status: draft
---

# URD — ứng dụng acceptance local

### US-001 — Đăng nhập và xem trước tìm kiếm

**As a** khách hàng
**I want** kiểm tra đăng nhập và xem trước tìm kiếm
**So that** kiểm chứng toàn bộ compiler trên ứng dụng hư cấu local

**Acceptance Criteria**

| ID | Given | When | Then |
| --- | --- | --- | --- |
| AC-001-1 | Phiên anonymous ở /entry; cả hai ô email và mật khẩu trống | Bấm Login | Hiển thị Both fields are required; không gửi POST /api/session; URL vẫn ở /entry |
| AC-001-2 | Open /entry | fill email; fill password; click Login | POST /api/session trả 200 với success=true; URL chuyển tới /workspace |
| AC-001-3 | Open /entry | fill email; fill password; click Login | POST /api/session trả 401 với success=false; URL vẫn ở /entry |
| AC-001-4 | Open /start | Click Preview; fill "orchid" into Search; Click Check | Hiển thị Search ready; URL vẫn ở /review |

AC-001-2 cần tài khoản customer active đã được verify; AC-001-3 dùng cùng tài
khoản và mật khẩu sai từ fixture tin cậy. Policy quy định từng fact riêng.
AC-001-4: Preview là link từ /start đến /review; Search và Check ở /review.
Không tạo tài khoản qua UI, không OTP, không dữ liệu production.
