---
type: tracking-index
scope: project
lang: vi
status: living
owner: "@binhhm"
created: 2026-09-18
updated: 2026-09-18
changelog:
  - 2026-09-18 | manual | tool dùng được: `qctool serve` mở UI bấm-là-chạy; `qctool all` một lệnh cả pipeline
---

# qc-tool — Tracking Index

Điểm vào của bộ tracking. Đọc [`README.md`](README.md) trước khi sửa bất cứ thứ gì.

## 1. Tiến độ milestone

```
M01 Ingest & Requirement model      ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓░░░░░  78%   In progress
M02 Generate + validator + render   ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓░░░░░░  73%   In progress
M03 Renderer theo template          ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓░░░  85%   In progress
M04 Execute + evidence              ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓░░░░  80%   In progress
M05 Report & traceability           ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓░░░░░░  70%   In progress
M06 UI adapter + UI map             ░░░░░░░░░░░░░░░░░░░░░░   0%   Planned
M07 Feedback loop                   ░░░░░░░░░░░░░░░░░░░░░░   0%   Planned
```

`▓ = đã làm   ░ = còn lại`

**Tổng: 0/7 milestone xong (0%)** — pipeline chạy end-to-end, nhưng chưa milestone nào đủ DoD
(chưa chạy trên môi trường thật, chưa có traceability matrix).
**Chặn hiện tại:** chưa có. D2 (spec thật) sẽ nâng chất lượng sinh case.

Chi tiết: [`milestones.md`](milestones.md)

## 2. Theo tuần

| Kỳ | Từ → đến | Milestone xong | Việc đáng chú ý |
|---|---|---|---|
| 2026-W38 | 09-14 → 09-20 | — | Chốt bài toán + kiến trúc; dựng 3 template; **tool dùng được** — `qctool serve` mở giao diện web, bấm là chạy; sinh 54 case, chạy trên mock API, bắt 3/4 bug cài sẵn, xuất báo cáo + điền kết quả vào Excel |

## 3. Chờ quyết định

Chi tiết ở [`todo.md`](todo.md) §1:

| # | Việc | Chặn | Trạng thái |
|---|---|---|---|
| D2 | Spec OpenAPI thật | M04 | **chờ** — anh xác nhận sẽ cấp sau khi tool ra hình hài |
| D1 | File template testcase thật | ~~M03~~ | ✅ chốt — anh cấp mỗi lần dùng; đã có template 14 cột |
| D3 | Tài khoản test | ~~M04~~ | ✅ chốt — dùng account thật, để trong `.env` gitignored |
| D4 | Ngôn ngữ output | ~~M03, M05~~ | ✅ chốt — tiếng Việt, ngôn ngữ đơn giản |
| D5 | Phạm vi ingest | ~~M01~~ | ✅ chốt — chỉ `.md` |

## 4. Template & dữ liệu mẫu

| Loại | File | Trạng thái |
|---|---|---|
| Testcase (14 cột) | `templates/testcase/testcase-template.xlsx` | ✅ sinh bởi `scripts/build_testcase_template.py` |
| OpenAPI | `templates/api/openapi-template.yaml` | ✅ điền sẵn 3 operation thật của login-sso |
| Báo cáo | `templates/report/report-template.md` | ✅ kèm ví dụ đã điền |
| **Sample OpenAPI (hư cấu)** | `samples/openapi/task-manager-sample.yaml` | 7 endpoint, để dev/test — **không phải hệ thống thật** |

## 5. Tài liệu dự án

| File | Là gì |
|---|---|
| [`../brainstorms/2026-09-18-qc-automation-tool.md`](../brainstorms/2026-09-18-qc-automation-tool.md) | Brainstorm & thiết kế — bài toán, input contract, kiến trúc 5 chặng, map 14 field template, pilot login-sso |
| [`../findings/2026-09-18-login-sso-doc-review.md`](../findings/2026-09-18-login-sso-doc-review.md) | 10 phát hiện khi rà SRS/URD login-sso (P1–P10) |
| [`../../AGENTS.md`](../../AGENTS.md) | Kiến trúc, lệnh, quy tắc |

## 6. Cách dùng

| Câu hỏi | Đọc |
|---|---|
| "Dự án đang ở đâu?" | file này, Mục 1 + [`milestones.md`](milestones.md) |
| "Còn gì chưa xong?" | [`todo.md`](todo.md) §1 + §2 |
| "Sao lại thiết kế thế này?" | [`../brainstorms/2026-09-18-qc-automation-tool.md`](../brainstorms/2026-09-18-qc-automation-tool.md) §5 |
| "Chạy thử thế nào?" | `AGENTS.md` §Lệnh |
| "Template nằm ở đâu?" | Mục 4 ở trên |
