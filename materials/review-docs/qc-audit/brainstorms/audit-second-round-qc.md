---
type: brainstorm
feature: review/qc-audit
idea_slug: audit-second-round-qc
status: draft
mode: deep
lang: vi
owner: binhhm
created: 2026-09-08
updated: 2026-09-25
last_modified_by: binhhm
complexity_flags: [has_state_machine, has_multi_role, has_async_flow]
links:
  - backend/app/features/qc/review_store.py
  - backend/app/features/qc/audit_store.py
  - backend/app/features/qc/ingestion_mapper.py
  - backend/app/features/auth/permission_bundles.py
  - docs/review/qc-queue/urd.md
  - docs/delivery/warehousing
  - docs/annotation/annotation-review-detail/brainstorms/frozen-keep-segments-on-rejection.md
  - docs/notes/2026-09-23-end-to-end-flow-audit.md
tags: [brainstorm, qc-audit, qc-review-module]
stale_reason: ""
changelog:
  - 2026-09-25 | /brainstorm | **định tuyến từ chối bị lật ngược theo chốt PO 2026-09-23** — sửa Mục 1, 4 (P0), 5.1, 6.1, 6.2, 6.3, 6.4, 8, 10, 11: Audit **chỉ** nhận item vòng 1 **Pass**; cả Review Reject lẫn Audit Reject đều về **Annotation** (không qua hàng đợi QC Review vòng 1); thêm OQ-7 về đóng băng keep segment
  - 2026-09-11 | /docs-sync | đối chiếu code: chốt tên quyền/nhóm (OQ-4), chốt hàng đợi không giao việc (OQ-5), ghi nhận vòng lặp reprocess chưa khép kín
  - 2026-09-08 | /urd | cascade OQ-1 (chặn cứng tự audit) + OQ-2 (không giới hạn vòng lặp): cập nhật Mục 4, 6.3, 6.4, 6.5, 7.2, 8, 9, 11
  - 2026-09-08 | /brainstorm | initial brainstorm — Audit vòng QC thứ 2 trong module Review, deep mode, 5 OQs
---

# Audit — vòng QC thứ 2 trong module Review

> Feature: review/qc-audit | Idea: audit-second-round-qc
> 1 feature có thể có nhiều brainstorm — đây là 1 idea/draft độc lập.

## 1. Idea Seed

Xây sub-module "Audit" nằm trong module "Review". Sub-module này làm tương tự QC Review nhưng luồng dữ liệu khác một chút: item **đã Pass ở QC Review** đi tiếp qua Audit để soát lại lần hai trước khi bàn giao. Đây là vòng QC thứ hai.

> **Cập nhật 2026-09-25 — phần "Idea Seed" giữ nguyên nguyên văn làm dấu vết lịch sử.** Ý tưởng ban đầu (2026-09-08) là đưa **100% item**, kể cả nhánh Rejected, vào Audit. Chốt PO 2026-09-23 đã **lật ngược** điểm này — xem Mục 2.1 bên dưới. Toàn bộ các mục từ 4 trở đi trong tài liệu này đã được sửa theo chốt mới.

## 2. Context

**Vì sao cần vòng 2.** Trước khi có Audit, QC Review chỉ có một vòng duy nhất. Reviewer chấm xong là kết quả có hiệu lực ngay — item Pass được đẩy thẳng xuống bàn giao. Điều này tạo ra ba vấn đề nghiệp vụ mà PO muốn xử lý:
1. **Hàng lỗi lọt xuống bàn giao (false pass)** — reviewer chấm Pass nhầm, data lỗi đi tiếp xuống delivery, khách phát hiện và trả về.
2. **Data tốt bị loại oan (false reject)** — reviewer reject nhầm, mất data đã tốn chi phí thu thập, không có cơ chế nào cứu lại.
3. **Không đo được chất lượng người review** — không có nguồn dữ liệu độc lập nào để biết reviewer nào chấm chính xác, reviewer nào hay sai.

**Ai yêu cầu.** PO. Chưa có mốc thời gian cứng.

**Liên quan tới phần đã có.** Sub-module này nằm cùng module với `qc-queue`, `qc-dashboard`, `qc-checklists`, `qc-review-detail-*`. Điểm ra của Audit nối vào `docs/delivery/warehousing` (module Delivery) — brainstorm này dừng ở ranh giới đó theo yêu cầu, không phân tích sâu hơn về Warehousing.

### 2.1 Chốt PO 2026-09-23 — định tuyến từ chối (lật ngược ý tưởng ban đầu)

Quyết định PO ngày **2026-09-23 15:12 GMT+7** (ghi ở `docs/notes/2026-09-23-end-to-end-flow-audit.md` câu 1 và 8):

| # | Câu hỏi | Chốt |
|---|---|---|
| 1 | Review Reject → Annotation ngay, hay qua Audit? | **Annotation ngay** — không đưa Review FAIL qua Audit. Audit **chỉ** cho item đã Review PASS |
| 8 | Segment hay video ở Review/Audit? | Mỗi dòng menu QC Review/Audit là **segment** (cắt từ video project), không phải full video. Workflow cha vẫn theo `uuidv7` |

**Hai hệ quả lật ngược so với brainstorm này (bản 2026-09-08):**

