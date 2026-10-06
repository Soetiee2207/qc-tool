---
type: urd
feature: salonhub-smoke
status: source-derived
smoke_scope:
  included: [AC-001-1, AC-001-2, AC-001-3, AC-001-4]
  excluded:
    - id: SMOKE-REGISTRATION-OTP
      status: OUT_OF_SCOPE_FOR_SMOKE
      reason: requires external OTP/mailbox interaction
      operations: [POST /api/auth/register, POST /api/auth/verify-registration-otp]
      coverage_claim: false
---

# Đăng nhập SalonHub bằng mật khẩu

## Phạm vi

Một luồng duy nhất: người chưa đăng nhập mở `/login`, nhập thông tin và bấm
**Đăng nhập**. Phạm vi gồm khách hàng đăng nhập thành công và ba nhánh từ chối.
Đây là bản mô tả hành vi từ source, không phải bằng chứng deployment đã đạt.

### Loại trừ tường minh

**SMOKE-REGISTRATION-OTP — OUT_OF_SCOPE_FOR_SMOKE**
Reason: **requires external OTP/mailbox interaction**.

Đăng ký và xác nhận OTP không phải obligation của smoke: không sinh/resolve
case đăng ký, không đưa vào mẫu số coverage login, không tính phần loại trừ là
coverage failure và không tuyên bố đã covered. Mục này chỉ là scope record;
không thêm User Story, Acceptance Criterion hoặc operation đăng ký vào smoke.
Không tạo account, bypass OTP, seed production hay đổi backend để chuẩn bị data.

### US-001 — Đăng nhập bằng tài khoản khách hàng

**As a** khách hàng có tài khoản SalonHub
**I want** đăng nhập bằng email và mật khẩu
**So that** được đưa tới trang chủ `/` khi thông tin hợp lệ

**Acceptance Criteria**

| ID | Given | When | Then |
| --- | --- | --- | --- |
| AC-001-1 | Phiên anonymous ở /login; tài khoản customer đang hoạt động và mật khẩu đúng do người vận hành cung cấp | Nhập email và mật khẩu đúng; bấm Đăng nhập | Đăng nhập thành công; URL chuyển tới /; POST /api/auth/login trả 200 với success=true |
| AC-001-2 | Phiên anonymous ở /login; cả hai ô email và mật khẩu trống | Bấm Đăng nhập | Hiển thị Vui lòng điền đầy đủ thông tin; không gửi POST /api/auth/login; URL vẫn ở /login |
| AC-001-3 | Phiên anonymous ở /login; email của tài khoản hoạt động và mật khẩu sai đã xác nhận | Nhập email và mật khẩu sai; bấm Đăng nhập | POST /api/auth/login trả 401; hiển thị Email, Số điện thoại hoặc mật khẩu không đúng; URL vẫn ở /login |
| AC-001-4 | Phiên anonymous ở /login; tài khoản có isActive=false đã được chuẩn bị bởi người vận hành | Nhập email và mật khẩu không trống; bấm Đăng nhập | POST /api/auth/login trả 401; hiển thị Tài khoản của bạn đã bị khóa.; URL vẫn ở /login |

## Ba yêu cầu chức năng

- **FR-001**: tài khoản customer đang hoạt động với mật khẩu đúng đăng nhập
  thành công và được chuyển tới `/` (AC-001-1; SRS F-01).
- **FR-002**: thiếu email hoặc mật khẩu bị chặn tại form; hiện thông báo và không
  gọi API login (AC-001-2; SRS F-02).
- **FR-003**: mật khẩu sai hoặc tài khoản bị khóa bị từ chối với thông báo tương
  ứng và người dùng ở lại `/login` (AC-001-3, AC-001-4; SRS F-03).

## Dữ liệu và giới hạn

Chỉ dùng account customer hoạt động có sẵn và đã kiểm chứng login thành công.
Fixture hiện tại trả 401 cả khi login trực tiếp và qua UI; các facts được khai báo
trong config không chứng minh account đó hợp lệ trên deployment. Chưa có valid
active account thì AC-001-1 giữ unresolved vì thiếu valid test data; không đổi
kỳ vọng 200/success=true thành 401 để coi là đạt.

Không có credential mẫu trong fixture. Người vận hành phải cung cấp tài khoản
customer hoạt động, mật khẩu đúng/sai đã kiểm chứng và tài khoản bị khóa.
Thiếu dữ liệu đó phải giữ testcase unresolved/Blocked, không tự tạo tài khoản,
khóa tài khoản hay đoán credentials. Biến username/password có sẵn trong env
không chứng minh tài khoản thuộc role customer hoặc đang hoạt động.

Không bao gồm Google OAuth, đăng ký/OTP, quên mật khẩu, đổi mật khẩu, chuyển
trang theo role khác customer, đăng nhập qua số điện thoại hay phục hồi phiên.
Không suy ra quy tắc độ dài mật khẩu, định dạng email hoặc giới hạn thử sai.

## Bằng chứng nguồn

Root source: `/home/soetie/Documents/2026_Document/SalonHub`.

- `frontend/src/App.jsx`: route `/login` dùng component Login.
- `frontend/src/pages/auth/Login.jsx`: handleSubmit, validationMessage,
  useEffect chuyển customer tới `/`, và hiển thị lỗi trả về từ API.
- `frontend/src/contexts/AuthContext.jsx`: login lưu token/user và cập nhật user.
- `frontend/src/services/authService.js`: login gọi POST `/auth/login`.
- `frontend/src/services/api.js`: thêm prefix `/api`; ở `/login`, lỗi 401
  được trả lại form thay vì redirect sang một trang khác.
- `backend/app.js`, `backend/routes/authRoutes.js`: mount `/api/auth` và POST `/login`.
- `backend/controllers/authController.js`: login kiểm tra trường trống,
  isActive, mật khẩu và trả 200/400/401.
- `backend/models/User.js`: role customer và trường isActive.
