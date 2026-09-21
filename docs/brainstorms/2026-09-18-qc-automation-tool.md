---
type: brainstorm
status: draft
created: 2026-09-18
updated: 2026-09-21
lang: vi
owner: "@binhhm"
links: [docs/findings/2026-09-18-login-sso-doc-review.md, docs/tracking/milestones.md]
tags: [vision, architecture, input-contract]
changelog:
  - 2026-09-21 | manual | thêm Q9–Q13 + §5.1: Playwright là tầng dưới; auto-wait, context mỗi case, bằng chứng
  - 2026-09-18 | manual | bản đầu — chốt bài toán, input contract, kiến trúc 5 chặng, map 14 field template, pilot login-sso
---

# QC Automation Tool — Brainstorm & Thiết kế

> Phiên làm việc 2026-09-18. Ghi lại toàn bộ mạch suy nghĩ, quyết định, và bằng chứng đã kiểm chứng.
> Mục đích: người (hoặc agent) đọc sau 1 tháng không cần hỏi lại.

## 1. Bài toán & mục tiêu

### 1.1. Mục tiêu lớn

> **Vất input + thông tin cần thiết vào → tool tự làm QC (software testing) một webapp.**

Input gồm 3 nguồn, độ "cứng" rất khác nhau:

| Nguồn | Cho gì | Ghi chú |
|---|---|---|
| Tài liệu (URD/SRS/Excel/Confluence) | Requirement, acceptance criteria, business rule | Nguồn chính, chủ yếu là prose |
| Link webapp | Màn hình, element, luồng UI | **Một URL là không đủ** — phải dựng UI map |
| curl / OpenAPI (tuỳ chọn) | Contract kỹ thuật: endpoint, field, status code | Nguồn "cứng" nhất |

Output kỳ vọng:

1. **File testcase theo template của team** (bắt buộc đúng format).
2. **Thực thi** lần lượt các testcase.
3. **Báo cáo thống kê kết quả** + traceability về requirement.

### 1.2. Non-goals (chốt để khỏi trôi)

- Không phải tool quản lý test case (không thay TestRail/Xray). Nó *sinh ra* file cho tool đó nuốt.
- Không phải tool CI/CD. Nó xuất JUnit XML để CI nuốt.
- Không phải "AI viết test tự do". LLM bị giới hạn trong vocabulary đóng.

### 1.3. Nguyên tắc xuyên suốt

> **LLM không bao giờ sinh ra thứ không chạy được.**
> LLM chỉ làm 2 việc: (a) prose → *mô hình test* có cấu trúc, (b) prose → *step* theo verb trong vocabulary đóng.
> Mọi thứ còn lại là **deterministic**.

Đây là ranh giới quyết định tool có dùng được hay không. Không có nó, tool chỉ là máy viết văn.

## 2. Vì sao các tool kiểu này thường chết

Ba lý do, và cách né:

| Nguyên nhân chết | Cách né trong thiết kế này |
|---|---|
| LLM bịa endpoint/field không tồn tại → phải sửa tay từng case, sửa còn tốn hơn viết | **Grounding bắt buộc**: mọi identifier phải có trong context pack (OpenAPI, DB schema, UI map). Không có → reject |
| Step là văn xuôi ("login as valid user and verify dashboard") → không chạy được | **Vocabulary đóng**: step phải là `action:` + tham số có schema. Verb lạ → validator chặn |
| Requirement không có identity ổn định → không trace được, không sinh lại tăng dần được | **Stable ID + content hash** ngay từ chặng ingest |

## 3. Kiến trúc — 5 chặng

```
[1] INGEST            [2] GENERATE           [3] EXECUTE        [4] REPORT
Tài liệu  ─┐
Webapp    ─┼─► Context Pack ─► Testcase IR ─► Runner ─► JUnit XML / HTML
curl/API  ─┘        │                │                     │
                    │                └─► render theo template team
                    └─ Requirement: ID + hash + trích dẫn nguồn
```

### 3.1. Chặng 1 — Ingest & normalize

Gom 3 nguồn về một **context pack**:

- `requirements.yaml` — mỗi requirement có: ID ổn định, **content hash**, câu phát biểu chuẩn hoá,
  acceptance criteria, priority, và **trích dẫn nguyên văn + vị trí nguồn**.
- `api-surface.yaml` — từ OpenAPI nếu có, hoặc suy từ curl + doc.
- `ui-map.yaml` — từ crawl webapp: màn hình, element, role, label, text.

