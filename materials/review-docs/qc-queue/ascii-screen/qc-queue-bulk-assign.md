## Wireframe (ASCII)

```
┌────────────────────────────────────────────────────────────────────────────────┐
│  Gán hàng loạt — 12 video đã chọn                                              │
├────────────────────────────────────────────────────────────────────────────────┤
│  [ 🔍 Tìm reviewer...                                                        ] │
│  Chọn nhanh theo nhóm  [ 🔍 Chọn nhóm… ▼ ]   + Tạo nhóm                        │
│        ┌──────────────────────────────────────────────┐                        │
│        │ QC Reviewer           24 thành viên          │                        │
│        │                         Tạo 03/09/2026       │                        │
│        │ QC Lead                3 thành viên          │                        │
│        │ Nhóm thiết kế          8 thành viên          │                        │
│        └──────────────────────────────────────────────┘                        │
│                                                                                │
│  [x] Nguyễn Văn A                                                              │
│      @nguyenvana                                                               │
│  [ ] Trần Thị B                                                                │
│      @tranthib                                                                 │
│  [x] Lê Văn C                                                                  │
│      @levanc                                                                   │
│  [ ] Phạm Thị D                                                                │
│  [x] Hoàng Văn E                                                               │
│                                                                                │
│  ! Chọn ít nhất 1 người để gán                                                 │
│                                                                                │
│  [ ] Bạn đang gán 12 video cùng lúc, thao tác có thể mất vài giây. Tiếp tục?   │
├────────────────────────────────────────────────────────────────────────────────┤
│  Xem trước phân chia (3 người — cân bằng theo thời lượng, sửa tay được):       │
│  12 video · tổng 01:23:45                                                      │
│                                                                                │
│   Tên tệp               │  Thời lượng  │  Người phụ trách                      │
│   ──────────────────────┼──────────────┼──────────────────────────             │
│   filename.mp4          │  02:15       │  [ Nguyễn Văn A      ▼ ]              │
│   clip_bathroom_01.mp4  │  01:42       │  [ Lê Văn C          ▼ ]              │
│   kitchen_task_03.mp4   │  03:01       │  [ Hoàng Văn E       ▼ ]              │
│   ... 9 video khác ...  │  ...         │  [ ...               ▼ ]              │
├────────────────────────────────────────────────────────────────────────────────┤
│                            ( Hủy )          [   Xác nhận gán   ]               │
└────────────────────────────────────────────────────────────────────────────────┘
```

*Dropdown nhóm (khi mở) hiển thị nhãn nhóm + số thành viên + ngày tạo; nút "+ Tạo nhóm" chỉ hiện khi user có `user:manage`. Danh sách reviewer hiển thị tên + `@username`, và reviewer đã có item trong phân chia hiện thêm badge tải ở cuối dòng (`bulk_assign_reviewer_load` = "{count} · {duration}").*

## Screen description