1. **Audit không còn nhận 100% item vòng 1.** Chỉ nhánh vòng 1 **Pass** mới vào hàng đợi Audit. Nhánh vòng 1 **Reject** đi thẳng về Annotation theo trạng thái `needs_revision`.
2. **Audit Reject cũng đi thẳng về Annotation**, không quay về hàng đợi QC Review vòng 1. Cả hai nhánh từ chối đều đổ về Annotation để annotator sửa, rồi vào lại QC Review vòng 1 → QC Audit vòng 2.

Vì vậy luồng đúng hiện nay là **một vòng lặp qua Annotation**, không phải hai đường vòng độc lập như Mục 5.1 bản cũ mô tả.

**Hệ quả lên cơ chế "Audit ghi đè vòng 1".** Ý tưởng "vòng 1 Rejected + Audit Pass thì data vẫn đi Warehousing" **không còn áp dụng** — trường hợp đó không thể xảy ra nữa vì item bị vòng 1 Reject không bao giờ tới được Audit. Việc "cứu data bị loại oan" nay diễn ra ở một chỗ khác: annotator sửa lại ở Annotation rồi đi qua cả hai vòng chấm mới.

**Hệ quả lên mục tiêu "đo chất lượng reviewer".** Vẫn giữ được, nhưng cách đọc số liệu khác đi: không còn đo được bằng "tỉ lệ Audit lật quyết định của vòng 1" cho nhóm item vòng 1 Reject, vì nhóm đó không tới Audit.

> **Còn lệch tài liệu:** `docs/review/qc-audit/urd.md` và `srs/*` (tài liệu BA của chính feature này) **vẫn còn** mô tả "Audit nhận 100% item vòng 1 kể cả Rejected" và "Audit Reject quay về hàng đợi QC Review vòng 1". Việc sửa các file đó nằm ngoài phạm vi brainstorm — đang theo dõi ở `docs/_sync/SYNC-2026-09-25-001.md` dưới mã **OQ-9**, cần một `/cr` riêng.

## 3. User Types (preliminary)

| User Type | Pain Point | Primary Need |
|-----------|-----------|--------------|
| Auditor (nhóm quyền mới, tách khỏi reviewer) | Không có nơi nào để soát lại **item đã được vòng 1 cho đạt** trước khi data đi ra ngoài | Một hàng đợi riêng chứa item **đã Pass vòng 1**, xem được vòng 1 chấm gì và tự chấm lại |
| Reviewer vòng 1 (`vd-qc-reviewers`) | Chấm xong không biết mình đúng hay sai, không có phản hồi để sửa | Xem được kết quả Audit của item mình đã chấm, kèm lý do, để tự rút kinh nghiệm — **chưa triển khai**, xem 5.2 |
| QC Lead (`vd-qc-leads`) | Không biết chất lượng từng reviewer ra sao, không có căn cứ để phân công hay kèm cặp | Nguồn dữ liệu đối chiếu 2 vòng (phase này mới lưu dữ liệu, màn báo cáo để phase sau) |
| Annotator | Video bị từ chối ở **cả hai vòng** đều quay về màn của họ để sửa | Biết chính xác segment nào bị bắt lỗi, và không vô tình sửa hỏng phần đã được chấp nhận — xem Mục 6.6 |

## 4. Capabilities Breakdown

### P0 — must have

- Hàng đợi Audit dạng danh sách, nằm ở mục menu "Audit QC" trong nhóm "Đánh giá" của module Review.
- Nhận item **đã Pass ở vòng 1**. Nhánh vòng 1 Reject **không** vào Audit — đi thẳng về Annotation (chốt PO 2026-09-23; xem Mục 2.1).
- Màn chấm Audit hiển thị đầy đủ kết quả vòng 1: quyết định, lý do, tên người review.
- Auditor chấm Pass / Reject theo bộ tiêu chí dùng chung với QC Review.
- Reject bắt buộc chọn mã lý do; ghi chú tùy chọn.
- Audit Pass đẩy data sang Warehousing (module Delivery).
- Audit Reject đẩy item chạy lại toàn bộ các bước xử lý dữ liệu rồi **quay về Annotation** để annotator sửa — **không** quay về hàng đợi QC Review vòng 1 (chốt PO 2026-09-23).
- Lưu lịch sử Audit (ai chấm, chấm gì, khi nào, lý do) để reviewer vòng 1 và Lead xem được.
- Nhóm quyền riêng cho auditor, tách khỏi quyền QC Review vòng 1.
- Chặn cứng auditor chấm chính item mình đã review ở vòng 1 — hệ thống ẩn item đó khỏi hàng đợi Audit của người đó.

### P1 — should have

- Giới hạn số vòng lặp reject để item không chạy vòng vô hạn — **đã chốt không làm ở phase này**, xem Mục 8.
- Bộ lọc / tìm kiếm trên hàng đợi Audit tương đương QC Queue hiện có — đã làm (tìm kiếm, lọc kết quả vòng 1, lọc project, khoảng ngày).

### P2 — nice to have

- Cơ chế lấy mẫu theo lô: chỉ audit một phần data, kết quả đại diện cho cả lô (**đã chốt hoãn sang phase sau**, xem Mục 8).
- Màn thống kê Audit: tỉ lệ lật quyết định, độ chính xác từng reviewer, nhóm lỗi hay gặp (**đã chốt hoãn sang phase sau**).

