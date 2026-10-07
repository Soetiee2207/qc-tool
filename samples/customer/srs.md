---
type: srs
feature: customer
status: source-derived
created: 2026-10-07
updated: 2026-10-07
lang: vi
changelog:
  - 2026-10-07 | config | Tin cậy account operator xác nhận, bỏ verification probe
  - 2026-10-07 | source-review | Đối chiếu route, control và contract customer
---

# SRS — Customer SalonHub

Bảy AC trong `urd.md` là nguồn coverage duy nhất. Phần này bổ sung bằng chứng
cho cùng AC, không thêm nghiệp vụ hay nghĩa vụ coverage độc lập.

## Đối chiếu chức năng

| Tham chiếu | AC | Hành vi xác nhận | Bằng chứng source |
| --- | --- | --- | --- |
| FR-CUSTOMER-001 | AC-001-1 | Customer login hợp lệ chuyển /; API trả 200/success=true | frontend/src/pages/auth/Login.jsx: useEffect/handleSubmit; backend/controllers/authController.js: login |
| FR-CUSTOMER-002 | AC-001-2 | Form thiếu email/password chặn API, hiển thị thông báo | frontend/src/pages/auth/Login.jsx: handleSubmit và validationMessage |
| FR-CUSTOMER-003 | AC-001-3 | /profile có Thông tin cá nhân và badge Khách hàng khi role=customer | frontend/src/pages/auth/Profile.jsx: roleBadgeMap và phần render |
| FR-CUSTOMER-004 | AC-001-4 | /my-orders có Đơn hàng của tôi và tab Tất cả | frontend/src/pages/orders/MyOrders.jsx: TABS và render |
| FR-CUSTOMER-005 | AC-001-5 | /my-appointments có Lịch hẹn của tôi và tab Tất cả | frontend/src/pages/appointments/MyAppointments.jsx: FILTER_TABS và render |
| FR-CUSTOMER-006 | AC-001-6 | Customer không thuộc danh sách roles của /admin, redirect / | frontend/src/App.jsx: route admin; frontend/src/components/common/ProtectedRoute.jsx: roles check |
| FR-CUSTOMER-007 | AC-001-7 | Anonymous mở protected /profile bị redirect /login | frontend/src/App.jsx; frontend/src/components/common/ProtectedRoute.jsx: !user |

## Route và control

- `/login`: input `login-email-input`, `login-password-input`; button submit
  `login-submit-btn` có nhãn **Đăng nhập**. Không thay bằng nút điều hướng cùng tên.
- Submit trống: `login-validation-message`, role `alert`, text chính xác
  **Vui lòng điền đầy đủ thông tin**. Hai ô vẫn trống; không gọi login API.
  Không dùng riêng sự xuất hiện của toast để bỏ các outcome khác.
- `/profile`: heading **Thông tin cá nhân**, badge **Khách hàng**.
  `profile-fullname-input`, `profile-phone-input` chỉ là controls quan sát;
  không bấm `profile-save-btn` hoặc `profile-pwd-submit-btn`.
- `/my-orders`: heading **Đơn hàng của tôi**, `order-tab-all` text **Tất cả**.
- `/my-appointments`: heading **Lịch hẹn của tôi**, `appointment-tab-all` text **Tất cả**.
- `/admin`: ProtectedRoute cho admin/staff/service_staff/warehouse_staff/accountant;
  customer không được render AdminLayout và bị chuyển `/`.
- `/profile`/`/my-orders`/`/my-appointments` yêu cầu đăng nhập. Không suy ra chúng
  chỉ cho customer từ việc nằm trong CustomerLayout.

## API được sử dụng

`frontend/src/services/api.js` có API host mặc định
`https://salonhub-3cg8.onrender.com`, có thể override bằng `VITE_API_URL`.
Host source không chứng minh deployment đang dùng đúng phiên bản backend đó.
`backend/app.js` mount `/api/auth`, `/api/orders`, `/api/appointments`.

- POST `/api/auth/login`: `authService.login` → authRoutes.login → authController.login.
  JSON email/password; email cũng có thể là phone ở backend. Thiếu trường trả 400;
  account không tồn tại/isActive=false/mật khẩu sai trả 401; hợp lệ trả 200,
  success=true, data.user và data.token. Password bị bỏ khỏi user. Không có kiểm
  role customer tại handler; frontend dùng role để chọn route sau login.
- GET `/api/auth/profile`: authenticated; getProfile trả 200/success=true/data=user
  không chứa password; user không còn tồn tại trả 404.
- GET `/api/orders/my-orders`: authenticated; orderController.getMyOrders dùng
  `req.user.id` để query orders; trả success=true/data=array.
- GET `/api/appointments/my-appointments`: authenticated; getMyAppointments dùng
  `req.user.id`, trả success=true/data=array/meta phân trang.

Không dùng `/api/customers`: route đó là quản lý customer cho admin/accountant,
không phải API tự phục vụ customer. Không đưa endpoint mutation/registration vào spec.

## Ranh giới bằng chứng

Source là cơ sở kỳ vọng. UIMap/Playwright là quan sát hiện tại để tìm controls và
state; không sửa kỳ vọng nếu web đang sai. Account được người dùng xác nhận customer hợp lệ và được ghi dưới assurance DECLARED
trong config. Không probe login trước testcase. Không gắn nhãn VERIFIED cho khai
báo này; AC-001-1 vẫn kiểm HTTP/URL, AC-001-3 kiểm badge customer ở runtime.
