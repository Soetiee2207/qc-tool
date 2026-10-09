---
type: todo
scope: project
lang: vi
status: living
owner: "@binhhm"
created: 2026-09-18
updated: 2026-10-09
changelog:
  - 2026-10-09 | claude | Customer 7 intent: 5/7 Pass, 0 Fail; thêm việc tiếp theo
  - 2026-10-09 | codex | Agent redesign: gate/citation/dry-run, live acceptance chưa chốt
  - 2026-09-21 | manual | M06: tầng Playwright đầy đủ — 12 verb UI/UX, context mỗi case, retry+flake, evidence+trace, axe. 172 test
  - 2026-09-21 | manual | thêm `ui.session`: test được login/redirect/guard; khử 63 bước đệm + 19 case bịa. 111 test
  - 2026-09-21 | manual | theo phản hồi user: đọc cả cây tài liệu, parser luồng nghiệp vụ, case thủ công. 25 → 92 case
  - 2026-09-21 | manual | chạy trên spec + môi trường THẬT: 8/8 case API đạt; sửa 4 bug tool; ghi finding spec trộn service
  - 2026-09-18 | manual | tool dùng được: `qctool serve` + `qctool all`; 75 test; HUONG-DAN.md
---

# To-do — qc-tool

> Ô đánh dấu: `[ ]` chưa xong · `[x]` đã xong (giữ 1 kỳ rồi xoá) · `[~]` đang làm · `[!]` đang chặn
> Cột **Nguồn** ghi việc này từ đâu ra, để sau còn truy được.

## 1. Chờ người khác quyết định

| # | Việc | Ai quyết | Thuộc | Nguồn | Từ ngày |
|---|---|---|---|---|---|
| D2 | **Spec OpenAPI thật**: **đã xong 09-21** — spec thật ở `docs/OAS/authentication/openapi.yaml` của repo portal đã được dùng để chạy. Xem `docs/findings/2026-09-21-openapi-mixed-services.md` | @binhhm | M04 | findings P-bổ sung | 09-18 |

> **Đã chốt:** **D1** — anh cam kết mỗi lần dùng tool sẽ cung cấp template; đồng thời đã có
> template 14 cột sinh tự động (`templates/testcase/`) để dùng ngay.
> **D3** — dùng account thật cho automation (chốt 2026-09-18). Vẫn để trong `.env` gitignored,
> **không** hard-code vào repo — vì tool phải dùng được cho hệ thống khác.
> **D4** — output tiếng Việt, ngôn ngữ đơn giản (chốt 2026-09-18).
> **D5** — M01 chỉ hỗ trợ `.md` (chốt 2026-09-18). Lý do: cả 6 tài liệu pilot đều là markdown;
> `.docx`/`.pdf` thêm sau không ảnh hưởng thiết kế. Riêng `.pdf` nên tránh lâu dài vì
> PDF là chữ + toạ độ, không có khái niệm bảng hay cấp bậc tiêu đề — parse sai rất khó phát hiện.

## 2. Kỳ này — W38 (2026-09-14 → 09-20)

### 2.1. Việc đang dở

| # | Việc | Thuộc | Nguồn |
|---|---|---|---|
| [x] W38-1 | Dựng skeleton repo: `uv` + `pyproject.toml` | M01 | brainstorm §8 |
| [x] W38-2 | Định nghĩa schema `requirements.yaml`: id, hash, statement, acceptance, trace, source_quote | M01 | brainstorm §3.1 |
| [x] W38-3 | Parser markdown cho `srs.md`/`urd.md` → `requirements.yaml`; chạy trên login-sso: **44 requirement** (6 US + 15 AC + 10 FR + 13 NFR) | M01 | brainstorm §6.2 |
| [x] W38-4 | Chốt input contract D1–D5 | M03 | brainstorm §9 |
| [x] W38-9 | Dựng package `qctool/` + CLI (`ingest`, `generate`) | M01 | AGENTS.md §Lệnh |
| [x] W38-13 | Bộ test tự động cho ingest | M01 | M01 DoD |
| [x] W38-14 | Ghi 3 bug parser thành test hồi quy: dòng trống trước bảng, `[A-Z]+` không khớp `I18N`, ô chứa `\|` | M01 | M01 DoD |
| [x] W38-16 | **M02**: testcase IR + vocabulary đóng + sinh case (OpenAPI, AC, NFR) + validator + render Excel | M02 | brainstorm §3.2 |
| [x] W38-19 | **M04**: executor chạy testcase thật + `run` CLI + report 4 định dạng + ghi kết quả ngược vào `.xlsx` | M04 | brainstorm §3.3 |
| [x] W38-20 | Mock API có 4 bug cài sẵn — chứng minh pipeline bắt được lỗi thật (3/4) | M04 | M04 DoD |
| [~] W38-21 | **M05**: `report.md` + `junit.xml` + `results.csv` + `results.json`. Còn: bảng traceability Requirement ↔ Testcase ↔ Kết quả | M05 | brainstorm §3.4 |
| [x] W38-24 | **Dùng được**: `qctool serve` (UI web) + `qctool all` (pipeline 1 lệnh) + `HUONG-DAN.md` | — | yêu cầu user |

