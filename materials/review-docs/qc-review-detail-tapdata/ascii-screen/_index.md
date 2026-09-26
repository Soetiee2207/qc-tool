---
type: screen-index
feature: "review/qc-review-detail-tapdata"
device: "desktop-1024"
owner: "Product Owner"
updated: "2026-09-25"
changelog:
  - "2026-09-25 | docs-sync | sidebar detail đổi sang 2 tab (Delivery Audit + Review History); Pass/Reject về queue, bỏ auto-next"
  - "2026-08-27 | /wireframe-ascii | initial screen tapdata-qc-review-detail — 1 video + Tapdata Delivery Audit 18 field"
  - "2026-08-27 | /wireframe-ascii | chốt final_result logic; minimum_video PASS/FAIL; task_description_map naming"
  - "2026-08-27 | /wireframe-ascii | PHẦN 1–3 read-only — bỏ dropdown/input editable"
---

# Tapdata QC Review — Wireframe (ASCII)

## Screens

| # | Screen slug | Tên màn | Thuộc luồng | Trạng thái | Cập nhật |
|---|-------------|---------|-------------|------------|----------|
| 1 | `tapdata-qc-review-detail` | Tapdata QC Review detail — 1 video + Delivery Audit | US-001/US-002/US-003 | draft | 2026-09-25 |

## Descriptions

### tapdata-qc-review-detail

Màn detail module Tapdata QC Review: sidebar trái 2 tab (**Tapdata Delivery Audit** mở mặc định — 18 field, 3 phần: Face & Hands editable, QC Auto read-only, QC Manual dropdown PASS/FAIL — và **Review History**), Preview **1 video** bên phải. Toolbar Pass/Reject/Back giữ nguyên QC Review egocentric. Delivery profile (`tapdata-iphone-std` / `tapdata-gopro-std`) hiển thị trên header.