| # | Items | Control type | Data type | Description |
|---|-------|---------------|-----------|-------------|
| 1 | Tiêu đề modal | Heading | string | • Mục đích: xác nhận số lượng video đang thao tác<br>• Text `bulk_assign_modal_title`: "Gán hàng loạt — {N} video đã chọn" — N lấy từ badge lựa chọn ở màn Queue (`qc-queue-list.md` #10) |
| 2 | Ô tìm reviewer | Text input (icon Search) | string | • Placeholder `auto_assign_reviewers_search_placeholder`; không bắt buộc<br>• Lọc theo `username`, họ tên (`full_name`) và nhãn nhóm của reviewer |
| 3 | Chọn nhanh theo nhóm | Combobox (search + listbox) | group name | • Label `bulk_assign_quick_group`, placeholder `bulk_assign_quick_group_placeholder`<br>• Nguồn dữ liệu: `GET /api/v1/admin/users/groups` (mirror Postgres); nếu API trả rỗng thì fallback 2 nhóm mặc định `vd-qc-reviewers` / `vd-qc-leads` (chưa có số thành viên/ngày tạo)<br>• Mỗi dòng: nhãn nhóm (`auto_assign_group_reviewer` = "QC Reviewer", `auto_assign_group_lead` = "QC Lead", nhóm khác hiện tên gốc) + `groups_member_count` + `groups_created_at`<br>• Bàn phím: ArrowUp/Down + Enter để chọn, Esc đóng; không khớp → `bulk_assign_quick_group_empty` ("Không tìm thấy nhóm")<br>• Chọn nhóm → FE gọi `GET /api/v1/admin/users/groups/{name}/members`, tick các reviewer khớp và toast `bulk_assign_quick_group_selected` ("Đã thêm {X} reviewer QC hợp lệ từ nhóm"); nhóm không có ai hợp lệ → lỗi `bulk_assign_quick_group_none`. Lỗi gọi API → `bulk_assign_quick_group_failed` |
| 3b | Nút "Tạo nhóm" | Button (link, icon Plus) | — | • Chỉ hiện khi user có `user:manage` (`group_create_action`)<br>• Mở `CreateUserGroupDialog` (xem `docs/authorization/users-admin/`); tạo nhóm xong thì thêm luôn các reviewer đang tick vào nhóm mới (`PUT /api/v1/admin/users/groups/{name}/members`) và toast `groups_member_count`<br>• Tạo nhóm lỗi → `group_create_failed`; thêm thành viên lỗi → `group_members_add_failed` |
| 4 | Danh sách reviewer (checkbox) | Checkbox list | set\<reviewer_id\> | • Nguồn: `GET /api/v1/qc/auto-assign/reviewers` (chỉ gọi khi user có `qc:assign`)<br>• Mỗi dòng: tên hiển thị (`full_name` hoặc `username`) + `@username`; reviewer có item trong phân chia hiện badge tải cuối dòng — `bulk_assign_reviewer_load` "{count} · {duration}", tooltip `bulk_assign_reviewer_load_title` "Đã gán {count} video, tổng {duration}"<br>• Validation: ≥1 người mới bật nút Xác nhận gán; khi 0 người, ngay dưới danh sách hiện lỗi `bulk_assign_pick_reviewer` "Chọn ít nhất 1 người để gán" (US-006 AC4)<br>• States: danh sách rỗng → `auto_assign_reviewers_none_available` ("Không có reviewer khả dụng"); đang tải → "Đang tải…" |
| 5 | Cảnh báo batch lớn | Checkbox (inline) | — | • Chỉ hiện khi batch > 200 item (`LARGE_BATCH_THRESHOLD`), ẩn nếu ≤200 (US-006 Business Rules)<br>• Wording `bulk_assign_large_warning`: "Bạn đang gán {N} video cùng lúc, thao tác có thể mất vài giây. Tiếp tục?"<br>• Là checkbox bắt buộc tick — chưa tick thì "Xác nhận gán" vẫn bị vô hiệu (khác mô tả cũ "cảnh báo rồi tiếp tục") |
| 6 | Khối "Xem trước phân chia" | Table (3 cột) | video↔reviewer[] | • Mục đích: cho Lead thấy trước — và sửa tay — kết quả chia trước khi cam kết<br>• States: **ẩn hoàn toàn** khi chỉ 1 reviewer được chọn (không cần preview vì không có gì để chia); **hiện** khi ≥2 reviewer (US-006 AC2)<br>• Tiêu đề `bulk_assign_preview_title`: "Xem trước phân chia ({K} người — cân bằng theo thời lượng, sửa tay được)"; ngay dưới là dòng tổng `bulk_assign_preview_total`: "{N} video · tổng {HH:MM:SS}"<br>• Cột: file (`filename`) / thời lượng (`duration`, `HH:MM:SS`, rỗng thì hiện "—") / người phụ trách (`assignee`, dropdown sửa tay từng dòng)<br>• Data: chia cân bằng theo tổng thời lượng (`buildBalancedAssignMap`) — item dài nhất xét trước, gán cho reviewer đang ít tổng thời lượng nhất (hoà thì ưu tiên người ít item hơn); không tính tải hiện tại của reviewer (V1, xem Assumption) |
| 7 | Dropdown đổi người mỗi dòng | Select (inline trong bảng) | reviewer_id | • Mục đích: cho Lead sửa tay video nào giao cho ai, khác với kết quả auto-chia mặc định<br>• Validation: chỉ chọn được trong nhóm reviewer đã tick ở #4 |
| 8 | Nút Hủy | Button (secondary) | — | • Nhãn `cancel`; đóng modal, không gửi request, giữ nguyên selection ở màn Queue; bị vô hiệu khi đang gửi request |
| 9 | Nút Xác nhận gán | Button (primary) | — | • Nhãn `bulk_assign_confirm`; disabled khi 0 reviewer được chọn (#4), 0 item, batch lớn chưa tick xác nhận (#5), đang gửi (`isAssigning`) hoặc đang tải reviewer<br>• Navigation: `POST /api/v1/qc/queue/assign` — 1 người dùng `item_ids` + `assignee_id`/`assignee_name`/`assignee_initials`; ≥2 người dùng `assignments[]` (srs.md F-05)<br>• Success 1 người (không skip): "Đã phân công {N} mục cho {tên}" (`assign_success`) — nhiều người: "Đã gán {N} mục cho {K} người" (`assign_multi_success`)<br>• Partial (có video đã bị gán trước): "Đã gán {X}/{Y} mục — {Z} mục không gán được" (`assign_partial_success`) (US-006 AC3)<br>• Lỗi: message từ API hoặc "Phân công thất bại" (`assign_failed`)<br>• Sau khi thành công: đóng modal, clear selection ở màn Queue |
