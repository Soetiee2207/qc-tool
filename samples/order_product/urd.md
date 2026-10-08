---
type: urd
feature: order_product
status: source-derived
created: 2026-10-08
updated: 2026-10-08
lang: vi
changelog:
  - 2026-10-08 | source-review | Một obligation đặt hàng COD từ giỏ đã chuẩn bị
---

# URD — Customer đặt hàng sản phẩm

Website: `https://salonhub-soe.vercel.app`.
Tài liệu đối chiếu source SalonHub, chưa phải kết luận deployment đạt.
Phạm vi có đúng **một testcase intent**: tạo đơn COD từ giỏ hàng đã chuẩn bị.
Không thêm testcase login độc lập hoặc testcase cho từng trang trung gian.

### US-001 — Khách hàng đặt hàng COD

**As a** khách hàng đã đăng nhập
**I want** đặt các sản phẩm trong giỏ bằng phương thức thanh toán khi nhận hàng
**So that** đơn hàng được ghi nhận và tôi trở lại danh sách đơn hàng của mình

**Acceptance Criteria**

| ID | Given | When | Then |
| --- | --- | --- | --- |
| AC-001-1 | Tài khoản customer đang hoạt động, mật khẩu đúng từ fixture active_user và khách hàng đã đăng nhập; giỏ hàng chỉ có một sản phẩm đang hoạt động với số lượng 1, tồn kho đủ và giá lớn hơn 0; khách hàng đã có địa chỉ giao hàng mặc định đầy đủ thông tin | Mở /cart; bấm Tiến hành thanh toán để tới /checkout; giữ địa chỉ mặc định được chọn và phương thức Thanh toán khi nhận hàng (COD), không nhập mã giảm giá; bấm Đặt hàng | POST /api/orders trả 201 với success=true và data.order có ID của đơn vừa tạo, paymentMethod=cod, status=pending, paymentStatus=pending; hiển thị Đặt hàng thành công!; URL chuyển tới /my-orders; hiển thị Đơn hàng của tôi |

## Điều kiện dữ liệu của testcase

- `active_user.email` và `active_user.password` lấy từ `.env`, không ghi giá trị
  vào tài liệu. Người dùng đã xác nhận tài khoản customer hợp lệ.
- Giỏ hàng và địa chỉ giao hàng là **preconditions cần có**, không phải facts
  đã được xác nhận chỉ vì có tài khoản. Chưa kiểm tra dữ liệu live trong task
  tạo tài liệu này. Nếu thiếu thì testcase phải unresolved/Blocked với lý do rõ.
- Dùng đúng một sản phẩm để tránh đặt nhầm toàn bộ giỏ cá nhân. Không tự chọn
  product ID, địa chỉ, số điện thoại hoặc xóa các items khác để ép precondition.
- Giá dương và không voucher xác định nhánh `paymentStatus=pending`; source
  trả `paid` khi tổng tiền bằng 0. Không đổi kỳ vọng nếu gặp dữ liệu khác.
- Địa chỉ mặc định đã tồn tại; không tạo/sửa địa chỉ trong testcase này.

## Phạm vi và tác động

Đây là **tạo đơn thật**, dù không chuyển tiền online: backend ghi Order,
OrderItem, Payment pending, tăng reservedStock, xóa các cart items được đặt
và gửi notifications. Không tự chạy lặp lại như một test đọc dữ liệu.

Ngoài phạm vi: thêm sản phẩm vào giỏ, tăng/giảm số lượng, tạo địa chỉ,
voucher, SePay/chuyển tiền, hủy đơn, giao hàng, admin/warehouse, đăng ký/OTP.
Không đưa các nhánh này thành nghĩa vụ coverage của feature này.

## Nguồn

Root source: `/home/soetie/Documents/2026_Document/SalonHub`.
Frontend: `pages/cart/Cart.jsx`, `pages/cart/Checkout.jsx`,
`services/orderService.js`, `pages/orders/MyOrders.jsx`, `App.jsx`.
Backend: `controllers/orderController.js::createOrder`, `models/Order.js`,
`routes/orderRoutes.js`, `controllers/cartController.js`,
`controllers/addressController.js`.
