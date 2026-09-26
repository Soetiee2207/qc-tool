---
type: screen-index
feature: "review/qc-review-detail-scaleai-3cam"
device: "desktop-1024"
owner: "@binhhm"
updated: "2026-09-11"
changelog:
  - "2026-09-11 | /wireframe-ascii | đối chiếu code: toolbar thật (Back/filename/project/status chip/+N queue/toggle sidebar-dark-help/Reject-Pass); header panel Delivery Audit có dòng đếm trường thiếu; preview dùng 1 master timeline chung + toggle 'Xoay 2 cam cổ tay 180°'"
  - "2026-08-26 | /wireframe-ascii | initial 2 screens: qc-review-detail-3cam-audit, qc-review-detail-3cam-history; updated audit fields (partner_name/collector_id/schema_version/activity_tags) theo schema thật"
---

# QC Review — Wireframe (ASCII)

## Screens

| # | Screen slug | Tên màn | Thuộc luồng | Trạng thái | Cập nhật |
|---|-------------|---------|-------------|------------|----------|
| 1 | `qc-review-detail-3cam-audit` | QC Review detail — 3 camera, tab Audit mở | US-001/US-002 | draft | 2026-09-11 |
| 2 | `qc-review-detail-3cam-history` | QC Review detail — 3 camera, tab History mở | US-002 | draft | 2026-09-11 |

## Descriptions

### qc-review-detail-3cam-audit

Màn detail của item ScaleAI multicam (3 video) với sidebar tab Delivery Audit/Review History (tab Audit mở mặc định), panel Delivery Audit có header đếm trường thiếu, và Preview tam giác 3 camera (Head/trái/phải) dùng chung 1 thanh timeline.

### qc-review-detail-3cam-history

Cùng màn detail 3-camera, khác trạng thái: tab Review History đang mở, hiện danh sách các lần review trước; Preview giữ nguyên trạng thái phát không bị ảnh hưởng bởi việc chuyển tab.
