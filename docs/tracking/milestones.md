---
type: milestone-registry
scope: project
lang: vi
status: living
owner: "@binhhm"
created: 2026-09-18
updated: 2026-10-09
changelog:
  - 2026-10-09 | claude | V2: code path M06 → agent/, kết quả live customer
  - 2026-10-09 | codex | Agent redesign: gate/citation/dry-run, live acceptance chưa chốt
  - 2026-09-21 | manual | M04/M06: tầng Playwright đầy đủ — 12 verb UI/UX, retry+flake, evidence+trace, axe
  - 2026-09-18 | manual | thêm `qctool serve` (UI) + `qctool all` (pipeline) + HUONG-DAN.md; tool dùng được
---

# Milestone Registry — qc-tool

> `M01`…`M07`. Đây là **xương sống**: báo cáo tuần là ảnh chụp của file này.
> Đánh số tăng dần, **không đánh số lại**.

**Cột `Owner` / `Nghiệm thu` cần @binhhm xác nhận lại. Ô nào chưa chắc ghi `TBC`, không suy diễn.**
**Ngày target là đề xuất, chưa được chốt.**

## 1. Milestones

| ID | Milestone | Module / Feature | Owner | Target | Status | Acceptance (DoD) | Evidence |
|---|---|---|---|---|---|---|---|
| M01 | Ingest & Requirement model — tài liệu → `requirements.yaml` có ID ổn định + content hash | `qctool/ingest`, `qctool/core/model.py` | TBC | 2026-09-25 | In progress | Parse được `srs.md` + `urd.md` của login-sso ra `requirements.yaml`; mỗi requirement có ID, hash, câu phát biểu, acceptance, trích dẫn nguồn; chạy lại cho ra byte-identical | Parser chạy: 44 requirement (6 US + 15 AC + 10 FR + 13 NFR), 44/44 ID không trùng, 10/10 FR có `traces_to`, 15/15 AC có `belongs_to`; 14 test tự động pass; byte-identical qua 2 lần chạy. **Còn thiếu:** chưa parse `flows`/`states`/`wireframe` (mới ghi hash) — chưa đủ DoD |
| M02 | Test model + sinh case deterministic + validator + render | `qctool/core/testcase.py`, `qctool/generate/`, `qctool/core/validate.py`, `qctool/render/` | TBC | 2026-10-02 | In progress | Sinh được case từ AC + FR + NFR; validator reject được case thiếu `traces_to`, thiếu expected, trùng nhau, verb lạ; render ra đúng 14 cột | Sinh từ OpenAPI sample: 54 case (boundary/auth/negative/positive, 6 kỹ thuật). Sinh từ login-sso: 17 case AC+NFR. Validator bắt được orphan/gap/trùng/verb lạ. Render Excel 14 cột có dropdown + tô màu. 44 test pass. **Còn thiếu:** vocabulary chưa có `db.*`/`cli.run` dùng thật; track LLM chưa làm |
| M03 | Renderer theo template team (14 cột) | `qctool/render/` | TBC | 2026-10-09 | In progress | Render ra file khớp template; 14 cột đúng thứ tự/tên; 4 cột runtime để trống chờ điền; giữ dropdown + định dạng | Đã render 54 dòng × 14 cột, có dropdown + tô màu theo Status; có luôn phần **ghi kết quả ngược** vào 4 cột runtime (`fill_results`). **Còn thiếu:** chưa đối chiếu với file `.xlsx` thật của team (chờ D1 mỗi lần dùng) |
| M04 | Execution engine — HTTP adapter + report | `qctool/execute/`, `qctool/report/` | TBC | 2026-10-16 | In progress | Chạy được case technical; evidence gắn theo testcase ID; phân biệt đúng Pass/Fail/Blocked | **Đã chạy trên môi trường THẬT 2026-09-21** (portal + Keycloak, spec thật): 8/8 case API đạt. Chạy mock API: 29 Pass / 15 Fail / 10 Blocked, ổn định qua 2 lượt; **cả 4 bug cài sẵn đều được phân loại đúng** (3 Fail + bug DELETE là Blocked vì cần dữ liệu setup). Sinh `report.md` + `junit.xml` + `results.csv` + `results.json`; ghi kết quả ngược vào `.xlsx`. **Xong 09-21:** retry + phân loại flake (case đạt ở lần chạy lại mang cờ `flaky`, báo cáo Mục 6 riêng); evidence lưu thành file (`evidence/<MÃ>-*.png`, `.trace.zip`) + mục bằng chứng trong báo cáo/CSV/xlsx. **Còn thiếu:** 11 Fail trên mock là do mock không validate input |
| M05 | Report & traceability | `qctool/report/` | TBC | 2026-10-23 | In progress | Sinh báo cáo Markdown tiếng Việt + JUnit XML + CSV; bảng Requirement ↔ Testcase ↔ Kết quả; liệt kê orphan + gap | Báo cáo Markdown 4 mục (tóm tắt / theo module / lỗi / chưa chạy được) sinh từ số liệu thật; JUnit XML cho CI. Tỉ lệ đạt ghi kèm mẫu số + số test chưa chạy (`Tỉ lệ đạt 66% (29/44) · 10 chưa chạy`), để "0 lỗi" không bị đọc thành "xong hết". Cảnh báo spec in ra màn hình. **Còn thiếu:** chưa có bảng traceability Requirement ↔ Testcase ↔ Kết quả (hiện chỉ có gap/orphan ở chặng generate) |
| M06 | UI adapter + UI map từ link webapp | `qctool/ui/crawl.py`, `qctool/execute/browser.py`, `qctool/agent/` (V2; `mapper.py` đã retire) | TBC | 2026-11-06 | In progress | Crawl webapp → `ui-map.yaml`; sinh case UI chỉ tham chiếu element có trong map; chạy được luồng login trên portal dev | Crawl được 35 element trên portal **sau khi đăng nhập**; đăng nhập Keycloak qua form thật, giữ phiên bằng `storage_state`. **09-21 — tầng điều khiển trình duyệt:** 23 → 40 verb, trong đó **12 verb UI/UX mới** (`ui.hover/press/check/scroll/wait_for`, `assert.disabled/enabled/text/value/attr/count/focused/checked/console_clean/no_broken_requests/axe/screenshot`); assert dùng `expect()` tự chờ thay vì đọc DOM một lần; **context riêng mỗi testcase** (hết phụ thuộc trạng thái giữa case); crawl ghi `test_id` + `disabled`/`checked`, mapper ưu tiên `data-testid`; nhãn UX văn xuôi map được sang verb (`vô hiệu hoá` → `assert.disabled`, `stack trace` → `assert.console_clean`). **Chạy thật trên mock:** 6 case UI → 2 Pass / 4 Fail, đúng 3 bug giao diện cài sẵn (nút không bị khoá, dialog không focus, DOM không cập nhật) + 1 lỗi JS; `assert.axe` chạy được. **Còn thiếu:** upload file/iframe/dialog hệ thống; chưa có tài khoản thiếu quyền để chạy case 403/forbidden |
| M07 | Feedback loop — review → few-shot | `qctool/generate/prompts` | TBC | 2026-11-20 | Planned | Duyệt/sửa/reject case được lưu thành labeled example; prompt dùng lại được; đo được tỉ lệ case được accept tăng theo thời gian | — |