**Hash là mấu chốt.** Tài liệu sửa → biết chính xác cái gì đổi → chỉ sinh lại testcase liên quan.
Không có hash thì mỗi lần tài liệu đổi phải đập đi làm lại, và mất hết công review.

### 3.2. Chặng 2 — Generate

Hai track, chạy song song:

- **Deterministic** (phần lớn công việc): boundary value analysis, equivalence partitioning,
  decision table, state transition, pairwise. Đảm bảo coverage thay vì trông chờ may mắn.
- **LLM-assisted**: negative case, edge case, security/abuse scenario, narrative test.

Điểm mấu chốt: **LLM dựng mô hình, engine enumerate case từ mô hình đó.**
Kết hợp được độ chặt của deterministic với độ phủ ý tưởng của LLM.

Validator chặn ở cửa ra: verb lạ, case không trace về requirement, thiếu expected result, case trùng nhau.

### 3.3. Chặng 3 — Execute

Vocabulary đóng cho `action:` — adapter nào chưa làm thì để stub, nhưng interface chốt từ đầu:

| Adapter | Dùng cho |
|---|---|
| `http` | gọi API, assert status/body/schema/time |
| `ui` | Playwright — thao tác element trong UI map |
| `db` | verify trạng thái trực tiếp trong DB |
| `cli` | lệnh shell, script |

**"Chạy lần lượt" là một cái bẫy.** Tuần tự ⇒ có phụ thuộc trạng thái ⇒ bug kinh điển: case N để lại
dữ liệu phá case N+1; hoặc chạy riêng pass, chạy cả suite fail. Nên buộc mỗi case khai báo
`setup` / `teardown` / preconditions và mức cô lập dữ liệu (data factory sinh entity mới, không dùng
chung account).

Evidence gắn theo testcase ID: screenshot, response body, trace, thời điểm. Retry 1–2 lần để
**tách flake khỏi fail thật** — report phải phân biệt hai thứ này.

### 3.4. Chặng 4 — Report

Hai thứ khác nhau, đừng gộp:

- **Bảng traceability**: Requirement ↔ Testcase ↔ Kết quả. Đây là thứ stakeholder thật sự đọc.
- **Metrics**: % requirement có test, % đã chạy, pass rate, danh sách fail,
  **orphan test** (case không trace về requirement nào), **gap** (requirement không có case nào).

Export JUnit XML cho CI, HTML cho người đọc.

## 4. Testcase IR — và map với template 14 field

### 4.1. Quyết định: IR là trung tâm, template chỉ là renderer

> **File testcase theo template của team KHÔNG phải định dạng trung tâm.**

Template QC là Excel, thay đổi theo dự án, có cột gộp, dropdown, công thức. Nếu engine sinh thẳng ra
template thì mỗi lần đổi template là mỗi lần viết lại engine. Nên: **IR ở giữa, template là output adapter.**

### 4.2. Map 14 field template → IR

Template của team mô tả 14 field. Map thẳng vào IR:

| # | Field trong template | IR field | Sinh ở đâu |
|---|---|---|---|
| 1 | Test Case ID | `id` — `TC_{MODULE}_{NNN}` | generate |
| 2 | Module / Feature Name | `module` | generate |
| 3 | Test Title / Summary | `title` | generate |
| 4 | Description / Objective | `objective` | generate |
| 5 | Preconditions | `preconditions[]` | generate |
| 6 | Test Data | `test_data{}` | generate |
| 7 | Test Steps | `steps[]` (`action` + tham số) | generate |
| 8 | Expected Result | `expected[]` | generate |
| 9 | **Actual Result** | `actual[]` | **runtime** |
| 10 | **Status** — `Pass / Fail / Blocked / Not Executed` | `status` | **runtime** |
| 11 | Priority / Severity — `High / Medium / Low` | `priority` | generate |
| 12 | **Environment** — browser, OS, device, build | `environment` | **runtime** (config) |
| 13 | **Created By / Date** | `created_by`, `created_at` | generate |
| 14 | **Executed By / Date** | `executed_by`, `executed_at` | **runtime** |

**Nhận xét quan trọng:** 5/14 field là **runtime** (9, 10, 12, 13 một phần, 14). Ranh giới
generator ↔ runner nằm đúng ở đây. Nghĩa là file testcase team nhận được **không chỉ để đọc** —
nó là bản ghi hai pha: pha sinh và pha chạy điền vào cùng một file.

Đây cũng là lý do cần IR: cùng một IR render ra (a) file template lúc sinh, và (b) file template
đã điền kết quả lúc chạy xong.

### 4.3. Ví dụ IR

