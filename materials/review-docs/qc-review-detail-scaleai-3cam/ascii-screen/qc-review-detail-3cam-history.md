## Wireframe (ASCII)

```
┌──────────────────────────────────────────────────────────────────────────────────────────┐
│ ← ScaleAI_session_042.mp4  Project X  [In review]  +8 trong hàng đợi    [▤][☾][?] (Reject)(Pass)│
├──────────────────────────┬───────────────────────────────────────────────────────────────┤
│ ┌───────┬─────────┐      │                  ┌───────────────────────┐                    │
│ │ Audit │►History │      │                  │          HEAD           │                  │
│ └───────┴─────────┘      │                  │                         │                  │
│ Lịch sử review           │                  └───────────────────────┘                    │
│                          │     ┌───────────────────┐ ┌───────────────────┐               │
│ minh.nv      Passed      │     │     LEFT WRIST     │ │    RIGHT WRIST     │             │
│  12/08 14:20             │     └───────────────────┘ └───────────────────┘               │
│ lan.nv       Rejected    │                                    [x] Xoay 2 cam cổ tay 180°│
│  10/08 09:05             │                                                               │
│ hoa.nv       In progress │  [‖] [«] [»] 00:42:00 / 03:10:00  (🔊) [0.5×][1×][2×][4×][8×] (⛶)│
│  08/08 16:41             │                                                               │
│                          │                                                               │
└──────────────────────────┴───────────────────────────────────────────────────────────────┘
```

## Screen description

| # | Items | Control type | Data type | Description |
|---|-------|---------------|-----------|-------------|
| 1 | Toolbar | Header | — | • Không đổi khi chuyển tab: **←** · tên file · Project link · `StatusChip` · `+N trong hàng đợi` · toggle sidebar · toggle dark mode · Help · **Reject** · **Pass**<br>• Read-only (item đã quyết định) → ẩn Reject/Pass |
| 2 | Tab "Audit bàn giao" (inactive ở màn này) | Tab | UI state | • Bấm để quay lại xem metadata bàn giao — xem màn `qc-review-detail-3cam-audit` cho nội dung khi tab này active<br>• Navigation: bấm → đổi nội dung sidebar, Preview giữ nguyên trạng thái phát (US-002 AC1) |
| 3 | Tab "Lịch sử review" (active ở màn này) | Tab | UI state | • Nhãn `qc_review_history_title` (có `qc:assign`) hoặc `qc_review_history_title_mine`<br>• Dot đỏ bên nhãn khi có ít nhất 1 session `rejected` trong tập reviewer được xem<br>• Edge: bấm lại tab đang active không có hiệu ứng thừa (US-002 AC2) |
| 4 | Danh sách lịch sử review | List panel (read-only) | `QcReviewSession[]` | • Nguồn `GET /api/v1/qc/queue/{item_id}/review-sessions`, FE filter theo `qc:assign` trước khi render<br>• Mỗi dòng = 1 lần review: reviewer, kết quả, thời điểm — không có action trên dòng<br>• Nếu không có session nào → panel trạng thái rỗng |
| 5 | Preview — HEAD / LEFT WRIST / RIGHT WRIST | Video display (playback-only) | video stream | • Giữ nguyên nội dung + trạng thái phát (play/pause, vị trí) khi chuyển sang tab này — KHÔNG reload (US-002 AC1)<br>• Bố cục tam giác không đổi so với màn `qc-review-detail-3cam-audit`<br>• Checkbox "Xoay 2 cam cổ tay 180°" vẫn hiển thị |
| 6 | Thanh điều khiển chung | Slider + button group | time | • Một thanh duy nhất gắn head camera — không đổi khi chuyển tab, vị trí phát giữ nguyên (US-002 AC1) |
| 7 | Nút Pass / Reject / Back | Button | action | • Giữ nguyên vị trí + hành vi toolbar hiện tại, không đổi theo tab đang mở |
