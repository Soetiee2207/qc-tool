## Wireframe (ASCII)

```
┌──────────────────────────────────────────────────────────────────────────────────────────┐
│ ← ScaleAI_session_042.mp4  Project X  [In review]  +8 trong hàng đợi    [▤][☾][?] (Reject)(Pass)│
├──────────────────────────┬───────────────────────────────────────────────────────────────┤
│ ┌───────┬─────────┐      │                  ┌───────────────────────┐                    │
│ │► Audit│History ●│      │                  │          HEAD           │                  │
│ └───────┴─────────┘      │                  │                         │                  │
│ Audit bàn giao       (i) │                  └───────────────────────┘                    │
│ Thiếu 1/5 trường bắt buộc│     ┌───────────────────┐ ┌───────────────────┐               │
│                          │     │     LEFT WRIST     │ │    RIGHT WRIST     │             │
│ Delivery audit           │     └───────────────────┘ └───────────────────┘               │
│ ScaleAI v1 template      │                                    [x] Xoay 2 cam cổ tay 180°│
│                          │                                                               │
│  * partner_name          │  [‖] [«] [»] 00:42:00 / 03:10:00  (🔊) [0.5×][1×][2×][4×][8×] (⛶)│
│   VinDynamics            │                                                               │
│                          │                                                               │
│  * collector_id          │                                                               │
│   op-8432562934          │                                                               │
│                          │                                                               │
│  metadata.schema_version │                                                               │
│   v1.0                   │                                                               │
│                          │                                                               │
│  * activity_tags         │                                                               │
│   ↳ task                 │                                                               │
│      Disassemble, clean… │                                                               │
│   ↳ environment          │                                                               │
│      Industrial Workspace│                                                               │
│   ↳ scene                │                                                               │
│      assembly line       │                                                               │
└──────────────────────────┴───────────────────────────────────────────────────────────────┘
```

## Screen description