## 2b. Kỳ W39 (2026-09-21 →)

| # | Việc | Thuộc | Nguồn |
|---|---|---|---|
| [x] W39-1 | `qc.sh` — bốn flag `--docs/--oas/--link/--acc`; mật khẩu qua env, không qua argv | — | yêu cầu user |
| [x] W39-2 | Tự suy `--api` từ `servers` trong spec, khớp tên miền với `--link` | M04 | D2 |
| [x] W39-3 | User-Agent tự khai — `Python-urllib` bị chặn 403, gây 17 fail giả | M04 | D2 |
| [x] W39-4 | Bắt bearer token từ phiên trình duyệt (SPA giữ token trong bộ nhớ, không ở storage) | M04 | D2 |
| [x] W39-5 | Tôn trọng `servers` cấp operation + thêm arg `base` cho `http.request` | M02, M04 | finding 09-21 |
| [x] W39-6 | Bỏ qua operation `x-external: true` — Keycloak không phải service đang test | M02 | finding 09-21 |
| [x] W39-7 | Body case 422 phải **sai kiểu** thật; trước đây là object hợp lệ chứa field lạ → server trả 200 | M02 | D2 |
| [x] W39-8 | Case 422 không body phải gửi query vi phạm (`page=0` với `minimum: 1`) | M02 | chạy mock |
| [x] W39-9 | In cảnh báo spec ra màn hình; tỉ lệ đạt ghi kèm mẫu số + số test chưa chạy | M05 | D2 |
| [x] W39-10 | **Chạy thật**: 25 test · 9 đạt · 0 lỗi · 16 bị chặn; 8/8 case API đạt. 98 test pass | M04 | D2 |
| [x] W39-11 | `discover_features`: trỏ thư mục CHA đọc được cả cây (29 feature), hết "0 requirement" | M01 | user báo lỗi |
| [x] W39-12 | ID `US`/`AC` thêm tiền tố feature — 15 feature cùng đánh số `US-001`, không prefix thì đè nhau | M01 | W39-11 |
| [x] W39-13 | Parser luồng nghiệp vụ: sequence diagram, state machine, bảng quyết định, bề mặt lỗi (28 mục từ login-sso) | M02, M06 | user báo lỗi |
| [x] W39-14 | Sinh case từ FR không có endpoint: `flow` + `error_handling` → **độ phủ FR 0/10 → 10/10** | M02 | user báo lỗi |
| [x] W39-15 | `execution: auto \| manual` — case thủ công là `Not Executed`, không phải `Blocked` | M02, M04 | user báo lỗi |
| [x] W39-16 | Cột Test Steps đọc như câu: hết `perform.unmapped:`, `ui.click: target=` | M03 | user báo lỗi |
| [x] W39-17 | Title dùng `summary` của OAS thay vì `METHOD /path` | M02 | user báo lỗi |
| [x] W39-18 | Crawl 2 pha (trước/sau đăng nhập) + dò link: 1 trang → 15 trang, 322 element; thấy được `/login` | M06 | user báo lỗi |
| [x] W39-19 | Báo cáo tách "Cần người chạy thủ công" khỏi "Bị chặn"; thêm bảng độ phủ theo nguồn | M05 | user báo lỗi |
| [x] W39-20 | **Kết quả**: 25 → **92 case**, độ phủ FR 10/10 · AC 15/15 · luồng 5/5 · trạng thái 15/15. 106 test pass | M02-M06 | W39-11..19 |
| [x] W39-21 | Khử 63 bước "câu đệm" generator tự sinh + khử trùng bảng `error_handling` chép ở 7 FR (19 case bịa) | M02 | tự rà |
| [x] W39-22 | Verb `ui.session` — xoá/nạp phiên trình duyệt. **Điều kiện tiên quyết để test login/redirect/guard** | M04, M06 | user hỏi |
| [x] W39-25 | **Tích hợp điểm mạnh điều khiển trình duyệt của Playwright**: 12 verb UI/UX; assert dùng `expect()` tự chờ (chống flake); **context riêng mỗi testcase**; retry + cờ `flaky`; evidence ảnh/trace/log console/request lỗi; `axe-core`; soft-assert; `run --web-url`; form web có link webapp | M04, M06 | user yêu cầu |
| [x] W39-26 | Crawl ghi `test_id` + `disabled`/`checked`; mapper ưu tiên `data-testid` thay nhãn hiển thị; nhãn UX văn xuôi → verb (`vô hiệu hoá`, `stack trace`, `WCAG`) | M06 | W39-25 |
| [x] W39-27 | Sửa 3 lỗi lộ khi chạy thật: tự đăng nhập dù `auth.mode: manual`; đăng nhập hỏng làm mất trình duyệt; lỗi tool (nạp axe) bị ghi thành `Fail` của sản phẩm | M04, M06 | W39-25 |
| [x] W39-28 | `tests/test_browser.py` — 24 test mở Chromium **thật** trên trang HTML của mock (8 bug giao diện cài sẵn); `test_ui_vocabulary.py`, `test_ui_run.py`. 111 → **172 test** | M04, M06 | W39-25 |
| [x] W39-29 | Phân loại lỗi mạng máy test → `Blocked`; chạy lại mà bị chặn thì không đặt cờ `flaky`. Test hồi quy cho cả 6 lỗi P1–P6 | M04, M06 | findings 09-21 |
| [x] W39-23 | Mapper nhận nhãn ngắn (`Router guard chạy`, `Mở login`) → hành động UI cụ thể | M06 | W39-22 |
| [x] W39-24 | Chỉ chèn `ui.session` cho case UI — case API dùng `auth` của `http.request` | M06 | tự phát hiện |
| [ ] W38-22 | ~~Retry + phân loại flake khỏi fail thật~~ — **xong 09-21** (W39-25): `ui.retry`, cờ `flaky`, báo cáo Mục 6 | M04 | brainstorm §3.3 |
| [ ] W38-23 | ~~Lưu evidence (response body, ảnh) thành file gắn theo testcase ID~~ — **xong 09-21** (W39-25): `evidence/<MÃ>-*.png`, `.trace.zip`, console, request lỗi | M04 | M04 DoD |
| [ ] | Verb UI cho upload file / iframe / dialog hệ thống — nhóm còn thiếu để test UI đầy đủ | M06 | W39-25 |
| [ ] | Dò sâu menu để crawl nhiều màn hình (hiện chỉ theo link tĩnh) | M06 | M06 DoD |
| [ ] | Chạy song song nhiều testcase — bộ UI hiện chạy lần lượt, chậm | M04 | W39-25 |
| [ ] W38-17 | Parse `login-sso-states.md` → state machine, sinh case chuyển trạng thái | M01, M02 | M01 DoD |
| [ ] W38-18 | Parse `login-sso-flows.md` + `login-screen.md` → bổ sung ngữ cảnh cho generator | M01 | M01 DoD |

