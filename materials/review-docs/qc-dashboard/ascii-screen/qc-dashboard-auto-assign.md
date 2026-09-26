## Wireframe (ASCII)

```
┌────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│  Phân công tự động                                                          [x] Bật auto-assign        │
│  Tự động gán video chưa có người review theo chiến lược và giới hạn hàng đợi.                          │
├────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│  Chiến lược                                                                                            │
│  [ Ít tải nhất (least loaded)                                                              ▼ ]         │
│                                                                                                        │
│  Reviewers                                                                                             │
│  [x] Nguyễn Văn A   [x] Trần Thị B   [ ] Lê Văn C   ...                                                │
│                                                                                                        │
│  Tối đa hàng đợi / reviewer          [x] Ưu tiên high/critical                                         │
│  [ 12                    ]                                                                            │
├────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│  42 chưa gán          │                                    [ Chạy ngay ]  [ Reassign ngay ]            │
│  8 có thể reassign    │                                                                                │
└────────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

## Screen description

| # | Items | Control type | Data type | Description |
|---|-------|---------------|-----------|-------------|
| 1 | Title | Heading | string | • `auto_assign_title` |
| 2 | Description | Text | string | • `auto_assign_desc`; line-clamp-3 + title attr full text |
| 3 | Enabled toggle | Checkbox | bool | • `auto_assign_enabled`<br>• onChange → `saveMutation` PUT rules immediately<br>• Disabled while loading/saving |
| 4 | Form container | div | — | • `opacity-50 pointer-events-none` when `!rules.enabled` |
| 5 | Strategy select | Select | AutoAssignStrategy | • Options: round_robin, least_loaded, by_project<br>• Labels via `AUTO_ASSIGN_STRATEGY_KEYS` i18n |
| 6 | Reviewer picker | AutoAssignReviewerPicker | string[]\|null | • Multi-select from `GET /auto-assign/reviewers`<br>• null = all eligible<br>• Empty array disables run buttons |
| 7 | Max queue | Number input | int | • min=1 max=50; fallback 12 on invalid<br>• `auto_assign_max_queue` label |
| 8 | High priority | Checkbox | bool | • `auto_assign_high_priority` |
| 9 | Stats unassigned | Text | int | • From `GET /auto-assign/stats` → `unassigned` |
| 10 | Stats reassignable | Text | int | • `reassignable` count |
| 11 | Run now | Button primary | — | • POST `/auto-assign/run`<br>• Disabled: !enabled, unassigned=0, busy, noReviewersSelected<br>• Pending label `auto_assign_running` |
| 12 | Reassign now | Button ghost | — | • POST `/auto-assign/reassign`<br>• Disabled: !enabled, reassignable=0, busy, noReviewersSelected |
| 13 | Success toast | Toast | — | • `auto_assign_run_toast` + assigned count<br>• `auto_assign_reassign_toast` + reassigned count |
| 14 | Error toast | Toast | — | • `auto_assign_run_failed` / `auto_assign_reassign_failed` |
| 15 | Auth gate | null render | — | • Panel returns null if !canAssign or !authenticated or auth loading |