> P0/P1/P2 là tentative; final scope chốt ở `/prd review/qc-audit`.

## 5. Core Flows (Happy Path)

### 5.1 Luồng Audit đầy đủ (từ vòng 1 đến điểm ra)

1. Data đi qua các bước xử lý dữ liệu, vào hàng đợi QC Review.
2. Reviewer vòng 1 mở item, chấm Pass hoặc Reject.
3. **Nhánh Pass** → hệ thống chuyển item sang hàng đợi Audit. **Nhánh Reject** → item đi thẳng về Annotation ở trạng thái cần sửa, **không** vào Audit (chốt PO 2026-09-23).
4. Auditor mở menu "Audit", thấy danh sách item đang chờ, tự lấy item để chấm. Hệ thống không khóa item.
5. Màn chấm hiển thị: nội dung cần soát, và kết quả vòng 1 gồm quyết định, lý do, tên người review. Auditor chỉ xem, không sửa được dữ liệu.
6. Auditor chấm theo bộ tiêu chí dùng chung với QC Review, rồi bấm Pass hoặc Reject.
7. Nếu **Pass** — item được đánh dấu đạt, data chuyển sang Warehousing (module Delivery). Kết thúc luồng.
8. Nếu **Reject** — auditor bắt buộc chọn mã lý do (ghi chú tùy chọn). Item được đẩy chạy lại toàn bộ các bước xử lý dữ liệu, sau đó **quay về Annotation** để annotator sửa; sửa xong item vào lại **QC Review vòng 1** rồi **QC Audit vòng 2** (không rẽ nhánh mới).
9. Hệ thống lưu lịch sử Audit. Không gửi thông báo cho bất kỳ ai.

```
     [Các bước xử lý dữ liệu]
                │
                ▼
   ┌────────────────────────┐
   │   Hàng đợi QC Review   │ ◀────────────────────────────┐
   │        (vòng 1)        │                              │
   └───────────┬────────────┘                              │
               │ Reviewer chấm                             │
               ▼                                           │
        ◇ Quyết định vòng 1 ◇                              │
         │                │                                │
      Passed           Rejected                            │
         │                │                                │
         │                └──────────────┐                 │
         │    CHỈ nhánh Pass vào Audit  │                 │
         ▼                               ▼                 │
   ┌────────────────┐        ┌──────────────────────┐      │
   │ Hàng đợi Audit │        │  Chạy lại các bước   │      │
   │ menu "Audit"   │        │  xử lý dữ liệu       │      │
   └───────┬────────┘        └──────────┬───────────┘      │
           │ Auditor tự lấy             │                  │
           │ • Thấy kết quả vòng 1      ▼                  │
           │ • Chỉ xem, KHÔNG sửa  ┌──────────────────┐    │
           │ • Checklist chung     │    ANNOTATION    │    │
           ▼                       │  annotator sửa   │────┘
    ◇ Quyết định Audit ◇          │  • segment bị lỗi mở │
     │                │           │  • keep đã đạt ĐÓNG  │
   Pass            Reject         │    BĂNG (xem 6.6)    │
     │                │           └──────────────────────┘
     │                │ bắt buộc          ▲
     │                │ mã lý do          │
     ▼                └───────────────────┘
┌─────────────────┐
│   Warehousing   │
│ (module         │
│  Delivery)      │
└─────────────────┘
```

**Điểm mấu chốt.** Nhánh vòng 1 Reject **không** đi qua Audit — cả hai nhánh từ chối (vòng 1 và vòng 2) đều đổ về **Annotation** để sửa, rồi đi lại từ đầu qua cả hai vòng chấm. Kết quả cuối cùng vẫn chỉ do quyết định Audit quyết định: item chỉ vào kho khi Audit Pass.

### 5.2 Luồng reviewer vòng 1 xem lại kết quả Audit

> **Chưa triển khai.** Code mới có endpoint lịch sử Audit `GET /api/v1/qc/audit/queue/{item_id}/history` bọc quyền `qc:audit:perform` — reviewer vòng 1 và QC Lead không có quyền này. Endpoint lịch sử cũ `/qc/queue/{item_id}/review-sessions` vẫn chỉ trả phiên vòng 1 và không được mở rộng.

1. Reviewer mở lịch sử của item mình đã chấm.
2. Hệ thống hiển thị kết quả Audit: quyết định, lý do, thời điểm.
3. Reviewer tự đối chiếu với quyết định của mình. Hệ thống không gửi thông báo, không yêu cầu reviewer phản hồi gì.

## 6. System Behavior Deep Dive

### 6.1 Decision Points