Ví dụ dưới đây lấy **thật** từ pilot login-sso (F-01), không phải ví dụ chế:

```yaml
id: TC_LOGIN_001
module: "Login SSO - Auth Config"
title: "GET /auth/config trả đủ 4 field cấu hình Keycloak"
objective: "Xác nhận FE lấy được cấu hình Keycloak để khởi tạo adapter"
traces_to: [F-01, AC-001-2]        # bắt buộc — không trace được thì validator reject
technique: equivalence_partitioning # vì sao case này tồn tại
type: positive
priority: High
preconditions: ["Portal API sống tại dev-qc-portal.datafactory.fit"]
test_data: {}
steps:
  - action: http.request
    target: GET /api/v1/auth/config
    auth: none                      # SRS §3.2.1 ghi Auth = None (public)
  - action: assert.http_status
    args: {expected: 200}
  - action: assert.json_schema
    args:
      required: [keycloak_enabled, keycloak_issuer, keycloak_client_id, keycloak_realm]
      types: {keycloak_enabled: boolean}
  - action: assert.json_value
    args: {path: $.keycloak_realm, expected: vd-dev}
expected:
  - "HTTP 200"
  - "Đủ 4 field, đúng kiểu"
  - "keycloak_realm = vd-dev"
provenance:
  source_quote: "Response 200 | keycloak_enabled boolean | keycloak_issuer string|null | keycloak_client_id string|null | keycloak_realm string|null"
  source_ref: "srs.md §3.2.1, dòng 210-217"
  source_hash: "sha256:54b4c13e…763d"
  model: null                       # case deterministic — không qua LLM
status: draft                      # draft → approved → automated → pass/fail
```

Ghi chú: `traces_to` và `provenance.source_quote` **bắt buộc**. Không có thì case là orphan,
không review được, không trả lời được câu "sao lại có case này?".

`model: null` là chi tiết đáng chú ý: case deterministic **không** đi qua LLM, nên provenance của nó
ghi `null`. Nghĩa là report phải phân biệt được case nào do LLM sinh, case nào do engine sinh —
chúng có mức tin cậy khác nhau và cần review khác nhau.

## 5. Quyết định thiết kế đã chốt

| # | Quyết định | Lý do |
|---|---|---|
| Q1 | LLM bị giới hạn trong vocabulary đóng | Step văn xuôi không chạy được |
| Q2 | IR ở giữa, template là renderer | Template đổi theo dự án, không muốn viết lại engine |
| Q3 | Bắt buộc grounding cho mọi identifier | Chống bịa endpoint/field |
| Q4 | Requirement có stable ID + content hash | Traceability + sinh lại tăng dần. **Diff, không regenerate** |
| Q5 | Deterministic sinh case, LLM sinh ý tưởng | Coverage chặt + độ phủ ý tưởng |
| Q6 | Toàn bộ artifact là file YAML/JSON | Diff được, review được trên PR, nhét git được |
| Q7 | Làm HTTP trước UI | UI automation là nơi tool kiểu này chết: locator flaky, chạy chậm, assertion giòn |
| Q8 | Report tách traceability và metrics | Stakeholder đọc traceability; CI đọc JUnit XML |
| Q9 | **Playwright là tầng dưới, không phải đối thủ** | Tool sinh kịch bản, Playwright thực thi. Mỗi case một browser context để cắt phụ thuộc trạng thái (R4) |
| Q10 | Assert UI dùng `expect()` tự chờ, không đọc DOM một lần | Đọc-một-lần là nguồn flake số một: SPA chưa render thì assertion sai ngẫu nhiên, và cái sai ngẫu nhiên đó bị báo thành bug (R3) |
| Q11 | Case chỉ đạt ở lần chạy lại mang cờ `flaky`, báo riêng | "Lúc được lúc không" là vấn đề cần tìm, không phải bằng chứng chất lượng |
| Q12 | Ưu tiên `data-testid` hơn nhãn hiển thị | Nhãn đổi khi dev sửa chữ; test id thì không. Dùng nhãn là tự tạo test giòn |
| Q13 | Lỗi của tool (nạp axe thất bại, chưa đăng nhập) → `Blocked`, không `Fail` | Ranh giới trung thực: `Fail` là lời khẳng định về **sản phẩm** |

### 5.1. Tích hợp điều khiển trình duyệt (bổ sung 2026-09-21)

Playwright mạnh ở tầng nào thì tool giao đúng tầng đó, và giữ lại thứ Playwright
cố ý không làm:

