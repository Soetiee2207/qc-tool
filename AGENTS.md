# AGENTS.md — qc-tool

Repo-level guidance for any coding agent (Kimi Code, Claude Code, Cursor, …) working in this repository.

## What this repo is

Tool tự động hoá QC: nhận **tài liệu yêu cầu** (URD/SRS/…) + **link webapp** + (tuỳ chọn) **curl/OpenAPI**,
sinh **testcase theo template chuẩn của team**, **thực thi**, rồi xuất **báo cáo + traceability**.

Đây là tool dùng chung, không gắn với một webapp cụ thể. `login-sso` của VD Data Platform Portal
là **pilot đầu tiên**, không phải phạm vi.

## Where things live

| Need | Location |
|---|---|
| Bối cảnh, quyết định thiết kế | `docs/brainstorms/` |
| Quy ước tracking | `docs/tracking/README.md` |
| Điểm vào tracking | `docs/tracking/INDEX.md` |
| Milestone registry | `docs/tracking/milestones.md` |
| Việc còn lại / chờ quyết định | `docs/tracking/todo.md` |
| Phát hiện về hệ thống được test | `docs/findings/` |
| Mã nguồn | `qctool/` — `ingest/` `generate/` `execute/` `ui/` `report/` `render/` `web/` `agent/` `pipeline.py` |
| Authoring agent (V2) | `qctool/agent/` — `loop.py` (hội thoại tool-calling), `tools.py` (browser/dry-run), `gate.py` (schema/citation/thứ tự), `safety.py` (origin/write/alias), `knowledge.py` (`app-model.yaml`) |
| Kết quả kiểm chứng V2 | `docs/findings/agent-redesign.md` |
| Template testcase (14 cột) | `templates/testcase/` — sinh từ script, **không sửa tay `.xlsx`** |
| Template OpenAPI | `templates/api/` — anh điền, tool đọc |
| Template báo cáo | `templates/report/` |
| Dữ liệu hư cấu để dev/test | `samples/` — **không phải hệ thống thật**, trừ các fixture lấy từ source SalonHub thật: `samples/customer/`, `samples/customer_e2e_test_1/`, `samples/order_product/` |
| Config chạy E2E SalonHub | `qctool.customer.e2e.yaml`, `qctool.customer_e2e_test_1.e2e.yaml` — credential chỉ ở `.env` |
| API giả để chạy thử executor | `tests/mock_server.py` — 4 bug API + 4 bug giao diện cài sẵn |
| Trình duyệt | Playwright + Chromium (đã cài). Bí mật ở `.env` (gitignored) |
| Tầng điều khiển trình duyệt | `qctool/execute/browser.py` — context riêng mỗi case, assert auto-wait, bằng chứng |
| Bản đồ element của webapp | `qctool/ui/crawl.py` → `<out.dir>/ui-map.yaml` (có `test_id`) |
| Test | `tests/` — `test_browser.py` mở Chromium thật (marker `playwright`) |
| Hướng dẫn người dùng | `HUONG-DAN.md` — đọc file này khi giải thích cho người mới |
| File cấu hình mẫu | `qctool.example.yaml` |
| Output sinh ra | `artifacts/` — gitignored |

## Lệnh

```bash
# ── Cách dùng chính ─────────────────────────────────────────────────────────
uv run qctool serve                       # giao diện web — bấm là chạy
uv run qctool all --config qctool.yaml    # cả pipeline từ file cấu hình

# ── Từng bước (khi cần kiểm soát chi tiết) ──────────────────────────────────
uv run qctool ingest   <feature-dir> --feature <tên>
uv run qctool generate --requirements artifacts/<f>/requirements.yaml \
                       --openapi <spec.yaml> --xlsx artifacts/<f>/testcases.xlsx
# ↑ không gọi LLM: OpenAPI → case API; prose → case thủ công (perform.unmapped).
#   Case UI tự động từ prose chỉ có qua `run --config … --llm` (agent).
uv run qctool run      artifacts/<f>/testcases.yaml \
                       --base-url <url> --xlsx artifacts/<f>/testcases.xlsx

# ── V2: agent viết testcase từ tài liệu (cần DeepSeek trong .env) ──────────
uv run qctool validate --config qctool.customer_e2e_test_1.e2e.yaml
QCTOOL_LLM_TIMEOUT_SECONDS=90 QCTOOL_LLM_THINKING=disabled \
  uv run qctool run --config qctool.customer_e2e_test_1.e2e.yaml --llm
uv run playwright show-trace artifacts/<f>/evidence/<MÃ>.trace.zip   # xem lại từng bước

# ── Thử toàn bộ, không cần hệ thống thật ────────────────────────────────────
uv run python -m tests.mock_server --port 8099 &
uv run qctool all --openapi samples/openapi/task-manager-sample.yaml \
                  --feature sample --module SAMPLE \
                  --base-url http://127.0.0.1:8099/api/v1 --token fake

# ── Test & tiện ích ─────────────────────────────────────────────────────────
uv run python -m pytest tests/ -q
uv run scripts/validate_openapi.py <file.yaml>
uv run scripts/build_testcase_template.py
```