| ID | Flow | Khi nào | YES (nhánh đồng ý) | NO (nhánh từ chối) |
|---|---|---|---|---|
| D1 | 5.1 bước 3 | Item vừa có quyết định vòng 1 **Pass**? | Đưa vào hàng đợi Audit | Vòng 1 Reject → đưa về **Annotation** (`needs_revision`), không vào Audit |
| D2 | 5.1 bước 4 | Auditor có quyền vào sub-module Audit? | Hiện hàng đợi, cho lấy item | Ẩn menu "Audit" / báo không có quyền |
| D3 | 5.1 bước 6 | Auditor chấm Pass? | Đánh dấu đạt, chuyển Warehousing | Sang nhánh Reject tại D4 |
| D4 | 5.1 bước 8 | Auditor đã chọn mã lý do reject chưa? | Ghi nhận reject, đẩy xử lý lại | Chặn submit, yêu cầu chọn mã lý do |
| D5 | 5.1 bước 4 | Item đã được auditor khác chấm xong trước đó? | Báo item đã được chấm, không cho chấm lại | Cho chấm bình thường |
| D6 | 5.1 bước 8 | Xử lý lại xong? | Đưa item về **Annotation** ở vòng sửa lại | Item nằm ở `audit_rejected` — xem OQ-6 |

### 6.2 Scenario Matrix

Ma trận kết hợp quyết định 2 vòng. **Lưu ý:** tổ hợp "vòng 1 Rejected × Audit" **không còn tồn tại** sau chốt PO 2026-09-23 — item bị vòng 1 Reject không bao giờ tới được Audit.

| From State (vòng 1) | To State (Audit) | Rule | Action | Result |
|------------|----------|------|--------|--------|
| Passed | Pass | Hai vòng đồng thuận đạt | Chuyển Warehousing | Data được bàn giao |
| Passed | Reject | Audit lật quyết định — chặn được false pass | Đẩy chạy lại xử lý dữ liệu | Về **Annotation** để sửa → vào lại vòng 1 |
| Rejected | *(không tới Audit)* | Nhánh vòng 1 Reject đi thẳng về Annotation | Chạy lại xử lý dữ liệu (nếu cần) rồi đưa về Annotation | Annotator sửa → vào lại vòng 1 |

### 6.3 State Transitions

```
Item: Chờ QC Review → (Pass) → Chờ Audit → Đã audit (Pass) → Bàn giao Warehousing
        │                            ↘ Đã audit (Reject) → Xử lý lại → ANNOTATION (lặp)
        │
        └── (Reject) → ANNOTATION → sửa xong → Chờ QC Review (lặp)
```

| Entity | Từ | Sang | Trigger | Quay lại được? |
|--------|------|----|---------|-------------|
| Item | Chờ QC Review | Chờ Audit | Reviewer vòng 1 chấm **Pass** | không |
| Item | Chờ QC Review | **Annotation** (`needs_revision`) | Reviewer vòng 1 chấm **Reject** | có — annotator sửa xong vào lại vòng 1 |
| Item | Chờ Audit | Đã audit — Pass | Auditor chấm Pass | không |
| Item | Chờ Audit | Đã audit — Reject | Auditor chấm Reject kèm mã lý do | không |
| Item | Đã audit — Pass | Bàn giao Warehousing | Tự động ngay sau khi Audit Pass — trong code là mở cổng `_audit_gate_open` cho deliverable sync, **không** sinh thêm trạng thái item nào | không |
| Item | Đã audit — Reject | **Annotation** | Các bước xử lý dữ liệu chạy lại xong | **có — vòng lặp không giới hạn số vòng ở phase này (quyết định có ý thức)**. Lưu ý: hàm `complete_audit_reprocess` đã có nhưng chưa được nối vào luồng nào — xem OQ-6 |
| Segment (keep) | Đã đạt | Cần sửa + hạ thành cut | Vòng chấm sau từ chối chính segment đó | có — đây là **đường mở khoá duy nhất** của cơ chế đóng băng (xem 6.6) |

> Trạng thái `pending_audit`, `audit_passed`, `audit_rejected` đã có trong code. Trạng thái "Trong kho" không phải trạng thái của item ở portal — thuộc nghiệp vụ Delivery.

### 6.4 Interrupted Transactions

| Tình huống | Hệ thống còn lại gì | Resume | Cleanup |
|---|---|---|---|
| Auditor đóng trình duyệt giữa lúc đang chấm | Item vẫn ở trạng thái "Chờ Audit", chưa ghi nhận gì | Auditor (hoặc người khác) mở lại item, chấm từ đầu | Không cần — chưa có gì được ghi |
| Hai auditor cùng mở một item | Không khóa item, cả hai xem được | Người bấm chấm trước được tính; người sau nhận báo item đã được chấm (D5) | Không cần |
| Bước xử lý lại dữ liệu bị lỗi sau khi Audit reject | Item ở `audit_rejected` với `reprocess_status='requested'` (hoặc `'failed'` nếu hàm complete được gọi với `success=False`) | **Chưa có cơ chế resume**: `complete_audit_reprocess` không có caller, `reprocess_status='failed'` chỉ ghi log cảnh báo, item kẹt ở `audit_rejected` và không vai trò nào nhìn thấy trong hàng đợi | <!-- TBD: cần chốt callback từ pipeline và danh sách item kẹt --> |
| Item bị Audit reject nhiều lần liên tiếp | Mỗi vòng ghi một bản ghi `qc_audit_reviews` mới (khóa `uuidv7` + `round_no`), item quay về Annotation rồi vào lại vòng 1 | Lặp không giới hạn — đã chốt chấp nhận ở phase này | Theo dõi thủ công; nếu phát sinh item kẹt thì bổ sung điểm dừng ở phase sau |

