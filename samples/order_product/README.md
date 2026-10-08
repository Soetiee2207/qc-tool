# order_product — Một testcase customer đặt hàng COD

## Testcase đề xuất

**Giỏ đã chuẩn bị → checkout COD → tạo đơn thành công → danh sách đơn hàng.**
Source trong `/home/soetie/Documents/2026_Document/SalonHub` xác nhận workflow.
Tool tự ingest/generate; không có testcase YAML viết tay. Bộ input có một
user story, một AC, một business obligation. `srs.md` và `flows.md` chỉ giải
thích cùng AC, không tạo thêm các cases kiểm tra login/trang trung gian.

Các outcomes phải giữ đủ: POST orders 201/success=true, ID đơn vừa tạo,
paymentMethod cod, status pending, paymentStatus pending, toast thành công,
URL /my-orders và heading Đơn hàng của tôi. COD chưa phải thanh toán thành công.

## Chuẩn bị trước khi thử

- Account customer hợp lệ đã có trong `.env`: `QCTOOL_USERNAME`,
  `QCTOOL_PASSWORD`. Config tin cậy xác nhận của operator về account; không
  tạo account, không đăng ký/OTP và không probe verification riêng.
- Giỏ account có đúng **một** sản phẩm active, số lượng **1**, giá dương,
  đủ tồn kho. Nếu giỏ cá nhân có nhiều món, dùng dữ liệu test riêng hoặc chuẩn
  bị thủ công; tool không được tự xóa chúng để ép testcase chạy.
- Account có **địa chỉ giao hàng mặc định** đầy đủ thông tin, phone lấy từ
  địa chỉ đã lưu. Không bịa phone/address và không tạo địa chỉ.
- `.env` đã có provider/model/API key trong `QCTOOL_LLM_*`; không copy giá trị
  sang docs/YAML. Có thể đặt `QCTOOL_LLM_TIMEOUT_SECONDS=90` khi cần.

**Chưa xác nhận cart/address live trong task này.** Có account không tự chứng
minh những preconditions đó. Đơn có tổng tiền dương, không voucher là nhánh
được test; không tự đổi expected thành paid khi tổng tiền bằng 0.

## Lệnh từ root qc-tool

Preflight offline, không gọi website/LLM/Chromium:

```bash
uv run qctool validate --config qctool.order_product.e2e.yaml --llm
```

Kiểm tra offline hiện nhận hai requirement records (US và AC), **một obligation**
và sáu API operations. Hai warnings về không tìm thấy FR/NFR riêng trong SRS
là do SRS giải thích cùng AC, không khai thêm nghĩa vụ kiểm thử; không phải
lỗi OpenAPI hoặc bằng chứng testcase đã chạy.

Chạy pipeline đầy đủ, bật provider thật tường minh:

```bash
uv run qctool run --config qctool.order_product.e2e.yaml --llm
```

Nếu muốn entrypoint `all` đang dùng:

```bash
uv run qctool all --config qctool.order_product.e2e.yaml --llm
```

Chỉ chạy một trong hai lệnh full. Config giữ `generation.profile: business`,
không chạy diagnostic API seeds. `auth.mode: browser` cho phép đăng nhập
bootstrap; fixture aliases bind vào đúng `AC-order_product-001-1`. Một case
generated thường có ID `TC_ORDER_PRODUCT_001`; source obligation là định danh
ổn định, ID candidate có thể thay đổi theo generation pass.

## Giới hạn tool hiện tại cần quan sát

Explorer hiện giới hạn tối đa 5 actions/request và chặn checkout/purchase cùng
POST không được approve. `POST /api/orders` trong OpenAPI là contract evidence,
**không phải quyền cho phép explorer tạo đơn**. Account DECLARED cũng không
chứng minh cart/address hoặc tự authorize mutation.

Vì vậy input này không bảo đảm executable/Pass với engine hiện tại. Nếu bị
chặn, giữ testcase unresolved và xem validator/routing issues trong audit;
không bỏ HTTP/JSON outcomes, không thay bằng case chỉ mở trang và không bật
`--allow-provisioning` để cố vượt safety gate. Chưa thay đổi engine/policy ở đây.

**Nếu case thực sự được resolve và execute, nó tạo đơn thật:** ghi order/items,
giữ tồn kho, tạo payment pending, bỏ items đã đặt khỏi giỏ, gửi notifications
tới customer/warehouse. Không có cleanup tự động trong fixture và không có
thao tác chuyển tiền online. Không chạy lặp lại trên giỏ cá nhân.

## Artifacts cần trace

Trong `artifacts/order-product-e2e/`:

- `requirements.yaml`, `ui-map.yaml`: input đã ingest và UI evidence.
- `generation.json`: logical case, resolutions, LLM/plan/validator issues.
- `testcases.yaml`, `testcases.xlsx`: cases do engine serialize/render.
- `summary.json`, `pipeline.log`: summary và diagnostics của product `run`.
- `runs/<timestamp>/results.json`, `results.csv`, `junit.xml`, `report.md`:
  kết quả execution thực tế. Manual/unresolved không được coi là Pass.

Trace và screenshots đang tắt; evidence phục vụ model là dữ liệu có cấu trúc.
Browser auth state là artifact runtime nhạy cảm, không commit/chia sẻ nó.