### 2.2. Việc đã hứa từ trước

| # | Cam kết | Trạng thái |
|---|---|---|
| — | chưa có | — |

## 3. Chưa xếp lịch

| # | Việc | Thuộc | Nguồn |
|---|---|---|---|
| [x] | **Bảng map ID** tài liệu ↔ canonical: `F-01` → `FR-login-sso-001`, `NFR-SEC-01` → `NFR-login-sso-001`. Giữ ID gốc trong `source_ids[]` | M01 | findings P10 |
| [x] | Vocabulary đóng cho `action:` — 20 verb + schema tham số, validator chặn verb lạ | M02, M04 | brainstorm §5 Q1 |
| [ ] | Golden fixture: manifest trỏ tới 6 file login-sso + hash, để regression mỗi lần đổi prompt | M01, M02 | brainstorm §10 |
| [ ] | Map 17 case `needs_mapping` của login-sso sang hành động cụ thể — cần UI map hoặc OpenAPI thật | M06, M04 | kết quả generate |
| [ ] | Thử nghiệm: đo xem deterministic sinh được bao nhiêu % case so với LLM, để biết tỉ lệ thật | M02 | brainstorm §3.2 |
| [x] | Chạy thử trên môi trường thật khi có OpenAPI spec + xác thực (D2) — **xong 09-21**: 8/8 case API đạt trên portal thật | M04 | D2 |