Hướng dẫn cho người dùng cuối: `HUONG-DAN.md`.

## Luồng dữ liệu

```
tài liệu ─┐
OpenAPI  ─┼─► requirements.yaml ─► testcases.yaml ─► runner ─► results.json
          │         (ingest)          (generate)      (execute)   results.csv
          │                              │                        junit.xml
          │                              ▼                        report.md
          │                        testcases.xlsx ◄──────────────────┘
          │                        (14 cột)         ghi kết quả ngược
```

Mọi đường đi đều qua `qctool/pipeline.py::run_pipeline()`. **CLI, web UI và CI dùng
chung một hàm** — không có logic nào chỉ tồn tại trong giao diện.

## Kiến trúc — 4 chặng

```
[1] INGEST          [2] GENERATE        [3] EXECUTE      [4] REPORT
tài liệu ─┐
OpenAPI  ─┼─► requirements.yaml ─► testcase IR ─► runner ─► report.md
webapp   ─┘                            │            │        junit.xml
                                       │            │        results.csv
                                  render ─► .xlsx ───┘        results.json
                                  (14 cột)  ◄── ghi kết quả ngược
```

**Cả 4 chặng đã chạy end-to-end**, có giao diện web. Trạng thái chi tiết:
`docs/tracking/milestones.md`.

Vòng lặp quan trọng nhất: file `.xlsx` 14 cột là **bản ghi hai pha** — sinh ra một
lần, rồi chạy điền kết quả vào chính file đó (4 cột runtime). QC không phải đối
chiếu hai file.

Nguyên tắc xuyên suốt: **Chỉ case qua gate và dry-run mới được chấp nhận tự động.**
LLM thiết kế intent và viết toàn bộ case theo vocabulary đóng trong một phiên có feedback.
Prose dùng authoring agent tool-calling (`generated_by: llm`); OpenAPI giữ generator deterministic (`generated_by: engine`).

## Lệnh — quy tắc

- **Không sửa tay file trong `artifacts/`.** Đó là output sinh lại được. Sửa
  `templates/` hoặc `samples/` rồi chạy lại.
- **`samples/` là hư cấu.** Không bao giờ trỏ tool vào URL trong đó.
- Thêm `action` verb mới → phải thêm vào `ACTION_SPECS` trong `qctool/testcase.py`,
  kèm `required`/`optional`. Verb không có trong đó sẽ bị validator chặn.
- **Thêm verb UI mới phải sửa ba chỗ, không phải hai:**
  1. `ACTION_SPECS` (`qctool/testcase.py`) — kèm nhánh trong `describe()` **và**
     `expects()`, vì cột Test Steps / Expected Result là chỗ người QC đọc.
  2. `UI_VERBS` (`qctool/execute/runner.py`) — danh sách "cần trình duyệt", dùng
     chung cho runner và pipeline.
  3. `_run_ui_step` (`qctool/execute/runner.py`) — dispatch sang `BrowserSession`.
  Thiếu bước 2 thì case chạy nhưng báo "chưa mở trình duyệt"; thiếu bước 1 thì
  cột Excel lộ cú pháp máy (`assert.text: target=…`).
- Assert UI dùng `expect()` của Playwright (`_check` trong `browser.py`), **không**
  đọc DOM một lần. Đọc-một-lần là nguồn flake số một của UI test.
- Bước UI không map được vì **thiếu môi trường** (không nạp được axe-core, chưa
  đăng nhập) phải ném `NeedsEnvironment` → `Blocked`. Nuốt thành `Fail` là đổ lỗi
  cho sản phẩm vì lỗi của tool.