| Việc | Ai làm |
|---|---|
| Điều khiển trình duyệt, auto-wait, trace, screenshot, axe | **Playwright** |
| Sinh kịch bản từ tài liệu/spec | qc-tool |
| Bản đồ element có thật, không bịa selector | qc-tool (`ui-map.yaml`) |
| Bốn trạng thái không nói dối + `flaky` | qc-tool |
| Traceability requirement ↔ testcase ↔ kết quả | qc-tool |
| Template 14 cột, ghi kết quả ngược | qc-tool |

**Ba thứ lấy từ Playwright và vì sao chúng quan trọng hơn chúng có vẻ:**

1. `expect()` (auto-wait) — biến "assert đúng lúc nào" từ câu hỏi không trả lời
   được thành việc của thư viện. Không có nó, mọi assert UI đều là đọc DOM một lần.
2. **Browser context riêng mỗi case** — cắt phụ thuộc trạng thái mà brainstorm §3.3
   đã gọi là "cái bẫy" (R4).
3. **Trace + screenshot** — biến `Fail` từ lời khẳng định thành thứ kiểm chứng được.
   Trước 09-21, `screenshot()` có trong code nhưng **không nơi nào gọi**.


## 6. Pilot: login-sso (VD Data Platform Portal)

### 6.1. Vì sao chọn login-sso làm pilot

Tài liệu đã có sẵn, độ phức tạp vừa phải (10 function, có cả BE + FE + IdP ngoài), và **hệ thống
thật đang chạy** — nghĩa là ground được, chạy được, không phải mock.

### 6.2. Nguồn đã thu thập

| File | Vai trò |
|---|---|
| `docs/authentication/login-sso/urd.md` | 6 user story + 15 acceptance criteria (Given/When/Then) |
| `docs/authentication/login-sso/srs.md` | 10 functional requirement + 13 NFR |
| `docs/authentication/login-sso/srs/login-sso-flows.md` | 3 sequence/activity diagram |
| `docs/authentication/login-sso/srs/login-sso-states.md` | State machine FE session |
| `docs/authentication/login-sso/ascii-screen/login-screen.md` | Wireframe + interactive elements |
| `docs/authentication/login-sso/brainstorms/baseline-from-code.md` | Baseline suy từ code |

**Mật độ dữ liệu:** 6 US / 15 AC / 10 FR / 13 NFR / 3 flow / 1 state machine / 1 wireframe.
Đủ để thử mọi nhánh của pipeline, bao gồm cả acceptance criteria dạng Given/When/Then (map rất thẳng
sang test case) và NFR có ngưỡng định lượng (p95 < 100ms) — cái sau test được bằng k6/assert timing.

### 6.3. Grounding cho API — đã kiểm chứng ngày 2026-09-18

Probe trực tiếp hệ thống thật:

| Kiểm tra | Kết quả |
|---|---|
| `GET /` | 200 — SPA "VinDynamics Data Ingestion Portal UI" |
| `GET /api/v1/auth/config` | **200**, trả đúng 4 field SRS mô tả: `keycloak_enabled`, `keycloak_issuer`, `keycloak_client_id`, `keycloak_realm` |
| `GET /api/v1/auth/me` (không token) | **401** `{"detail":{"error":{"code":"UNAUTHORIZED","message":"Invalid or missing bearer token","details":[]}}}` |
| IdP `/.well-known/openid-configuration` | 200 — realm `vd-dev` sống |
| `GET /openapi.json` | 200 nhưng **trả về `index.html`** (SPA fallback) → không có spec |
| `GET /api/v1/openapi.json` | 404 |

**Kết luận quan trọng:** portal **không expose OpenAPI**. Với app kiểu này, grounding cho API
không thể chỉ dựa vào spec — phải là **doc + crawl + curl do người dùng cấp**. Đây là input cho
quyết định D2 trong `todo.md`.

Điểm tích cực: `/auth/config` khớp **chính xác** với SRS ⇒ tài liệu này đáng tin để làm ground.

### 6.4. Testcase sinh ra từ đâu (dự kiến)

| Nguồn | Loại case | Ví dụ |
|---|---|---|
| `srs.md` §3.2 F-01..F-10 | API functional | F-01: GET `/auth/config` trả 4 field đúng schema |
| `srs.md` §4 NFR | NFR / perf | NFR-PERF-01: `/auth/config` p95 < 100ms |
| `urd.md` AC-001-1..AC-006-2 | Acceptance (Given/When/Then → step) | AC-001-1: mở `/projects` chưa auth → redirect `/login?callback=/projects` |
| `login-sso-states.md` | State transition | Loading → Unauthenticated khi check-sso fail |
| `srs.md` §3.2 error table | Negative | 401 khi thiếu Bearer |
| `login-screen.md` | UI | Click "Sign in with Keycloak" → disabled state khi `ssoBusy` |
| OpenAPI/curl (nếu có) | Technical | boundary trên body PATCH `/auth/me` |