### 6.5 Other Edge Cases

- **Hàng đợi Audit rỗng** — auditor mở menu "Audit QC" khi chưa có item nào chờ; màn hiện khối rỗng "Không có item chờ audit" + dòng mô tả, thanh lọc vẫn giữ.
- **Auditor tự audit item mình đã review vòng 1** — đã chốt chặn cứng: item do chính người đó chấm vòng 1 không xuất hiện trong hàng đợi Audit của họ. **Hành vi khi mở thẳng đường dẫn** (đã chốt trong code): `GET /qc/audit/queue/{id}/review` trả 404 vì item không nằm trong truy vấn hàng đợi hiển thị; `POST .../submit` trả 403 nếu item vẫn đang `pending_audit` và người gọi là reviewer vòng 1.
- **Item bị Audit reject trong lúc reviewer vòng 1 đang mở xem lại lịch sử** — reviewer thấy dữ liệu cũ cho tới khi tải lại màn.
- **Bộ tiêu chí (checklist) bị sửa giữa hai vòng** — vòng 1 chấm theo bản cũ, Audit chấm theo bản mới; hai vòng không cùng thang đo. Màn Audit hiện chưa render checklist nên rủi ro này chưa phát sinh trên UI. <!-- TBD: cần xác nhận có neo phiên bản checklist theo item không -->
- **Item cũ đã bàn giao trước khi có sub-module Audit** — không hồi tố, không kéo ngược vào hàng đợi Audit. Các dòng `status='passed'` legacy vẫn được `_audit_gate_open` cho đi tiếp.

### 6.6 Điểm đến của nhánh từ chối — Annotation và cơ chế đóng băng

> **Mục mới 2026-09-25.** Bổ sung theo chốt PO 2026-09-23 (cả hai nhánh từ chối đều về Annotation) và brainstorm [[docs/annotation/annotation-review-detail/brainstorms/frozen-keep-segments-on-rejection.md|frozen-keep-segments-on-rejection]].

Cả hai nhánh từ chối đều đổ về **màn Annotation**. Vì một video gồm **nhiều segment**, quay về cả video là quá thô — annotator không biết chỗ nào bị bắt lỗi và có thể sửa hỏng phần đã được chấp nhận. Cơ chế đóng băng khắc phục điều đó:

| Khái niệm | Nội dung |
|---|---|
| Đơn vị từ chối | Theo **từng segment**, không theo cả video — dữ liệu đưa vào Review/Audit là segment |
| Cái gì đóng băng | `keep` segment **đã được chấm đạt** ở lượt chấm gần nhất → xem được, không tương tác được |
| Cái gì không | `cut` segment và vùng chưa từng qua chấm |
| Keep bị từ chối | **Hạ xuống `cut`**, giữ khoảng thời gian + dữ liệu task; segment mở lại để sửa |
| Đường mở khoá | **Không có mở băng thủ công** cho bất kỳ vai trò nào. Chỉ vòng chấm sau từ chối chính segment đó |
| Field bàn giao | Đóng băng cùng keep segment, chỉ đọc suốt vòng sửa lại |
| Tập đóng băng | **Suy ra** mỗi lần mở màn từ kết quả chấm gần nhất, không lưu cứng vào segment |
| Số vòng | **Không giới hạn**; không thêm thông báo cho annotator |

**Hệ quả cho tài liệu này:**

- Hàng đợi Audit **không** chứa item vòng 1 Reject hay Audit Reject — cả hai đang ở vòng sửa lại trong màn Annotation.
- Vòng chấm kế tiếp sau khi annotator sửa: **QC Review vòng 1 → QC Audit vòng 2** như luồng cũ, không rẽ nhánh mới.
- Tài liệu đầy đủ về cơ chế: URD `US-016`, SRS `F-17` của feature `annotation/annotation-review-detail`.

> **Chưa có code.** "Trạng thái chấm ở cấp segment" là khái niệm mới; màn Annotation hiện **chưa có** nguồn dữ liệu kết quả chấm theo segment. Đây là **điểm nghẽn** — xem OQ-7.

## 7. Validation, Limits & Wording

### 7.1 Validation rules

| Field | Rule |
|---|---|
| Quyết định Audit | Bắt buộc, chỉ nhận một trong hai giá trị: Pass hoặc Reject (ràng buộc `pattern` ở schema) |
| Mã lý do reject | Bắt buộc ở giao diện khi Reject; không áp dụng khi Pass. Chọn từ danh mục dùng chung với QC Review. **Backend chưa cưỡng chế**: chỉ chặn khi reject mà thiếu cả lý do lẫn ghi chú (422), giá trị lý do không bị đối chiếu danh mục |
| Ghi chú | Tùy chọn ở cả hai nhánh Pass và Reject; gửi ở field `comment`. Không giới hạn độ dài ở backend |
| Dữ liệu nội dung (vùng làm mờ, metadata) | Chỉ đọc — auditor không sửa được ở phase này |

### 7.2 Limits & Quotas (exact values)