| # | Items | Control type | Data type | Description |
|---|-------|---------------|-----------|-------------|
| 1 | Toolbar (1 hàng, cao 48px) | Header | — | • Thứ tự: icon **←** (về list) · tên file (mono, truncate) · link **Project** (ẩn dưới `lg`) · `StatusChip` (hiện "In review" khi chưa có quyết định) · `+N trong hàng đợi` (ẩn dưới `lg`) · toggle ẩn/hiện sidebar · toggle dark mode (cả hai ẩn dưới `md`) · nút **Help** (mở dialog shortcut) · nút **Reject** · nút **Pass**<br>• Reject mở dialog chọn lý do (radio) + ghi chú; Pass mở dialog xác nhận đơn giản<br>• Khi item đã `passed`/`rejected` → hai nút này **không render** (read-only) |
| 2 | Tab "Audit bàn giao" | Tab | UI state (active/inactive) | • Nhãn lấy i18n `qc_delivery_audit_title`; tab mở **mặc định** khi vào màn (và reset về audit mỗi khi đổi item)<br>• Bấm → đổi nội dung sidebar, không ảnh hưởng Preview đang phát (US-002 AC1) |
| 3 | Tab "Lịch sử review" + dot đỏ | Tab | UI state | • Nhãn `qc_review_history_title` (có `qc:assign`) hoặc `qc_review_history_title_mine`<br>• **Dot đỏ** (`metadata-qc-sidebar-history-reject-hint`) hiện khi trong các session reviewer được xem có ít nhất 1 lần `rejected`<br>• Bấm lại tab đang active: no-op (US-002 AC2) |
| 4 | Header panel Delivery Audit | Text + icon | — | • Tiêu đề `"Audit bàn giao"`<br>• Dòng trạng thái: `"Thiếu {missing}/{total} trường bắt buộc"` (đỏ) nếu thiếu, ngược lại `"Đủ tất cả trường bắt buộc"` (hoặc biến thể có mock ở môi trường dev)<br>• Nút **info** góc phải mở popover hướng dẫn audit<br>• Tổng required thực tế = **5** (`activity_tags` container và `metadata.schema_version` không tính) |
| 5 | Section "Delivery audit" | Section header | string | • Tiêu đề section + dòng `source` = `ScaleAI v1 template`<br>• Mỗi field: nhãn (kèm `*` nếu required), tuỳ chọn nút info mô tả field, và giá trị<br>• Field thiếu: tô đỏ, giá trị `"Thiếu — cần audit"`; field sai ngưỡng: tô amber + hậu tố `(giá trị không hợp lệ)` |
| 6 | partner_name | Display field (read-only, required) | string | • Tên đối tác/tổ chức thu thập dữ liệu, gắn với bản ghi<br>• Bắt buộc (*); mặc định "VinDynamics" khi không có giá trị khác được khai báo |
| 7 | collector_id | Display field (read-only, required) | string | • ID duy nhất của collector (người/thiết bị thu thập), dạng alphanumeric<br>• Bắt buộc (*); ví dụ giá trị: `op-8432562934` |
| 8 | metadata.schema_version | Display field (read-only, optional) | string | • Phiên bản schema của khối metadata đi kèm bản ghi<br>• **Không** bắt buộc (không hiện `*`, không tính vào mẫu số); mặc định `v1.0` |
| 9 | activity_tags | Display field group (read-only, required) | object | • Nhóm 3 trường mô tả hoạt động được quay: `task`, `environment`, `scene` (chi tiết ở 3 dòng ↳ bên dưới)<br>• Có `*` nhưng **không** được cộng vào `required_count` — 3 trường con mới là đơn vị đếm |
| 10 | ↳ task | Display field (read-only, required) | string | • Mô tả định danh activity của collector<br>• Bắt buộc; định dạng: tối thiểu 2 động từ + 1 vật thể + 1 dụng cụ/thành phần<br>• Ví dụ: "Disassemble, clean, and reassemble a fan using a screwdriver and cloth." (giá trị hiện trong khung đã rút gọn "…" do dài, xem đủ ở đây) |
| 11 | ↳ environment | Display field (read-only, required) | string (enum, 6 giá trị) | • Loại môi trường quay, bắt buộc<br>• Chỉ nhận 1 trong 6 giá trị: Industrial Workspace, Logistics Floor, Workshop & Field Service, Commercial Kitchen, Retail & Merchandising Floor, Service & Care Environment<br>• Giá trị ngoài 6 giá trị trên = **invalid** (amber), khác với "thiếu" |
| 12 | ↳ scene | Display field (read-only, required) | string | • Scene/phòng/trạm làm việc cụ thể trong `environment` đã chọn, bắt buộc<br>• Ví dụ giá trị: assembly line, kitchen prep counter, grocery store aisle, workshop bench, stockroom |
| 13 | Preview — HEAD | Video display (playback-only) | video stream | • Pane lớn nhất, đặt phía trên theo bố cục tam giác (`flex-[3]`; 2 pane cổ tay `flex-[2]` chia đôi dưới)<br>• **Không** có toolbar/seek riêng trên pane — điều khiển qua thanh chung ở #16 |
| 14 | Preview — LEFT / RIGHT WRIST | Video display (playback-only) | video stream | • Phát đồng bộ theo head + `syncOffsets`; không có control riêng<br>• Click vào pane → phát/tạm dừng cả nhóm |
| 15 | Checkbox "Xoay 2 cam cổ tay 180°" | Checkbox | boolean | • Nhãn `scaleai_qc_flip_wrist`; **mặc định bật**<br>• Bật → 2 pane cổ tay render lật 180° (chỉ đổi hướng hiển thị, không đổi dữ liệu)<br>• Luôn hiển thị ở cả hai chế độ; khi `playbackOnly` (màn QC Review detail) thì dòng gợi ý layout bên trái được ẩn và checkbox dồn về phải |
| 16 | Thanh điều khiển chung (1 thanh) | Slider + button group | time | • Gắn **head camera** — play/pause, `«`/`»` ±5s, `current / total` `HH:MM:SS`, mute, 5 nút tốc độ, fullscreen (fullscreen cả lưới 3 pane)<br>• Khi seek cần chờ 2 pane cổ tay bắt kịp → overlay mờ `"Đang đồng bộ…"` (`scaleai_qc_seek_syncing`)<br>• **Không** có timeline độc lập cho từng camera |
| 17 | Nút Pass / Reject | Button | action | • Pass: đánh giá bản ghi đạt chất lượng; Reject: đánh giá không đạt (yêu cầu lý do); Back (icon ←) quay lại QC Review Queue<br>• Nằm cùng hàng toolbar #1 |
