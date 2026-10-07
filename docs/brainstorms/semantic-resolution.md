---
type: design
status: implemented
created: 2026-10-08
updated: 2026-10-08
lang: vi
changelog:
  - 2026-10-08 | codex | Thêm semantic IR và routing evidence need có kiểm chứng
---

# Semantic resolution có kiểm chứng

## Trust boundary

Model có thể trả `semantic.clauses` bên cạnh proposal cũ. Mỗi clause ghi
`step_seq`, `clause_index`, nguyên văn `source_text` và các atom có kiểu.
Đây vẫn là input không tin cậy. Parser không sửa field hoặc nội dung model.
Validator nối quote về requirement đã trace và kiểm tra từng slot trước khi
lưu IR vào context. IR không phải bằng chứng rằng sản phẩm đang hoạt động đúng.

Các concept: session, precondition, fill, activate, navigate, visible, url,
api, no_request, empty. Runtime action vẫn được kiểm tra bằng ACTION_SPECS,
Step.validate, grounding UI/API, response writer và kiểm tra executability.

## Phạm vi chứng minh

Đây là normalization có slot trích xuất, không phải semantic theorem prover.
Identifier, literal, polarity, actor/fixture fact và thứ tự phải có nguồn.
Câu chưa thể chứng minh đầy đủ giữ unmapped. Các clause tách bằng dấu chấm phẩy
phải được giữ đủ; bỏ một sibling sẽ làm cả step không được chuẩn hóa.
Conjunction chưa thể kiểm tra đầy đủ phải abstain. IR giữ lịch sử binding theo
source quote để step renumber không làm mất provenance của workflow state.

Field có thể ground bằng input type/name tokens; activate có role và label
trích từ nguồn, không cần toàn câu nguồn bằng tên DOM. Hai control cùng phù hợp
vẫn không được lựa chọn tùy ý. Stable ID chứng minh locator, không tự chứng minh
ý nghĩa business của control.

Fast path chỉ chuẩn hóa identifier session/route tường minh với qualifier hữu
hạn; không suy luận prose business hoặc account facts từ credential. Những câu
khác đi qua LLM rồi validator. Grammar cũ vẫn là compatibility path.

## Route authority

Route literal được mở rõ trong Given/When của requirement đã trace có thể là
target khám phá dù UIMap chưa có page đó. Endpoint reference không phải browser
route authority. Origin, scheme và request budget vẫn qua validator explorer.
Expected URL là expectation, không tự cho phép truy cập route khác.

## Rejection và loop

Chỉ rejection có source normalization đã kiểm tra mới có thể sinh evidence
need: UI state, API contract, network binding, workflow state, semantic binding.
Không biến mọi locator/endpoint bịa thành quyền khám phá. Evidence need không
phải browser approval; exploration plan vẫn phải qua safety validator.

Routing ưu tiên chuẩn hóa clause chưa có binding trước khi lập interaction plan.
UI/state/network need sau đó có thể chuyển sang exploration. IR/evidence need
mới có nội dung được tính là progress một lần; state giống nhau vẫn dừng.
Sau enrichment, deterministic grounding chạy trước model. Mọi action sinh từ
IR vẫn qua proposal validator và safe applier; nguyên bản input không đổi.

## Giới hạn

Không hỗ trợ suy luận business tùy ý từ source quote, provisioning do model
quyết định, hoặc thực hiện action khi thiếu DOM/operation/state authority.
Các workflow có navigation chưa có control/state chain đầy đủ vẫn unresolved.
Không dùng quan sát UI để đổi expectation cho hợp với sản phẩm.
