---
title: QC Checklists — baseline từ code hiện có
feature: qc-checklists
idea-slug: baseline-from-code
mode: deep
owner: "@cursor-agent"
updated: 2026-09-05
tags: [brainstorm, qc, checklist]
changelog:
  - 2026-09-05 | /brainstorm | Viết lại từ checklists/router.py + QCChecklists.tsx
---

# Brainstorm — QC Checklists

## 1. Tổng quan

**QC Checklists** cho phép QC Lead định nghĩa phiên bản checklist (tiêu chí pass/fail) dùng khi review video. Mỗi **version** có nhiều **criteria** (tên EN/VI, operator, expected, auto/manual). Chỉ **một version published** tại một thời điểm — version cũ archived khi publish mới.

## 2. User types

| Role | P0 |
|------|-----|
| QC Lead / Admin | List versions, edit criteria, publish |
| Reviewer | Đọc published criteria trong review (API `/published/criteria`) |
| PM | Xem options khi gắn checklist project (`/options`, `project:view`) |

## 3. Core Flows

### 3.1 Xem và chọn version

1. Lead mở `/qc/checklists`.
2. Sidebar liệt kê versions (version string, status chip, created_by, criteria_count).
3. Click version → load `GET /qc/checklists/{id}` → CriteriaBuilder.

### 3.2 Publish version

1. Lead chọn version draft → bấm **Publish**.
2. `PATCH /qc/checklists/{id}` `{ status: "published" }`.
3. Backend archive mọi published khác; invalidate Redis cache criteria.

### 3.3 Reviewer dùng checklist

1. Review detail gọi `GET /qc/checklists/published/criteria` (`qc:review:perform`).
2. Criteria render trong review UI (module khác).

## 4. Decision points

| ID | Khi nào | YES | NO |
|----|---------|-----|-----|
| D-01 | Publish version | Archive published cũ | — |
| D-02 | Create với status=published | Archive all published | — |
| D-03 | User thiếu `qc:checklist:manage` | 403 | Allow CRUD |

## 5. State transitions

| Entity | Từ | Sang | Trigger |
|--------|-----|------|---------|
| ChecklistVersion | draft | published | patch/create published |
| ChecklistVersion | published | archived | publish version khác |

## 6. Limits & wording

| Rule | Value |
|------|-------|
| Operators UI | ≥, ≤, =, >, <, between, contains |
| Section | `auto` \| `manual` |
| Cache TTL published | `qc_checklist_cache_ttl_seconds` (settings) |
| FE "Save version" button | Chưa wire create API (P1 gap) |

**Errors:** `Checklist version not found` (404), `Insufficient permissions` (403).

## 7. Risks

| Rủi ro | Phòng |
|--------|-------|
| Publish nhầm criteria trống | Validate ≥1 criterion P1 |
| FE edit local chưa save | Wire PATCH criteria P1 |

## 8. Open questions

| ID | Câu hỏi |
|----|---------|
| OQ-1 | CriteriaBuilder chưa persist PATCH — chỉ publish status? |
| OQ-2 | Drag reorder (GripVertical) chưa implement? |

## 9. API inventory

| Method | Path | Permission |
|--------|------|------------|
| GET | `/api/v1/qc/checklists` | `qc:checklist:manage` |
| GET | `/api/v1/qc/checklists/{id}` | `qc:checklist:manage` |
| POST | `/api/v1/qc/checklists` | `qc:checklist:manage` |
| PATCH | `/api/v1/qc/checklists/{id}` | `qc:checklist:manage` |
| GET | `/api/v1/qc/checklists/options` | `project:view` |
| GET | `/api/v1/qc/checklists/published/criteria` | `qc:review:perform` |
