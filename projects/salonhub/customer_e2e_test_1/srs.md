---
type: srs
feature: customer_e2e_test_1
status: source-derived
created: 2026-10-09
updated: 2026-10-09
lang: vi
changelog:
  - 2026-10-09 | claude | Đối chiếu route, control, text và API từ source SalonHub
---

# SRS — Customer SalonHub E2E

Mười một AC trong `urd.md` là nguồn coverage duy nhất. Phần này là bằng chứng từ
source cho cùng các AC, không thêm nghĩa vụ mới.

## Đối chiếu chức năng

| Tham chiếu | AC | Hành vi xác nhận | Bằng chứng source |
| --- | --- | --- | --- |
| FR-CE2E-001 | AC-001-1 | Login hợp lệ: API 200/success=true; customer về / | pages/auth/Login.jsx; backend authController.login |
| FR-CE2E-002 | AC-001-2 | Form trống: alert, không gọi API, ở lại /login | pages/auth/Login.jsx: handleSubmit |
| FR-CE2E-003 | AC-001-3, AC-003-2 | Route bảo vệ chuyển anonymous về /login | App.jsx; components/common/ProtectedRoute.jsx: `!user` |
| FR-CE2E-004 | AC-002-1 | Trang sản phẩm công khai | pages/products/Products.jsx: h1, search input |
| FR-CE2E-005 | AC-002-2 | Anonymous thêm vào giỏ: toast lỗi, về /login, không gọi API | Products.jsx: handleAddToCart kiểm `!user` trước khi gọi cartService |
| FR-CE2E-006 | AC-002-3 | Customer đã đăng nhập mở được /cart | App.jsx: ProtectedRoute không roles |
| FR-CE2E-007 | AC-002-4 | /my-orders: Đơn hàng của tôi, tab Tất cả | pages/orders/MyOrders.jsx |
| FR-CE2E-008 | AC-003-1 | Trang dịch vụ công khai | pages/services/Services.jsx |
| FR-CE2E-009 | AC-003-3 | Wizard đặt lịch bước 1; Tiếp theo khoá khi chưa chọn dịch vụ | pages/appointments/BookAppointment.jsx: STEPS, canGoNext |
| FR-CE2E-010 | AC-003-4 | /my-appointments: Lịch hẹn của tôi, tab Tất cả | pages/appointments/MyAppointments.jsx |

## Route và control

- `/login`: `login-email-input`, `login-password-input`, nút `login-submit-btn`
  (**Đăng nhập**). Submit trống: `login-validation-message`, role `alert`, text
  **Vui lòng điền đầy đủ thông tin**.
- `/products`: heading h1 **Sản phẩm chăm sóc tóc**; `products-search-input`
  placeholder **Tìm kiếm sản phẩm...**; `products-search-btn`, `products-sort-select`,
  `products-cat-all`. Thẻ `product-card-<id>`; nút `product-add-cart-btn-<id>` text
  **Thêm vào giỏ**, bị khoá khi hết hàng (`stock === 0`). ID phụ thuộc dữ liệu.
- Anonymous bấm **Thêm vào giỏ**: toast **Vui lòng đăng nhập để thêm vào giỏ hàng**,
  `navigate('/login')`, return trước khi gọi POST /api/cart.
- `/cart` (đăng nhập): heading **Giỏ hàng** khi có hàng hoặc **Giỏ hàng trống** khi rỗng
  — phụ thuộc dữ liệu, nên AC chỉ kiểm URL. Controls: `cart-select-all-btn`,
  `cart-checkout-btn` (không bấm).
- `/my-orders`: heading **Đơn hàng của tôi**, `order-tab-all` text **Tất cả**.
- `/services`: heading h1 **Dịch vụ của chúng tôi**; `services-search-input` placeholder
  **Tìm kiếm dịch vụ...**; `services-cat-all`; thẻ `services-card-<id>`.
- `/book-appointment` (đăng nhập): h1 **Đặt lịch hẹn**; bước 1 có h2 **Chọn dịch vụ**
  (text này cũng có trong thanh bước — dùng role heading); item `appointment-service-item-<id>`;
  nút **Tiếp theo** `book-appointment-btn` disabled khi `canGoNext()` false (chưa chọn
  dịch vụ); `appointment-back-btn` **Quay lại**. Không bấm `appointment-submit-btn`.
- `/my-appointments`: heading **Lịch hẹn của tôi**, `appointment-tab-all` text **Tất cả**.

## API được sử dụng

Host mặc định trong `frontend/src/services/api.js`: `https://salonhub-3cg8.onrender.com`.
`backend/app.js` mount `/api/auth`, `/api/products`, `/api/services`, `/api/cart`,
`/api/orders`, `/api/appointments`.

- POST `/api/auth/login`: 200 success=true + data.user/token; thiếu trường 400; sai 401.
- GET `/api/auth/profile`, `/api/orders/my-orders`, `/api/appointments/my-appointments`:
  authenticated, success=true.
- GET `/api/products`, `/api/services`: công khai, có cache.
- GET `/api/cart`, POST `/api/cart`: authenticated. POST chỉ khai để kiểm **không** gửi
  trong AC-002-2; tool không được gọi nó.
