---
type: flows
feature: order_product
status: source-derived
created: 2026-10-08
updated: 2026-10-08
lang: vi
changelog:
  - 2026-10-08 | source-review | Một workflow từ cart đến tạo đơn COD
---

# Workflow đối chiếu AC-001-1

File này giải thích cùng obligation trong URD, không khai thêm flow coverage.

```text
Customer đăng nhập bằng tài khoản có sẵn trong env
  → mở /cart
  → một cart item hợp lệ, quantity 1, được chọn
  → bấm Tiến hành thanh toán
  → /checkout, địa chỉ mặc định được chọn, COD mặc định
  → không nhập voucher, không thêm/sửa địa chỉ
  → bấm Đặt hàng
  → POST /api/orders: 201, success=true, data.order.id được trả
  → order.paymentMethod=cod, status=pending, paymentStatus=pending
  → toast Đặt hàng thành công!
  → /my-orders, heading Đơn hàng của tôi
```

Login là bootstrap/precondition của case, không phải một obligation coverage
riêng. Config `auth.mode: browser` cho phép bootstrap bằng account được cấp;
credentials resolve ở runtime, không chuyển giá trị cho LLM.

Nếu thiếu giỏ hợp lệ/địa chỉ, dừng và báo thiếu dữ liệu. Nếu capture không thấy
response tạo đơn, không dùng URL hoặc toast để thay thế API assertions.
Nếu control chưa có UI evidence, khám phá phải qua safety validator. Plan bị
chặn vì operation tạo đơn không được phép thì giữ unresolved, không nới policy.
