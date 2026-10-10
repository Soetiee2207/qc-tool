---
type: srs
feature: order_product
status: source-derived
created: 2026-10-08
updated: 2026-10-08
lang: vi
changelog:
  - 2026-10-08 | source-review | Đối chiếu checkout COD với UI và controller
---

# SRS — Đặt hàng COD từ giỏ hàng

**FR-001 — Ghi nhận đơn COD** là mô tả chi tiết của `US-001 / AC-001-1` ở
`urd.md`, không thêm một acceptance criterion hoặc flow coverage khác.

## Hành vi xác nhận từ source

| Chặng | Hành vi | Bằng chứng source, tính từ root SalonHub |
| --- | --- | --- |
| Xác thực | Login hợp lệ trả 200/success=true; token dùng cho các API của customer | backend/controllers/authController.js:188–214; frontend/src/services/api.js |
| Giỏ hàng | /cart tải giỏ của user, mặc định chọn tất cả items; Tiến hành thanh toán chuyển /checkout kèm selectedIds | frontend/src/pages/cart/Cart.jsx:fetchCart, handleCheckout |
| Checkout | Tải giỏ và các địa chỉ; chọn địa chỉ default, nếu không có default chọn địa chỉ đầu tiên | frontend/src/pages/cart/Checkout.jsx:fetchAddresses, useEffect |
| Phương thức | Giá trị khởi tạo paymentMethod là cod; không bắt buộc chuyển khoản | frontend/src/pages/cart/Checkout.jsx:useState, payment radios |
| Submit | Gửi address ghép từ địa chỉ đã chọn, phone, paymentMethod và cartItemIds khi có selectedIds | frontend/src/pages/cart/Checkout.jsx:handlePlaceOrder; frontend/src/services/orderService.js:create |
| Tạo đơn | Kiểm tra cart không rỗng, product active và quantity không vượt stock; tạo order và items trong transaction | backend/controllers/orderController.js:createOrder |
| Kết quả | HTTP 201, success=true, data.order; status mặc định pending, paymentMethod cod; tổng tiền dương có paymentStatus pending | backend/controllers/orderController.js:createOrder; backend/models/Order.js |
| UI thành công | Với COD: toast Đặt hàng thành công! rồi navigate /my-orders | frontend/src/pages/cart/Checkout.jsx:handlePlaceOrder |
| Danh sách | /my-orders tải đơn của user; heading Đơn hàng của tôi | frontend/src/pages/orders/MyOrders.jsx:fetchOrders, render |

## Routes và controls thực tế

- `/login`: `login-email-input`, `login-password-input`, `login-submit-btn`.
- `/cart`: heading **Giỏ hàng**, button **Tiến hành thanh toán** có
  `data-testid="cart-checkout-btn"`. Không bấm `cart-clear-btn` hoặc remove.
- `/checkout`: heading **Thanh toán**; địa chỉ
  `checkout-address-{id}` / `checkout-address-radio-{id}` dùng ID thực tế.
  Không tự dựng ID. COD radio `checkout-payment-cod`, value `cod`.
  Button **Đặt hàng** là `checkout-submit-btn`.
- `/my-orders`: heading **Đơn hàng của tôi**. Heading không có test ID trong
  source; cần locator được ground từ UI quan sát thực tế.

## API contract và assertion

`openapi.yaml` chỉ mô tả sáu operations dùng để login/bootstrap, đọc giỏ,
địa chỉ, tạo đơn và đọc danh sách đơn. Không bao gồm API admin hay provisioning.

Response tạo đơn phải gắn với click **Đặt hàng**: đúng POST `/api/orders` tại
backend origin đã khai. Không dùng response login hay response của đơn cũ để
chứng minh submit thành công. Giữ đủ HTTP, JSON, toast và URL/heading outcomes.

Không hardcode giá tiền/product ID/order ID. Không coi COD là đã thanh toán.
Không áp quy tắc mới về shipping fee, phone format, minimum order hay email
verification: những quy tắc này chưa được xác nhận cho workflow đang chọn.

GET `/api/cart` có thể xóa cart items của sản phẩm inactive/missing trong
controller; không mô tả operation này là hoàn toàn không có side effects.
Precondition của testcase dùng sản phẩm active, không sử dụng endpoint để
tự dọn giỏ. Đơn được tạo không được hủy tự động trong testcase này.