## 7. Rủi ro & cạm bẫy

| # | Rủi ro | Giảm thiểu |
|---|---|---|
| R1 | Tài liệu mơ hồ ("shall be user-friendly") → sinh case rác | Chặng phân tích testability, flag requirement không kiểm chứng được |
| R2 | Tài liệu **mâu thuẫn / thiếu** → case sai âm thầm | Đã gặp thật ở login-sso — xem `docs/findings/2026-09-18-login-sso-doc-review.md`. Tool phải **báo cáo**, không đoán |
| R3 | Flaky UI test → mất niềm tin | Làm HTTP trước; retry + phân loại flake vs fail thật |
| R4 | Chạy tuần tự gây phụ thuộc trạng thái | `setup`/`teardown` bắt buộc + data factory |
| R5 | Credential thật lọt vào repo/CI | Env/secrets; xem D3 |
| R6 | Sinh lại làm mất công review | Diff theo hash (Q4), không regenerate |
| R7 | Acceptance criteria không map thẳng ra case (NFR không trace về US) | Validator báo orphan/gap |

## 8. Lộ trình

Xem `docs/tracking/milestones.md` — M01..M07.

Tóm tắt thứ tự và lý do:

| Phase | Deliverable | Vì sao ở đây |
|---|---|---|
| 0 → M01 | Ingest → `requirements.yaml` (ID + hash) | Nền móng cho mọi thứ sau |
| 1 → M02 | Test model + sinh case deterministic + validator | Chạy được, đã có giá trị dùng ngay |
| 2 → M03 | Renderer theo template team | Cần template thật (D1) |
| 3 → M04 | HTTP executor + evidence | Vòng lặp end-to-end đầu tiên |
| 4 → M05 | Report + traceability | Thứ stakeholder đọc |
| 5 → M06 | UI adapter + UI map từ link webapp | Đắt nhất, để cuối |
| 6 → M07 | Feedback loop (review → few-shot) | Tool tự tốt lên theo dự án |

## 9. Câu hỏi mở / cần chốt

Chuyển thành `D1..D5` trong `docs/tracking/todo.md` Mục 1:

- **D1** — File template testcase thật (`.xlsx`). Screenshot hiện có là **bản mô tả 14 field**,
  không phải file template.
- **D2** — Nguồn ground cho API khi app không expose OpenAPI.
- **D3** — Tài khoản test cho automation (không dùng account thật).
- **D4** — Ngôn ngữ output (testcase & report).
- **D5** — Phạm vi ingest chặng đầu (chỉ markdown, hay cần docx/pdf/xlsx).

## 10. Nguồn & bằng chứng

**Hash tài liệu nguồn** (base để phát hiện thay đổi — đây chính là Q4 áp lên input thật):

| File | SHA-256 |
|---|---|
| `srs.md` | `54b4c13e4685c50cd2118c36a5153992ec344ceeb94afecbf866b88542ed763d` |
| `urd.md` | `952f94ce1e10071d178c0d27d7d232f2f699dfbbe9fdd8135e762b4f83da51bd` |
| `srs/login-sso-flows.md` | `2b08f454f38a148eb17b69f72805b2c321bc337288d161c520b343e18f3cf8c7` |
| `srs/login-sso-states.md` | `e2445ed52439102d64fa714b0fe7b17d618fab4569f1f1c7c5d4858c3c4ced55` |
| `ascii-screen/login-screen.md` | `040d489a9534bda1c8e464af2728f9f091f76718ad193c7aa8359fb5ffd94963` |
| `brainstorms/baseline-from-code.md` | `58247a69e6058fabce99bd047bf84c9668bc87052d5c9341c98d32e280891aae` |

Đường dẫn gốc: `/home/hendry/workspace/data-platform/data-management/vd-data-platform-portal/docs/authentication/login-sso/`
Repo portal tại thời điểm rà: commit `1104150`.

**Probe hệ thống thật:** 2026-09-18, `https://dev-qc-portal.datafactory.fit/` — kết quả ở Mục 6.3.

**Template testcase:** `Screenshot From 2026-09-17 10-28-26.png` — bảng "Standard Test Case Template Structure",
2 cột `Field Name` | `Description / Example Entry`, 14 dòng. Không phải grid Excel.
