---
type: srs
feature: salonhub-smoke
status: source-derived
---

# SRS — Đăng nhập bằng mật khẩu

## Phạm vi smoke và dữ liệu

Chỉ AC-001-1/2/3/4 của luồng login được đánh giá. Registration/OTP mang trạng thái
**OUT_OF_SCOPE_FOR_SMOKE**, reason: **requires external OTP/mailbox interaction**
(URD: SMOKE-REGISTRATION-OTP). Không sinh/resolve case đăng ký; không đưa phần
loại trừ vào coverage login và không báo nó covered. OpenAPI smoke chỉ có login.

AC-001-1 cần account đang hoạt động có sẵn đã xác minh bằng login thật. Chưa có
valid account thì giữ candidate unresolved do missing valid test data; không
provision, bypass OTP hoặc seed production. Config smoke không khai báo fixture
active_user hợp lệ khi dữ liệu hiện tại chưa đạt điều kiện này. Giữ alias bindings
để data thiếu được báo tường minh; credentials chỉ nằm trong env.

## 3. Functional Requirements

### 3.1 Function List

| ID | Function | Implementation | User Story |
| --- | --- | --- | --- |
| F-01 | FR-001: khách hàng đăng nhập thành công | frontend/src/pages/auth/Login.jsx | US-001 |
| F-02 | FR-002: form thiếu thông tin | frontend/src/pages/auth/Login.jsx | US-001 |
| F-03 | FR-003: mật khẩu sai hoặc tài khoản bị khóa | backend/controllers/authController.js | US-001 |

Các alias F-01/F-02/F-03 giữ tương thích parser hiện có. Ingest chuẩn hóa thành
FR-salonhub-smoke-001/002/003; ID FR-001/002/003 trong URD là ID nghiệp vụ gốc.
Chỉ bốn AC trong URD xác định bốn ý định smoke; không mở rộng thêm nghiệp vụ.

#### 3.2.1. F-01 Khách hàng đăng nhập thành công

##### A. Flow

Tại `/login` trong phiên anonymous, nhập email của tài khoản customer đang hoạt
động và mật khẩu đúng, bấm **Đăng nhập**. API trả 200, `success=true`,
`data.user` không chứa password và `data.token` là token đăng nhập.
Form hiển thị toast **Đăng nhập thành công!**; customer được chuyển tới `/`.
Testcase happy path chỉ hoàn thành khi có tài khoản thật đáp ứng tiền điều kiện.

##### B. API Specification

**Endpoint:** POST /api/auth/login

**Auth:** Không yêu cầu token cho login.

Body JSON có `email` và `password`; cả hai phải có giá trị không rỗng.
`email` là tên field backend dù handler cũng tra số điện thoại. Smoke chỉ dùng
email; không áp đặt email format/minimum password length ngoài source.

**Response 200**

| No | Field | Type | Description |
| --- | --- | --- | --- |
| 1 | success | boolean | true |
| 2 | data.user | object | Dữ liệu tài khoản, đã bỏ password |
| 3 | data.token | string | Token đăng nhập; không ghi token vào fixture/log LLM |

#### 3.2.2. F-02 Form thiếu thông tin

##### A. Flow

Nếu email hoặc password trống, bấm **Đăng nhập** làm xuất hiện
**Vui lòng điền đầy đủ thông tin** tại alert và toast. Form không gọi login API.
Smoke kiểm tra cả hai ô trống trong phiên anonymous; URL vẫn `/login`.
Nếu gọi API trực tiếp với dữ liệu thiếu, backend trả 400 và message
`Please provide email and password.`; đây là contract, không phải case smoke thứ năm.

#### 3.2.3. F-03 Từ chối mật khẩu sai hoặc tài khoản bị khóa

##### A. Flow

Mật khẩu sai của tài khoản hoạt động: 401, `success=false`, message
**Email, Số điện thoại hoặc mật khẩu không đúng**.
Tài khoản `isActive=false`: 401, `success=false`, message
**Tài khoản của bạn đã bị khóa.**. Nhánh khóa chạy trước so sánh password.
Trong cả hai trường hợp form hiển thị message qua toast và không rời `/login`.

## 4. Điểm quan sát phục vụ kiểm thử

Các test_id đã có trong Login.jsx: `login-email-input`,
`login-password-input`, `login-submit-btn`, `login-validation-message`.
Alert validation chỉ có mặt sau khi submit thiếu thông tin; không suy ra nó phải
có trong UI map ban đầu. Lỗi API được hiển thị bằng toast, không khẳng định có
test_id cho toast. Không cần thao tác Google/đăng ký/quên mật khẩu.

OpenAPI trong fixture chỉ có POST `/api/auth/login`; không dùng GET profile
vì workflow không reload/khôi phục phiên. Host API mặc định từ services/api.js
là `https://salonhub-3cg8.onrender.com`; VITE_API_URL có thể thay đổi khi build.
Chưa xác nhận deployment Vercel đang dùng đúng host mặc định hay đúng commit.

## 5. Cách nạp fixture

Parser hiện tại cần `urd.md`, `srs.md`, `srs/*flow*.md`; các symlink kèm fixture
trỏ tới URD.md, SRS.md và flows.md, không tạo bản nội dung thứ hai.

```bash
uv run qctool ingest samples/smoke --feature salonhub-smoke
uv run qctool all --config qctool.smoke.yaml
```

Config mặc định `skip_run: true`: chỉ sinh/resolve và xuất artifact; chưa thực thi
trên deployment. Bốn ý định không bảo đảm engine chỉ xuất bốn dòng testcase:
generator có thể sinh thêm case kỹ thuật từ OpenAPI. Không tính case chưa chạy
hoặc chưa map là Pass; cần review testcase sinh ra trước khi bật thực thi.