## UI/UX test — quy tắc

- **Mỗi testcase một browser context** (`start_case`/`end_case`). Dùng chung context
  là quay lại đúng cái bẫy R4: chạy riêng pass, chạy cả suite fail.
- **Ưu tiên `data-testid`**: agent đặt `target: <test_id>` (`agent/tools.py::locator`), `by_name` chỉ để người
  đọc. Dùng nhãn hiển thị làm selector thì mỗi lần dev sửa chữ là test đỏ.
- **Case đạt ở lần chạy lại là `flaky`, không phải `Pass` sạch.** Báo cáo phải nói
  riêng (Mục 6). Xoá dấu vết lần hỏng đầu là nói dối.
- Bằng chứng (`evidence/<MÃ_TEST>-*.png`, `.trace.zip`) thu **trước khi** đóng
  context. Đọc `browser.evidence` sau `end_case()` — trace chỉ ghi xong ở đó.
- `auth.mode: manual` nghĩa là **không tự đăng nhập**, kể cả khi `.env` có tài
  khoản. Tự đoán ý người dùng ở đây đã làm hỏng cả một lượt chạy thật.
- Test UI thật nằm ở `tests/test_browser.py`, chạy trên trang HTML của
  `tests/mock_server.py`. Trang đó có bug giao diện cài sẵn — test phải khẳng định
  tool **phát hiện được** chúng. Chạy nhanh không cần trình duyệt:
  `uv run python -m pytest tests/ -q -m "not playwright"`.

## Template — quy tắc

`templates/` chứa **hợp đồng đầu vào/đầu ra** với người dùng. Ba thứ khác nhau về bản chất:

| Template | Ai tạo | Tool làm gì |
|---|---|---|
| `testcase/` | Tool sinh, người review | **Ghi ra**, đúng 14 cột, không tự đổi cấu trúc |
| `api/` | Người điền | **Đọc vào** để ground — không có thì tool phải đoán |
| `report/` | Tool sinh, người đọc | **Ghi ra**, ngôn ngữ đơn giản, số liệu lên đầu |

Quy tắc:

- **Không sửa tay file `.xlsx`.** Sửa `scripts/build_testcase_template.py` rồi chạy lại — nếu không,
  lần sinh sau sẽ ghi đè mất.
- Đổi cấu trúc template testcase → phải ghi changelog và báo người dùng, vì file họ đang dùng sẽ khác đi.
- Output của một lần chạy (`artifacts/`) được sửa tự do; template thì không.

## Conventions

- Body **tiếng Việt**, frontmatter key **tiếng Anh**.
- Mọi file trong `docs/` có YAML frontmatter: `type`, `status`, `created`, `updated`, `lang`, `changelog`.
- Changelog entry: `- {YYYY-MM-DD} | {skill} | {note}` — **mới nhất lên trên**, note ≤80 ký tự, factual.
- ID: `TC_{MODULE}_{NNN}` (testcase) · `M{NN}` (milestone) · `W{ww}-{n}` (việc trong kỳ) · `D{n}` (chờ quyết định).
- Timestamp **GMT+7**.

## Rules — quan trọng nhất: KHÔNG NÓI DỐI

Báo cáo QC chỉ có giá trị khi mỗi con số đều đúng. Bốn trạng thái, bốn nghĩa khác nhau:

| Trạng thái | Nghĩa | Tuyệt đối không dùng khi |
|---|---|---|
| `Pass` | Đã chạy, đúng như mong đợi | Case chưa chạy, còn bước chưa map, hoặc chỉ đạt nhờ chạy lại |
| `Fail` | Đã chạy, **sai** như mong đợi → **sản phẩm có lỗi** | Thiếu môi trường test, case chưa map, hoặc lỗi do tool (nạp axe thất bại) |
| `Blocked` | Chưa chạy được: cần tài khoản/dữ liệu/cách map/axe-core | Sản phẩm thật sự trả sai |
| `Not Executed` | Chưa tới lượt (gồm case thủ công) | — |

Trạng thái thứ năm, không phải kết quả mà là **dấu vết**: case đạt ở lần chạy lại
mang cờ `flaky`. Nó vẫn tính `Pass` về số liệu, nhưng báo cáo phải nêu riêng ở Mục 6
— một test lúc được lúc không là vấn đề (race condition của sản phẩm, hoặc test
viết giòn), không phải bằng chứng chất lượng.