| Tham số | Giá trị | Window | Behavior khi vượt |
|---|---|---|---|
| Tỉ lệ item của một lô phải audit | 100% item **đã Pass vòng 1** của lô, không lấy mẫu | Mỗi lần chạy | Không áp dụng ở phase này |
| Số vòng lặp reject tối đa | Không giới hạn ở phase này | Theo vòng đời item | Không chặn — item tiếp tục quay vòng qua Annotation rồi vào lại vòng 1 |
| Ngưỡng % mẫu fail để reject cả lô | <!-- TBD: đã chốt là "có ngưỡng %" nhưng chưa chốt con số --> | Theo lô | Reject cả lô, đẩy xử lý lại — **chỉ áp dụng ở phase sau** |
| Thời gian giữ khóa item | Không áp dụng — hệ thống không khóa item | — | — |

> Phần lớn số liệu ở bảng này còn để trống vì cơ chế lấy mẫu theo lô đã được chốt hoãn sang phase sau (xem Mục 8). Phase này chạy 1:1 theo từng item nên không cần ngưỡng.

### 7.3 Wording samples (exact strings)

> **Bảng dưới là đề xuất ban đầu của skill.** Code đã chốt câu chữ khác ở một số chỗ — cột "Đã dùng trong code" ghi lại giá trị thực tế (khóa i18n trong `frontend/src/lib/i18n/vi.ts`).

#### Error messages

| Tình huống | Wording (đề xuất) | Code | Đã dùng trong code |
|---|---|---|---|
| Bấm Reject mà chưa chọn mã lý do | "Vui lòng chọn lý do không đạt trước khi gửi." | E-? | Không có câu chữ này — nút xác nhận chỉ bị vô hiệu hoá (`disabled`) |
| Item đã được auditor khác chấm xong | "Item này vừa được người khác chấm. Danh sách sẽ được làm mới." | E-? | "Item vừa được người khác chấm. Đang làm mới danh sách." (`audit_submit_stale`) |
| Không có quyền vào sub-module Audit | "Bạn không có quyền truy cập Audit." | E-? | Giữ nguyên (backend trả `detail` tiếng Việt cho 403) |
| Mất kết nối khi đang gửi kết quả | "Không gửi được kết quả do mất kết nối. Vui lòng thử lại." | E-? | "Không thể gửi quyết định audit." (`audit_submit_failed`) |

#### Success messages

| Tình huống | Wording (đề xuất) | Đã dùng trong code |
|---|---|---|
| Chấm Pass thành công | "Đã chấm đạt. Dữ liệu chuyển sang bàn giao." | "Đã ghi nhận audit pass." (`audit_submit_pass_ok`) |
| Chấm Reject thành công | "Đã chấm không đạt. Dữ liệu sẽ được xử lý lại." | "Đã ghi nhận audit reject — đã yêu cầu reprocess." (`audit_submit_reject_ok`) |

#### Info / neutral messages

| Tình huống | Wording (đề xuất) | Đã dùng trong code |
|---|---|---|
| Hàng đợi Audit rỗng | "Chưa có item nào chờ audit." | Tiêu đề "Không có item chờ audit" (`audit_queue_empty_title`) + mô tả "Sau khi reviewer submit QC vòng 1, item sẽ xuất hiện ở đây." (`audit_queue_empty_body`) |
| Nhãn khối hiển thị kết quả vòng 1 | "Kết quả QC Review (vòng 1)" | "QC vòng 1" (`audit_round1_title`) |
| Chú thích khi auditor không sửa được dữ liệu | "Chế độ chỉ xem — vòng audit không chỉnh sửa dữ liệu." | "Màn audit chỉ đọc" (`audit_readonly_hint`) |

## 8. Assumptions

- **Audit là chốt chặn cuối trước bàn giao.** Quyết định Audit là quyết định cuối cùng; không có vòng nào sau Audit trong phạm vi phase này.
- **Audit chỉ nhận item vòng 1 Pass** (chốt PO 2026-09-23 — xem Mục 2.1). Nhánh vòng 1 Reject đi thẳng về Annotation, không qua Audit. Vì vậy khái niệm "Audit ghi đè quyết định vòng 1" **không còn áp dụng** — không còn tổ hợp vòng 1 Reject × Audit Pass.
- **Cả hai nhánh từ chối đều quay về Annotation**, không về hàng đợi QC Review vòng 1 (chốt PO 2026-09-23). Đây là thay đổi so với bản brainstorm 2026-09-08.
- **Hành vi bàn giao hiện tại phải đổi.** Trước khi có Audit, `submit_review` gọi `_autofill_delivery_on_pass` ngay khi reviewer vòng 1 chấm Pass. Với Audit là chốt chặn cuối, việc đẩy bàn giao dời sang thời điểm Audit Pass. **Đã triển khai:** `submit_review` nay đặt `pending_audit` khi Pass và `needs_revision` khi Reject, `audit_store.submit_audit_decision` gọi `_autofill_delivery_on_pass` khi pass, và `_audit_gate_open` chặn deliverable sync ở `pending_audit`/`audit_rejected`.
- **Cơ chế lấy mẫu theo lô hoãn sang phase sau.** Ý tưởng là chỉ audit một phần data (ví dụ 1/10) và lấy kết quả đại diện cho cả lô. Hai điểm đã chốt cho phase đó: có ngưỡng phần trăm mẫu fail để reject cả lô, và lô bị reject sẽ được audit lại với mẫu mới. Định nghĩa "lô" chưa chốt (OQ-3). Phase này chạy 1:1 theo item.
- **Màn thống kê chất lượng reviewer hoãn sang phase sau.** Phase này chỉ lưu dữ liệu đối chiếu hai vòng.
- **Dùng lại bộ tiêu chí của QC Review**, không dựng danh mục tiêu chí riêng cho Audit. Lưu ý: API chi tiết Audit có trả `review.criteria` nhưng màn chấm hiện chưa render checklist.
- **Nhóm quyền auditor là nhóm mới trên SSO**, không tái sử dụng nhóm reviewer hay lead sẵn có. **Đã chốt:** nhóm `vd-qc-auditors`, quyền `qc:audit:perform`.
- **Vòng lặp reject không giới hạn ở phase này.** Đã cân nhắc và chấp nhận: item có thể chạy Review → Annotation → Review → Audit nhiều lần. Điểm dừng và đường thoát cho người quản lý để phase sau.
- **Đơn vị chấm là segment, không phải video** (chốt PO 2026-09-23). Từ chối chỉ đích danh segment lỗi; các segment còn lại của lượt đó mặc hiểu là đạt.
- **Keep segment đã đạt thì đóng băng khi video quay về Annotation** — xem Mục 6.6 và brainstorm `frozen-keep-segments-on-rejection`. Đây là cơ chế **chưa có code**, phụ thuộc vào việc bổ sung kết quả chấm ở cấp segment.
- **Không hồi tố** — item đã bàn giao trước khi có Audit không bị kéo ngược vào hàng đợi.

