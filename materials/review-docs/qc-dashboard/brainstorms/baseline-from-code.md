---
title: QC Dashboard — baseline từ code hiện có
feature: qc-dashboard
idea-slug: baseline-from-code
mode: deep
owner: "@cursor-agent"
updated: 2026-09-05
tags: [brainstorm, qc, dashboard, auto-assign]
changelog:
  - 2026-09-05 | /brainstorm | Viết lại từ QCDashboard.tsx + AutoAssignRulesPanel + qc router dashboard/auto-assign
---

# Brainstorm — QC Dashboard

## 1. Tổng quan

**QC Dashboard** tổng hợp workload hàng đợi QC theo giờ video (hours), hiển thị tile theo status, pie chart phân bổ, **My Queue** (4 item gần nhất của user), analytics cohort nâng cao, và panel **Auto-assign rules** cho QC Lead.

Biến thể **Annotation Dashboard** (`mode=annotation`) dùng `manual_annotation_only=true` và ẩn auto-assign panel.

## 2. Users & P0

| Role | P0 capabilities |
|------|-----------------|
| QC Lead | Xem dashboard, analytics, cấu hình + chạy auto-assign |
| Reviewer | Xem dashboard scoped; my queue; mở review |
| Admin | `dashboard:qc:view` + full scope |

## 3. Core flows

### 3.1 Load dashboard

1. User mở `/qc/dashboard`.
2. FE `useQcDashboard("qc")` → `GET /qc/dashboard?include_analytics=true` (hoặc split analytics endpoint).
3. Render 5 stat tiles (totalRaw, pending, in_review, passed, rejected) — values in **hours**.
4. Pie chart queue summary by status hours.
5. My Queue list max 4 items → click review.

### 3.2 Auto-assign

1. Lead bật **Enabled** → `PUT /qc/auto-assign/rules`.
2. Chọn strategy: round_robin | least_loaded | by_project.
3. Chọn reviewers, max queue/reviewer (1–50, default 12), high-priority flag.
4. **Run now** → `POST /qc/auto-assign/run` — assign unassigned pending items.
5. **Reassign now** → `POST /qc/auto-assign/reassign` — rebalance reassignable items.

## 4. Decision points

| ID | Condition | YES | NO |
|----|-----------|-----|-----|
| D-01 | `canAssign && !isAnnotation` | Show AutoAssignRulesPanel | Hide panel |
| D-02 | `rules.enabled` | Enable form controls | opacity-50 pointer-events-none |
| D-03 | `unassigned === 0` | Disable Run now | Enable |
| D-04 | `reviewerIds.length === 0` (non-null) | Disable run buttons | Allow |
| D-05 | Cache TTL > 0 | Serve cached dashboard stats | Compute live |

## 5. Strategies (auto_assign.py)

| Strategy | Behavior |
|----------|----------|
| least_loaded | Assign to reviewer with fewest open items |
| round_robin | Rotate eligible reviewers; persist `round_robin_index` |
| by_project | Prefer reviewer already assigned same project |

## 6. Limits

| Rule | Value |
|------|-------|
| my_queue slice | 4 items (`dashboard()` service) |
| max_queue_per_reviewer | 1–50 (API), default 12 |
| Dashboard cache TTL | `qc_dashboard_cache_ttl_seconds` |
| Default auto-assign | enabled=false, strategy=least_loaded |

## 7. Wording (i18n)

| Key | VI intent |
|-----|-----------|
| auto_assign_run_toast | Đã chạy auto-assign |
| auto_assign_run_failed | Chạy auto-assign thất bại |
| no_items_assigned | Không có mục được gán cho bạn |
| no_queue_data | Không có dữ liệu hàng đợi |

## 8. Risks

| Risk | Mitigation |
|------|------------|
| Stale dashboard cache | TTL config; invalidate on assign |
| Auto-assign overload reviewer | max_queue_per_reviewer cap |

## 9. API inventory

| Method | Path | Permission |
|--------|------|------------|
| GET | `/api/v1/qc/dashboard` | `dashboard:qc:view` |
| GET | `/api/v1/qc/dashboard/analytics` | `dashboard:qc:view` |
| GET | `/api/v1/qc/annotation-dashboard` | `qc:queue:view` |
| GET/PUT | `/api/v1/qc/auto-assign/rules` | `qc:assign` |
| GET | `/api/v1/qc/auto-assign/reviewers` | `qc:assign` |
| GET | `/api/v1/qc/auto-assign/stats` | `qc:assign` |
| POST | `/api/v1/qc/auto-assign/run` | `qc:assign` |
| POST | `/api/v1/qc/auto-assign/reassign` | `qc:assign` |
