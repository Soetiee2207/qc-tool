---
type: flows
feature: customer_e2e_test_1
status: source-derived
created: 2026-10-09
updated: 2026-10-09
lang: vi
changelog:
  - 2026-10-09 | claude | Hành trình customer, không thay đổi dữ liệu
---

# Hành trình customer

Hướng dẫn đối chiếu 11 AC, không thêm coverage riêng. Mỗi ca một context mới.

Đăng nhập chung (AC-001-1, AC-002-3/4, AC-003-3/4): anonymous → /login → điền
`active_user.email`, `active_user.password` → bấm `login-submit-btn` → customer về /.

1. **Đăng nhập** — AC-001-1 kết thúc ở /; AC-001-2 submit trống → alert, không POST
   login, ở /login; AC-001-3 anonymous mở /cart → /login.
2. **Mua hàng (đến trước Đặt hàng)** — AC-002-1 anonymous xem /products; AC-002-2
   anonymous bấm Thêm vào giỏ → toast yêu cầu đăng nhập, không POST /api/cart, về /login;
   AC-002-3 đăng nhập rồi mở /cart; AC-002-4 đăng nhập rồi xem /my-orders.
3. **Đặt lịch (đến trước Xác nhận)** — AC-003-1 anonymous xem /services; AC-003-2
   anonymous mở /book-appointment → /login; AC-003-3 đăng nhập, mở /book-appointment,
   thấy bước Chọn dịch vụ và Tiếp theo bị khoá; AC-003-4 đăng nhập rồi xem /my-appointments.

Không bấm: Đặt hàng, Tiến hành thanh toán, Xác nhận đặt lịch, Thêm vào giỏ khi đã đăng
nhập, Xoá, Lưu, Đăng ký. Danh sách có thể rỗng hoặc có dữ liệu; không áp số lượng.