## 9. Risks

| Rủi ro | Khả năng | Hậu quả nghiệp vụ | Cách phòng |
|--------|----------|-------------------|-----------|
| Mục tiêu "đo chất lượng reviewer" không đạt ở phase này vì màn báo cáo bị hoãn | thường | PO kỳ vọng có số liệu chấm điểm reviewer nhưng phase 1 không giao được; dễ bị đánh giá là làm thiếu | Nói rõ với PO ngay từ đầu rằng phase 1 chỉ tích lũy dữ liệu; chốt mốc cho màn báo cáo ở phase sau |
| Auditor nhìn thấy kết quả vòng 1 trước khi chấm nên chấm theo quán tính | thường | Vòng 2 mất tính độc lập, tỉ lệ lật thấp giả tạo, false pass vẫn lọt | Theo dõi tỉ lệ lật quyết định; nếu quá thấp thì cân nhắc chuyển sang chấm độc lập rồi mới đối chiếu |
| Vòng lặp reject không có điểm dừng, item chạy đi chạy lại | thỉnh thoảng | Tốn chi phí xử lý dữ liệu lặp lại, item kẹt không bao giờ bàn giao được, trễ cam kết với khách | Đã chấp nhận rủi ro ở phase này; theo dõi item quay vòng nhiều lần và bổ sung điểm dừng ở phase sau nếu phát sinh thật |
| Đội auditor quá mỏng nên nhiều item bị treo vì luật chặn tự audit | thỉnh thoảng | Item tồn đọng ở hàng đợi Audit, trễ bàn giao | Ước lượng số auditor cần so với lượng item trước khi bật; cân nhắc cho Lead xử lý ca tồn đọng |
| Tên "Audit" trùng với hai thứ đã có: tab "Delivery Audit" trong màn QC Review Detail, và quyền `audit:view` của nhóm `vd-audit-viewers` | thường | Người dùng và cả đội phát triển hiểu nhầm phạm vi; cấp nhầm quyền cho người không phải auditor | **Đã xử lý (OQ-4):** menu "Audit QC", quyền `qc:audit:perform`, nhóm `vd-qc-auditors` — không trùng quyền/nhóm cũ |
| Không khóa item nên hai auditor có thể cùng chấm một item | thỉnh thoảng | Công auditor bị lãng phí, gây khó chịu khi bị báo "đã có người chấm" | Chấp nhận ở phase này; nếu đội đông thì bổ sung khóa mềm sau |
| Bộ tiêu chí bị sửa giữa hai vòng nên hai vòng không cùng thang đo | hiếm | Tranh cãi giữa reviewer và auditor về việc ai đúng; số liệu đối chiếu sai lệch | Neo phiên bản tiêu chí theo item, hoặc chỉ đổi tiêu chí tại thời điểm không có item đang treo |
| Thêm một vòng bắt buộc làm chậm thời gian data ra tới khách | thường | Trễ mốc bàn giao nếu số auditor không đủ so với lượng item | Ước lượng tải và số auditor cần trước khi bật; đây cũng chính là lý do phase sau cần lấy mẫu thay vì audit 100% |
| Đóng băng nhầm một keep segment thực ra có lỗi, mà không ai mở được | thỉnh thoảng | Annotator bị chặn ở chỗ không đáng chặn; dữ liệu sai vẫn đi tiếp; dễ sinh tranh cãi giữa annotator và reviewer | Ghi rõ đường thoát (vòng chấm sau từ chối chính segment đó) vào tài liệu hướng dẫn; tập huấn reviewer chọn đúng segment khi từ chối — xem OQ-7 |
| Nhánh Audit reject tắc ở `audit_rejected` vì bước xử lý lại chưa nối vào luồng nào | thường | Cơ chế đóng băng không có cơ hội chạy ở nhánh này; item không tự quay về Annotation được | Chốt phạm vi bước xử lý lại — xem OQ-6 |

