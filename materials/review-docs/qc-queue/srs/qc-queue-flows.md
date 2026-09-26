---
type: srs-flows
feature: qc-queue
updated: 2026-09-25
---

# QC Review Queue — Flows

## Flow: QC review open from queue (Sequence)

```mermaid
sequenceDiagram
    participant U as User
    participant FE as QCQueue.tsx mode=final_qc
    participant API as Backend

    U->>FE: Trigger — QC review open from queue
    FE->>API: GET /api/v1/qc/queue
    API-->>FE: 200
    FE-->>U: Update UI
```

## Flow: Gán hàng loạt (multi-reviewer + chọn nhanh theo nhóm)

```mermaid
sequenceDiagram
    actor Lead as QC Lead
    participant FE as QCQueue.tsx + QCQueueBulkAssignDialog.tsx
    participant QC as FastAPI features/qc
    participant AD as FastAPI features/admin

    Lead->>FE: Tick nhiều dòng trên trang hiện tại
    FE->>QC: GET /api/v1/qc/auto-assign/reviewers
    QC-->>FE: reviewer[] (id, username, full_name, groups)
    opt Chọn nhanh theo nhóm
        FE->>AD: GET /api/v1/admin/users/groups
        AD-->>FE: nhóm[] (name, member_count, created_at)
        Lead->>FE: Chọn 1 nhóm
        FE->>AD: GET /api/v1/admin/users/groups/{name}/members
        AD-->>FE: thành viên nhóm[]
        FE->>FE: tick các reviewer khớp thành viên
    end
    opt Tạo nhóm nhanh (chỉ khi có user:manage)
        FE->>AD: POST /api/v1/admin/users/groups
        FE->>AD: PUT /api/v1/admin/users/groups/{name}/members
        AD-->>FE: 200
    end
    Lead->>FE: Bấm "Xác nhận gán"
    alt 1 reviewer
        FE->>QC: POST /api/v1/qc/queue/assign {item_ids, assignee_*}
    else ≥2 reviewer (chia cân bằng theo thời lượng, sửa tay từng dòng)
        FE->>QC: POST /api/v1/qc/queue/assign {assignments[]}
    end
    QC-->>FE: 200 {updated, skipped, assignee_breakdown}
    FE-->>Lead: Toast kết quả + clear selection
```

## Flow: Chọn và xuất trên màn Queue (một thanh chọn hợp nhất)

Không còn chế độ chọn để xuất: `assignSelected` là tập chọn duy nhất, checkbox cột luôn tác động lên nó. `QCQueueSelectionBar` chỉ render khi `assignSelected.size > 0` và mang cả 2 nhóm hành động (Gán / Xuất) — nên "bật chế độ xuất" không còn tồn tại như một trạng thái.

```mermaid
stateDiagram-v2
    [*] --> ChuaChon
    ChuaChon: assignSelected rỗng — không có thanh chọn
    DaChon: assignSelected.size > 0 — QCQueueSelectionBar hiện
    ChuaChon --> DaChon: tick ít nhất 1 dòng
    DaChon --> ChuaChon: bấm Hủy / clearSelection()
    DaChon --> ChuaChon: đổi filter / reset effect
```

- Ở `ChuaChon`: không tick dòng nào → `QCQueueSelectionBar` không render, và banner "chọn hết" cũng không hiện.
- Ở `DaChon`: thanh chọn hiện badge "Đã chọn {N} mục" + **Phân công** (gate `qc:assign`) + **Xuất theo lựa chọn** / **Xuất tất cả {M} mục khớp lọc** (gate `qc:result:export`) + **Hủy**; tick hết trang thì banner chọn-theo-lọc hiện thêm.
- Reset khi đổi filter là **một chiều** (đổi trang thì lựa chọn được giữ nguyên) — sau reset phải tick lại từ đầu; effect `selectionResetKey` cũng xoá `assignOpen` và `dismissSelectAllBanner`.



