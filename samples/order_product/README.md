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
qctool check order_product
```

Kiểm tra offline hiện nhận hai requirement records (US và AC), **một obligation**
và sáu API operations. Hai warnings về không tìm thấy FR/NFR riêng trong SRS
là do SRS giải thích cùng AC, không khai thêm nghĩa vụ kiểm thử; không phải
lỗi OpenAPI hoặc bằng chứng testcase đã chạy.

Chạy pipeline đầy đủ, bật provider thật tường minh:

```bash
qctool run order_product
```

Chỉ chạy một trong hai lệnh full. `generation.profile: business` là alias của `agent` (V2).

> **Giới hạn V2:** agent không dry-run thao tác ghi (`Mutation cannot be dry-run twice`),
> nên case đặt hàng hiện **không thành executable** dù có mutation policy — giữ thủ công.
> Cần thay đổi tool (dry-run tới trước submit, runner submit một lần) trước khi dùng sample này. `auth.mode: browser` cho phép đăng nhập
bootstrap; fixture aliases bind vào đúng `AC-order_product-001-1`. Một case
generated thường có ID `TC_ORDER_PRODUCT_001`; source obligation là định danh
ổn định, ID candidate có thể thay đổi theo generation pass.

## Cấp quyền mutation có phạm vi

Config có `exploration.mutation`, mặc định **`enabled: false`**. Đổi đúng
field này thành `true` nếu muốn cho phép explorer thực hiện tạo đơn thật.
`--llm` không tự bật quyền, `--allow-provisioning` cũng không thay thế quyền.

Hai rules chỉ áp dụng `AC-order_product-001-1` tại website đã khai:

- `cart-checkout-btn` trên `/cart` được chuyển tới `/checkout`.
- `checkout-submit-btn` trên `/checkout` được chuyển tới `/my-orders` và gửi
  đúng `POST /api/orders`, operation `createOrder`, tại backend origin đã khai.
  JSON phải có `paymentMethod: cod`, chỉ được chứa address/phone/paymentMethod/cartItemIds.
  SePay, voucher, field/request khác và redirect của request ghi đều bị chặn.

Mỗi rule tối đa một attempt **exploration trong một generation run**, chia sẻ
budget qua các case/cycle/pass. Attempt đã bắt đầu vẫn tiêu budget nếu bị lỗi;
không retry ghi dữ liệu, không có cache budget toàn cục. Source clause, stable
UI target, current page và OpenAPI phải cùng khớp; quyền không tạo ra evidence.
Explorer vẫn tối đa 5 actions/request và chặn admin/xóa/upload/thanh toán online.

**Budget này dành cho exploration; runner thực thi testcase là pha riêng.**
Nếu explorer đã tạo đơn thì giỏ hàng đã thay đổi. Không coi observation đó
là một lần runner Pass, cũng không giả định giỏ còn đủ dữ liệu cho pha execute.
Muốn thử quyền trước, đặt `out.skip_run: true` để chỉ chạy generation/exploration
và xem audit. Dù skip execution, exploration đã được cấp quyền vẫn có thể tạo đơn.

Input không bảo đảm executable/Pass: cart/address, mọi source outcomes và
grounding vẫn phải được chứng minh. Nếu thiếu thì giữ unresolved; không bỏ assertions.

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