## 10. Success Criteria (preliminary)

- Không còn hàng lỗi được bàn giao mà không qua vòng 2 — 100% item xuống Warehousing đều có bản ghi Audit Pass.
- ~~Tỉ lệ data bị loại oan được cứu lại: đo số item vòng 1 Reject nhưng Audit Pass~~ — **chỉ số này không còn đo được** sau chốt PO 2026-09-23, vì item vòng 1 Reject không tới Audit. Thay bằng: **tỉ lệ item quay về Annotation rồi qua được cả hai vòng ngay ở lần sửa đầu tiên**.
- Tỉ lệ khách trả data về giảm so với trước khi có Audit. <!-- TBD: cần số liệu nền hiện tại để đặt mục tiêu -->
- Thời gian trung bình từ lúc vào hàng đợi Audit đến lúc được chấm. <!-- TBD: chốt ngưỡng chấp nhận được -->
- **0 thao tác sửa thành công lên keep segment đã đóng băng** (đo bằng nhật ký thao tác) — từ brainstorm `frozen-keep-segments-on-rejection`.
- **Số segment phải sửa lại ở vòng sau giảm** so với trước khi có cơ chế đóng băng.

## 11. Open Questions

- [x] OQ-1: Người đã review vòng 1 có được audit chính item đó không? — **Đã chốt qua `/urd` (2026-09-08): chặn cứng.** Item do chính người đó chấm vòng 1 bị ẩn khỏi hàng đợi Audit của họ, không có ngoại lệ cho Lead.
- [x] OQ-2: Vòng lặp reject có giới hạn số vòng không? — **Đã chốt qua `/urd` (2026-09-08): không giới hạn ở phase này.** Chấp nhận rủi ro item quay vòng nhiều lần; điểm dừng để phase sau.
- [ ] OQ-3: "Lô" trong cơ chế lấy mẫu phase sau được hiểu là gì — cohort theo đợt dữ liệu về, theo project/đối tác, theo đơn bàn giao, hay theo phiên thu thập?
- [x] OQ-4: Tên hiển thị và tên nhóm quyền cho Audit là gì, để không trùng với tab "Delivery Audit" trong QC Review Detail và quyền `audit:view` của nhóm `vd-audit-viewers` đã có? — **Đã chốt trong code (2026-09-09):** menu "Audit QC", quyền `qc:audit:perform`, nhóm `vd-qc-auditors`. Tab "Delivery Audit" ở màn vòng 1 vẫn tên cũ, nhưng nằm khác màn nên không gây nhầm.
- [x] OQ-5: Hàng đợi Audit có dùng lại cơ chế phân công (giao việc thủ công và tự động) của QC Review không, hay chỉ để auditor tự lấy item? — **Đã chốt trong code:** chỉ auditor tự lấy item (OQ-5 trùng OQ-3 của URD); hàng đợi dùng pool chung mọi project, không có giao việc.
- [ ] OQ-6: Vòng lặp reprocess khi Audit reject đóng lại bằng cách nào — hiện `complete_audit_reprocess` chưa có caller nên item nằm ở `audit_rejected` vô thời hạn. **Trở nên cấp thiết hơn sau chốt PO 2026-09-23:** đích đến của nhánh này nay là Annotation, nên thiếu bước đó thì cơ chế đóng băng không bao giờ chạy được ở nhánh Audit.
- [ ] OQ-7: **Mới (2026-09-25).** Cơ chế đóng băng keep segment (Mục 6.6) phụ thuộc vào việc sinh **kết quả chấm ở cấp segment** — hiện màn Annotation chưa có nguồn dữ liệu này. Đây là điều kiện tiên quyết: chưa có nó thì không suy ra được tập đóng băng nào. Câu hỏi kèm theo: vòng chấm sau có phải chấm lại segment đang đóng băng không, hay mặc nhiên giữ kết quả đạt và chỉ chấm phần mới sửa? (Ảnh hưởng trực tiếp tới khối lượng việc của reviewer/auditor.) Các câu hỏi mở chi tiết hơn nằm ở brainstorm `frozen-keep-segments-on-rejection` Mục 11.

## 12. Next Steps

Sau brainstorm này (sau khi BA approve):
- `/urd review/qc-audit` — capture user perspective
- `/brd review/qc-audit` — business case
- `/prd review/qc-audit` — product scope

**Việc phải làm riêng (ngoài brainstorm này):**
- `/cr` cho mâu thuẫn tài liệu module Audit — `urd.md` + `srs/*` của chính feature này vẫn ghi "Audit nhận 100% item vòng 1 kể cả Rejected" và "Audit Reject quay về hàng đợi QC Review vòng 1", ngược chốt PO 2026-09-23. Đang theo dõi ở `docs/_sync/SYNC-2026-09-25-001.md` mã **OQ-9**.
- Sinh kết quả chấm ở **cấp segment** — điều kiện tiên quyết cho cơ chế đóng băng (OQ-7).

*KHÔNG nhảy thẳng SRS — qua PRD trước.*
