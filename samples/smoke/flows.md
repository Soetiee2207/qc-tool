---
type: flows
feature: salonhub-smoke
status: source-derived
---

# Luồng đăng nhập bằng mật khẩu

## 5. Core Flows

### 5.1 Đăng nhập SalonHub

1. Người chưa đăng nhập mở /login.
2. Nhập email và mật khẩu theo dữ liệu của AC đang kiểm tra.
3. Bấm Đăng nhập.

Luồng này không tạo obligation mới về business; bốn Given/When/Then trong URD
là nguồn kỳ vọng cụ thể. Không ghép bốn nhánh loại trừ nhau thành một testcase.

## Bốn nhánh của cùng một luồng

| AC | Tiền điều kiện / dữ liệu | Kỳ vọng được xác nhận từ source |
| --- | --- | --- |
| AC-001-1 | Anonymous; customer đang hoạt động; email và mật khẩu đúng | POST /api/auth/login: 200, success=true; thông báo Đăng nhập thành công!; URL / |
| AC-001-2 | Anonymous; email và password trống | Alert Vui lòng điền đầy đủ thông tin; không POST login; URL /login |
| AC-001-3 | Anonymous; tài khoản hoạt động; mật khẩu sai đã xác nhận | POST login: 401; thông báo Email, Số điện thoại hoặc mật khẩu không đúng; URL /login |
| AC-001-4 | Anonymous; tài khoản đã bị khóa, isActive=false; hai ô không trống | POST login: 401; thông báo Tài khoản của bạn đã bị khóa.; URL /login |

Mỗi nhánh chạy bằng phiên anonymous riêng. Không dùng phiên đã đăng nhập vì
Login.jsx sẽ chuyển hướng ngay khi có user. Không khóa tài khoản để chuẩn bị
case; người vận hành cung cấp sẵn dữ liệu kiểm thử. Không gọi endpoint ngoài
POST `/api/auth/login`, không tự lấy OTP, không đăng ký hay đổi mật khẩu.

Nguồn: Login.jsx (submit và redirect), AuthContext.jsx (login), api.js (lỗi 401)
và authController.js (login). Đường dẫn đầy đủ và phạm vi được ghi tại URD.md.
