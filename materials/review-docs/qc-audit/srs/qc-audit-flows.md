---
type: srs-flows
feature: qc-audit
updated: 2026-09-25
---

# QC Audit — Flows

## Flow: Audit vòng QC thứ 2 (Activity)

**Trigger:** Reviewer vòng 1 chấm xong một item (Pass hoặc Reject)

**Related US:** US-001, US-002, US-003, US-004

```mermaid
flowchart TB
    start([Data qua các bước xử lý dữ liệu]) --> queue1[Vào hàng đợi QC Review vòng 1]
    queue1 --> review1[Reviewer vòng 1 chấm item]
    review1 --> d1{Quyết định vòng 1}
    d1 -->|Passed| toAudit[Chuyển sang hàng đợi Audit]
    d1 -->|Rejected| toAudit
    toAudit --> d2{Auditor có phải<br/>người đã review vòng 1?}
    d2 -->|Đúng| hidden[Ẩn item khỏi hàng đợi<br/>của người đó]
    d2 -->|Không| pick[Auditor tự lấy item<br/>hệ thống không khóa]
    hidden --> otherAuditor[Auditor khác lấy item]
    otherAuditor --> viewR1
    pick --> viewR1[Xem kết quả vòng 1:<br/>quyết định + lý do + người review]
    viewR1 --> assess[Soát theo checklist dùng chung<br/>chế độ chỉ xem, không sửa dữ liệu]
    assess --> d3{Quyết định Audit<br/>QUYẾT ĐỊNH CUỐI CÙNG}
    d3 -->|Pass| warehouse[/Chuyển sang Warehousing<br/>module Delivery/]
    d3 -->|Reject| d4{Đã chọn mã lý do?}
    d4 -->|Chưa| errReason[Nút xác nhận bị vô hiệu hoá<br/>không gửi]
    errReason --> assess
    d4 -->|Rồi| logReject[Ghi nhận Audit Reject<br/>kèm mã lý do + ghi chú]
    logReject --> reprocess[Phát yêu cầu chạy lại toàn bộ<br/>các bước xử lý dữ liệu]
    reprocess --> queue1
    warehouse --> done([Kết thúc — data được bàn giao])
```

**Ghi chú nghiệp vụ:**

- Cả hai nhánh của vòng 1 (`Passed` và `Rejected`) đều vào hàng đợi Audit — 100% item, không nhánh nào được bỏ qua.
- Kết quả cuối chỉ phụ thuộc quyết định Audit. Vòng 1 `Rejected` + Audit `Pass` vẫn đi Warehousing — đây là đường cứu data bị loại oan.
- Vòng lặp `reprocess → queue1` không giới hạn số vòng ở phase này. Đây là quyết định có ý thức; điểm dừng để phase sau.
- **Vòng lặp đó hiện chưa khép kín trong code**: portal phát yêu cầu xử lý lại (`reprocess_status='requested'`, outbox + Kafka `qc.audit.reprocess_requested`) nhưng chưa có cơ chế nhận kết quả để `complete_audit_reprocess` đưa item về `pending`. Item đã bị reject hiện nằm ở `audit_rejected` cho tới khi có callback.
- **Tranh chấp hai auditor**: nhánh 409 có trong code nhưng khó chạy trên thực tế vì bước tra item đã lọc `status='pending_audit'` — item bị người khác chấm xong sẽ rơi vào 404. Xem ghi chú ở F-03 mục B của SRS.
- Màn chấm Audit hiện **chưa render checklist tiêu chí**; bộ tiêu chí vẫn nằm trong khối review vòng 1 mà API trả về (`review.criteria`).
- Warehousing là ranh giới ngoài phạm vi của sub-module Audit — phía Delivery nay có kho thật (`portal_warehouse_items`), màn `/warehousing` đọc `GET /api/v1/warehousing/items`; endpoint `GET /api/v1/delivery/warehousing/mock-items` cũ chỉ còn phục vụ bộ chọn item của đơn giao hàng.