## 2. Bảng trạng thái tổng hợp

| Status | Số milestone | Milestone |
|---|---|---|
| `Planned` | 1 | M07 |
| `In progress` | 6 | M01, M02, M03, M04, M05, M06 |
| `At risk` | 0 | — |
| `Blocked` | 0 | — |
| `Done` | 0 | — |
| `Signed-off` | 0 | — |

**Tổng: 0/7 milestone xong (0%)** — pipeline chạy end-to-end nhưng chưa milestone nào đủ DoD
(chưa chạy trên môi trường thật, chưa có traceability matrix).
**Chặn hiện tại:** chưa có. D2 (spec thật) sẽ nâng chất lượng sinh case.

## 3. Scope map — milestone ↔ code path

| Milestone | Code path (dự kiến) | Phụ thuộc |
|---|---|---|
| M01 | `qctool/ingest/`, `qctool/core/model.py` | 2 doc login-sso |
| M02 | `qctool/generate/`, `qctool/core/validate.py` | M01 |
| M03 | `qctool/render/` | M02, template 14 cột (đã có) |
| M04 | `qctool/execute/` | M02, **D2** (spec thật), D3 (đã chốt) |
| M05 | `qctool/report/` | M04 |
| M06 | `qctool/execute/adapters/ui.py`, `qctool/ingest/webapp.py` | M04 |
| M07 | `qctool/generate/prompts/` | M02 |

## 4. Cách cập nhật file này

- **Đổi status:** sửa ô `Status` + `updated` ở frontmatter + ghi `changelog`, và ghi vào Mục 2 của
  báo cáo tuần đó.
- **Thêm milestone:** thêm dòng, số kế tiếp, **không** đánh số lại.
- **Đóng milestone:** phải đủ cả 4 điều kiện của Definition-of-complete (xem `README.md`).
  Nếu cần, tách one-pager `milestones/M<id>-<slug>.md`.
- Cập nhật luôn Mục 2 bảng tổng hợp và `INDEX.md`.

## Agent redesign — 2026-10-09

Nhánh `agent-redesign`: prose authoring bằng tool calling, giữ native runner và
14 cột XLSX. Không đánh dấu milestone Done chỉ vì có code. Xem
[Finding agent redesign](../findings/agent-redesign.md).

Đã chạy thật (2026-10-09): customer 5/7 Pass, customer_e2e_test_1 9/11 Pass, 0 Fail giả.
Còn cần xác nhận: độ đầy đủ ngữ nghĩa của action/oracle
qua QC review; false-fail/semantic benchmark có labels. Không thay business expectation
theo observation để tăng runnable count.