## 4. Đã xong (giữ 1 kỳ rồi xoá)

| # | Việc | Xong ngày | Vào báo cáo |
|---|---|---|---|
| W38-5 | Thu thập & kiểm chứng input pilot: 6 tài liệu login-sso + probe hệ thống thật + hash nguồn | 09-18 | `docs/brainstorms/2026-09-18-qc-automation-tool.md` §6, §10 |
| W38-6 | Rà `srs.md`/`urd.md` login-sso — 10 phát hiện (P1–P10) + 1 xác nhận khớp hệ thống thật | 09-18 | `docs/findings/2026-09-18-login-sso-doc-review.md` |
| W38-7 | Chốt kiến trúc: 5 chặng, IR ở giữa, vocabulary đóng, 8 quyết định thiết kế | 09-18 | `docs/brainstorms/2026-09-18-qc-automation-tool.md` §3, §5 |
| W38-8 | Dựng bộ tracking cho repo qc-tool | 09-18 | `docs/tracking/` |
| W38-10 | Dựng template testcase `.xlsx` 14 cột từ ảnh spec + script sinh lại | 09-18 | `templates/testcase/` |
| W38-11 | Dựng template OpenAPI + script kiểm tra (3 operation thật của login-sso) | 09-18 | `templates/api/` |
| W38-12 | Dựng template báo cáo ngôn ngữ đơn giản + ví dụ đã điền | 09-18 | `templates/report/` |
| W38-15 | **M01 xong phần parser**: tài liệu login-sso → `requirements.yaml`, 44 requirement, 3 tính chất đã verify | 09-18 | `qctool/ingest/`, `artifacts/login-sso/requirements.yaml` |

## Agent redesign — 2026-10-09

Nhánh `agent-redesign`: prose authoring bằng tool calling, giữ native runner và
14 cột XLSX. Không đánh dấu milestone Done chỉ vì có code. Xem
[Finding agent redesign](../findings/agent-redesign.md).

Cần xác nhận: live testcase ready chạy thật; độ đầy đủ ngữ nghĩa của action/oracle
qua QC review; false-fail/semantic benchmark có labels. Không thay business expectation
theo observation để tăng runnable count.

Đã chạy đủ 7 intent customer (lượt `final4`): **5/7 executable, 5 Pass, 0 Fail**.
Chi tiết, lỗi đã sửa và số liệu từng lượt: finding mục "Chạy đủ 7 intent customer".

| # | Việc | Nguồn |
|---|---|---|
| [ ] | Profile: agent lặp locator không duy nhất tới hết budget — hướng agent dùng `role`+name khi text trùng; không nới uniqueness | finding agent-redesign |
| [ ] | Đo tỉ lệ qua nhiều lượt (≥3) thay vì một lượt; báo median + dao động | finding agent-redesign |
| [ ] | Timeout DeepSeek 2/37 call: cân nhắc timeout dài hơn hoặc giảm prompt mỗi turn | finding agent-redesign |
| [ ] | QC gắn nhãn sheet Review cho case `needs_review` → đo tỉ lệ chấp nhận | plan Phase 3 |
| [ ] | Chạy agent trên `order_product` (cần mutation policy đã review) và `smoke` | plan Phase 4 |
| [ ] | Commit nhánh `agent-redesign` (hiện toàn bộ thay đổi chưa commit) | — |

