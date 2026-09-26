---
feature: qc-dashboard
device: Desktop (1024)
updated: 2026-09-05
changelog:
  - 2026-09-05 | initial | overview + auto-assign từ QCDashboard.tsx + AutoAssignRulesPanel.tsx
---

# QC Dashboard — ASCII Screens

| Screen | File | Mô tả |
|--------|------|--------|
| Dashboard overview | [[qc-dashboard-overview.md]] | Tiles, pie, my queue, analytics placeholder |
| Auto-assign panel | [[qc-dashboard-auto-assign.md]] | Rules + run/reassign (embedded in dashboard) |

## Descriptions

- **qc-dashboard-overview:** Route `/qc/dashboard`; annotation variant hides auto-assign, shows link to annotation queue.
- **qc-dashboard-auto-assign:** Sub-component `AutoAssignRulesPanel`; permission `qc:assign` required.