## Flow: Load Audit Queue (Sequence)

**Trigger:** Auditor mở `/qc/audit`

**Related FR:** F-01

```mermaid
sequenceDiagram
    participant A as Auditor
    participant FE as AuditQueue.tsx
    participant API as FastAPI /api/v1/qc/audit
    participant DB as PostgreSQL

    A->>FE: Mở /qc/audit
    FE->>API: GET /queue?page&limit&round1_decision&project_id&q&created_from&created_to
    API->>API: require_permission(qc:audit:perform)
    API->>DB: SELECT qc_queue_items WHERE status = 'pending_audit'
    API->>DB: JOIN qc_reviews (quyết định + lý do + reviewer vòng 1)
    API->>API: Loại item có qc_reviews.reviewer_id = current_user.id
    Note over API: Luật tách vai — lọc ở tầng truy vấn,<br/>không lọc ở frontend.<br/>Auditor dùng pool chung mọi project,<br/>không giới hạn theo người được giao.
    DB-->>API: rows + total
    API-->>FE: 200 AuditQueueListResponse
    alt total = 0
        FE-->>A: Trạng thái rỗng "Không có item chờ audit"
    else total > 0
        FE-->>A: Bảng hàng đợi kèm cột QC1 / Reviewer / Vào audit
    end
```

## Flow: Submit Audit Decision (Sequence)

**Trigger:** Auditor bấm Pass, hoặc bấm Reject và xác nhận trong hộp thoại

**Related FR:** F-03, F-05, F-06

```mermaid
sequenceDiagram
    participant A as Auditor
    participant FE as AuditReviewDetail.tsx
    participant API as FastAPI /api/v1/qc/audit
    participant DB as PostgreSQL
    participant OB as Iceberg outbox
    participant PR as Pipeline xử lý dữ liệu

    A->>FE: Bấm Pass hoặc Reject
    opt decision = reject
        FE->>A: Mở hộp thoại chọn mã lý do (OTS GoPro: checkbox 6 mã — còn lại: radio 1 mã)
        A->>FE: Chọn lý do + ghi chú
        alt chưa chọn lý do
            FE-->>A: Nút xác nhận bị vô hiệu hoá, không gọi API
        end
    end
    FE->>API: POST /queue/{item_id}/submit {decision, reason, comment}
    API->>API: require_permission(qc:audit:perform)
    API->>DB: SELECT qc_queue_items FOR UPDATE
    alt item không còn trong hàng đợi hiển thị
        API-->>FE: 404 (thực tế) / 409 (nhánh có sẵn) — xem ghi chú F-03
        FE-->>A: "Item vừa được người khác chấm. Đang làm mới danh sách." (chỉ khi 409)
    else status = 'pending_audit'
        API->>DB: Kiểm tra qc_reviews.reviewer_id khác current_user.id
        alt trùng người review vòng 1
            API-->>FE: 403 vi phạm luật tách vai
        else hợp lệ
            API->>DB: INSERT qc_audit_reviews (decision, reason_code, notes,<br/>auditor_id, round_no, round1_revision, round1_reviewer_id)
            alt decision = pass
                API->>DB: _autofill_delivery_on_pass (delivery_overrides)
                API->>DB: UPDATE qc_queue_items SET status='audit_passed'
            else decision = reject
                API->>DB: UPDATE qc_queue_items SET status='audit_rejected',<br/>reprocess_status='requested'
                API->>PR: Phát yêu cầu chạy lại các bước xử lý dữ liệu<br/>(outbox + Kafka qc.audit.reprocess_requested)
                Note over PR,DB: Chưa có callback đưa item về 'pending' —<br/>xem F-06
            end
            API->>OB: enqueue audit_decision event
            API->>DB: COMMIT
            API-->>FE: 200 AuditSubmitResponse
            FE-->>A: Thông báo kết quả, quay về hàng đợi
        end
    end
```
