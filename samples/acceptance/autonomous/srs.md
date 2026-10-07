---
type: srs
feature: autonomous
status: draft
---

# Hợp đồng acceptance local

Ứng dụng chỉ chạy trên loopback, database trong bộ nhớ và rỗng mỗi lần chạy.

- /entry: Email, Password và Login; form trống hiển thị alert
  `Both fields are required`, không gọi API và giữ nguyên route.
- POST /api/session: tài khoản tồn tại, active và đúng password → 200,
  success=true và SPA chuyển route /workspace (History API). Sai password → 401, success=false.
- POST /api/customers: policy test cho phép tạo customer, trả 201 success=true.
  Không gửi mail, OTP hoặc tác động dữ liệu bên ngoài process.
- /start: Preview dẫn /review. Điền orchid vào Search rồi Check hiển thị
  `Search ready`, giữ /review. Đây là preview thuần local, không lưu dữ liệu.

Đặc tả API chi tiết trong openapi.yaml. Fact account_exists, account_state,
role, password_valid chỉ được chứng minh bởi reviewed verification policy;
credentials hiện diện không chứng minh account tồn tại.