Ba lỗi đã gặp thật, và luật sinh ra để chặn chúng tái diễn:

1. **Đổ lỗi cho sản phẩm khi thật ra thiếu môi trường.** Case cần "tài khoản không có
   quyền" để kiểm 403 không thể chạy chỉ với một tài khoản → phải `Blocked` kèm lý do,
   **không** `Fail`. Ghi `Fail` là gửi dev đi tìm bug không tồn tại.
2. **Sinh case không kiểm tra gì cả.** `GET /projects` không body, không tham số ràng buộc,
   mà sinh case "mong đợi 422" → luôn fail giả. Kiểm tra `_can_trigger` trước khi sinh.
3. **Case chưa map bị tính là đạt.** Validator chặn case `needs_mapping` mang trạng thái `Pass`.

Bốn lỗi nữa lộ ra khi chạy trên spec + môi trường **thật** (2026-09-21):

4. **Sinh case cho service không phải đang test.** Spec portal trộn 5 operation
   Keycloak vào cùng file; tool sinh case rồi gọi vào host portal → 404 hàng loạt, 8
   case `Fail` trong khi sản phẩm không có lỗi. Operation `x-external: true` phải bị bỏ qua.
5. **Bỏ qua `servers` cấp operation.** Đây là cơ chế OpenAPI chuẩn để một spec mô tả
   nhiều service. Không tôn trọng nó thì request đi sai host. Xem arg `base` của `http.request`.
6. **Input "không hợp lệ" lại hợp lệ.** Case 422 từng gửi `{"__invalid__": true}` — object
   JSON hợp lệ chứa field lạ; server bỏ qua field lạ và trả **200**. Phải gửi giá trị
   **sai kiểu** so với schema (`_wrong_type_value`), hoặc query vi phạm khi endpoint không có body.
7. **Header mặc định của thư viện bị chặn.** `urllib` gửi `Python-urllib/3.x`, môi trường
   dev chặn UA đó bằng 403 → **mọi** request 403. Luôn khai `USER_AGENT`.

Ba lỗi nữa lộ ra khi tích hợp điều khiển trình duyệt (Playwright) — 2026-09-21:

8. **Tự đăng nhập khi người dùng không yêu cầu.** `.env` có tài khoản là tool tự đi
   đăng nhập, kể cả khi `auth.mode: manual` — và làm hỏng cả lượt chạy trên webapp
   không có form đăng nhập. Chỉ đăng nhập khi mode là `browser`.
9. **Đăng nhập hỏng làm mất luôn trình duyệt.** Case UI không cần xác thực vẫn chạy
   được, nên lỗi đăng nhập phải để trình duyệt sống và case cần xác thực báo `Blocked`.
10. **Lỗi của tool bị ghi thành `Fail` của sản phẩm.** Không nạp được axe-core vì mạng
    chập, hoặc trang không mở được vì `ERR_NETWORK_CHANGED` → từng báo `Fail`. Nay ném
    `NeedsEnvironment` → `Blocked` kèm lý do. Lỗi mạng của máy test **không phải** câu
    trả lời của sản phẩm.
11. **Chạy lại mà bị chặn vẫn bị ghi là "chập chờn".** Vòng thử lại từng coi mọi kết
    quả khác `Fail` là "đã ổn", nên case bị đẩy về trang login ở lần hai được ghi vừa
    `flaky` vừa `Blocked`. Chỉ `Pass` mới đặt cờ `flaky`.

Các luật còn lại:

- **Không suy diễn.** Thiếu owner/acceptance → ghi `TBC`. Đánh dấu *done* **phải có bằng chứng**;
  thêm một việc vào to-do thì không cần.
- **Không sinh case khi không có cơ sở.** Agent không viết được case qua gate + dry-run (hết
  budget, locator không duy nhất, thiếu dữ liệu) → case giữ dạng `perform.unmapped`, `manual`,
  *chưa map*; **không** được đoán selector/URL hay nới gate để lấy số.
- **OpenAPI là nguồn ground cho API.** Endpoint/field không có trong OpenAPI hoặc tài liệu → tool
  **không được bịa**. Thà bỏ sót còn hơn sinh case gọi endpoint không tồn tại.
