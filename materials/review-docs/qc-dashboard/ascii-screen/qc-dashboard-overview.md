## Wireframe (ASCII)

```
┌────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│  Review  ›  QC Dashboard                                                                               │
│  Tổng quan hàng đợi và tiến độ QC                                                                     │
├────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌─────────────┐                        │
│ │ ▣  1240.5   │ │ ⏱  320.2    │ │ ▣  180.0    │ │ ✓  650.1    │ │ ✗  90.4     │                        │
│ │ Tổng raw (h)│ │ Chờ review  │ │ Đang review │ │ Passed (h)  │ │ Rejected(h) │                        │
│ └─────────────┘ └─────────────┘ └─────────────┘ └─────────────┘ └─────────────┘                        │
├────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ ┌──────────────────────────────┐ ┌──────────────────────────────────────────────────────────────────┐  │
│ │ Tóm tắt hàng đợi             │ │ Hàng đợi của tôi                              [ Xem tất cả ]     │  │
│ │ Tổng: 1240.5 giờ             │ ├──────────────────────────────────────────────────────────────────┤  │
│ │      ╭───╮                   │ │ ▶ clip_01.mp4    Project A · 02:10   [High]  2d   [ Mở review ] │  │
│ │     ╱     ╲  Pie by status   │ │ ▶ clip_02.mp4    Project B · 01:05   [Med]   1d   [ Mở review ] │  │
│ │    │       │  (hours)        │ │ ▶ clip_03.mp4    Project A · 03:22   [Crit]  5h   [ Mở review ] │  │
│ │     ╲     ╱                  │ │ (empty: Không có mục được gán cho bạn)                            │  │
│ │      ╰───╯                   │ └──────────────────────────────────────────────────────────────────┘  │
│ └──────────────────────────────┘                                                                       │
├────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│  Analytics (QCDashboardAnalytics)                                                                      │
│  [ Needs review vs Passed cohort tabs ]  [ Assignee pass rate bars ]  [ Pilot progress ]  [ L1 caps ]  │
├────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│  (Auto-assign panel — see qc-dashboard-auto-assign.md)                                                 │
└────────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

## Screen description

| # | Items | Control type | Data type | Description |
|---|-------|---------------|-----------|-------------|
| 1 | Page title | Heading | string | • `nav_qc_dashboard` / `nav_annotation_dashboard`<br>• Subtitle `dash_qc_subtitle` / `dash_annotation_subtitle` |
| 2 | View queue link | Button link | — | • Annotation mode only: `view_annotation_queue` → `/qc/annotation` |
| 3 | Stat tiles (×5) | vd-stat-tile | float hours | • Keys: totalRaw, pending, in_review, passed, rejected<br>• Icon + color per `DASHBOARD_TILE_KEYS`<br>• Loading: "—"<br>• Label includes `(dash_qc_hours)` |
| 4 | Queue summary card | Pie chart | hours[] | • Title `dash_queue_summary`<br>• Total hours line<br>• Recharts Pie innerRadius 45 outer 65<br>• Tooltip `.toFixed(1)` hours<br>• Empty: `no_queue_data` |
| 5 | My queue card | List | QcQueueItem[] | • Header `dash_my_queue` + `view_all` → `qcListPath(mode)`<br>• Max 4 items from API<br>• Thumbnail color block + play glyph<br>• ProjectLink + duration<br>• Priority StatusChip<br>• Age mono<br>• Review button → `qcReviewPath` |
| 6 | Analytics section | QCDashboardAnalytics | QcDashboardAnalytics | • Props: analytics, isLoading<br>• Cohort toggles, bar charts, pilot, caps, difficulty targets<br>• `topBuckets` limit 8 |
| 7 | Auto-assign panel | Embedded card | — | • Conditional: `canAssign && authenticated && !annotation`<br>• See [[qc-dashboard-auto-assign.md]] |