- **Approval gate (L1):** trước khi Write/Edit, in bảng plan `# | path | action | summary` rồi chờ Y/n —
  trừ khi user đã yêu cầu rõ ràng hoặc đang ở auto mode.
- `artifacts/` là output **sinh lại được** — không sửa tay, không review như source.
- Không hard-code credential vào repo. Bí mật đi qua env / secrets, không qua YAML commit.
- **Sửa mock server thì phải sửa cả docstring của nó.** `tests/mock_server.py` ghi rõ 4 bug
  cài sẵn; test dựa vào những bug đó để biết runner có thật sự phát hiện lỗi.

## Authoring agent — cập nhật 2026-10-09

- `pipeline.py` → `generation.py` → `agent/loop.py`; không dùng patch resolver cũ.
- Tool browser/HTTP áp dụng `agent/safety.py` bên trong từng lệnh: origin, mutation, alias.
- `agent/gate.py` dùng ACTION_SPECS và trích dẫn nguyên văn source cho assertion. Citation
  chứng minh nguồn, **không** chứng minh đầy đủ tương đương ngữ nghĩa.
- `draft_case` hợp lệ được dry-run trên context mới: chạy action, kiểm locator/adapter;
  không trả actual của assertion cho agent. Runner sau đó mới so expected thật.
- `ready`, `needs_review`, `manual`, `blocked_env` là trạng thái generation; không
  thay thế Pass/Fail/Blocked/Not Executed. Needs review vẫn chạy nhưng chưa thành success.
- ARIA snapshot là observation; không thay expected theo DOM. Stable ID luôn ưu tiên,
  không dùng `.first()` để che ambiguity.
- `app-model.yaml` chỉ chứa public hints/macros alias; reuse phải kiểm live. Không lưu
  token/cookie/receipt; hash DOM không chứng minh account state. Preparation cache backend
  vẫn run-scoped và kiểm freshness, tách khỏi knowledge base.
- Budget theo intent: turns/tokens/time. Chạy 1–2 intent đầu tiên, không retry vô hạn.
- Sheet Review trong XLSX ghi accepted/rejected làm label; không tự đổi runtime status.
- Gate chặn ba kiểu case "chạy được nhưng không kiểm gì" (lộ khi chạy customer 7/7, 2026-10-09):
  1. **Bỏ qua bước nguồn.** Route nêu trong Given/When (`mở /admin`) phải có `ui.goto`/HTTP/capture
     tương ứng — nếu không, case đăng nhập rồi assert `/` là `Pass` giả.
  2. **Assert trước hành động cuối.** Mỗi mệnh đề expected phải được assert *sau* bước hành
     động cuối cùng; assert URL trước khi mở trang đích không chứng minh outcome.
  3. **Văn xuôi làm regex.** `assert.url_matches` phải là regex path/URL hợp lệ, không khoảng
     trắng — `pattern: "URL chuyển tới /"` từng sinh `Fail` giả cho sản phẩm.
- Route có vẻ nguy hiểm (`/admin`) chỉ được mở read-only khi Given/When nêu đúng route đó;
  expected URL không cấp quyền. Write/click nguy hiểm vẫn bị chặn riêng.
- `expected: ""` là oracle hợp lệ (ô vẫn trống). Lỗi validate phải nói rõ dạng đúng — lỗi
  mơ hồ ("không hợp lệ") làm agent lặp lại tới hết budget.

- **Bằng chứng của một lượt chạy** (`artifacts/<out.dir>/`): `generation.json` → `agent_history`
  (agent gọi tool nào, lỗi gate/dry-run gì, token mỗi call); `testcases.yaml` (bước runner chạy);
  `runs/<t>/results.json` (Playwright chạy từng bước ra sao); `evidence/` (ảnh, `.trace.zip`).
  Case có điền mật khẩu (fixture alias) hoặc `capture_*` **cố ý không có trace/ảnh**
  (`runner.py` tắt) — trace sẽ chứa mật khẩu/token thật. Không gỡ chặn này mặc định.

Changelog:
- 2026-10-09 | claude | V2: bảng file agent/, lệnh chạy, nơi xem bằng chứng/trace
- 2026-10-09 | claude | Gate: route nguồn phải thực hiện, assert sau action, URL regex
- 2026-10-09 | codex | Agent authoring, citation, dry-run và review tier
