---
type: brainstorm
feature: review/qc-review-detail-scaleai-3cam
idea_slug: review-detail-3cam-layout
status: draft
mode: deep
lang: vi
owner: "@binhhm"
created: 2026-08-26
updated: 2026-08-26
complexity_flags: []
links: []
tags: [brainstorm, scaleai-qc-review]
stale_reason: ""
changelog:
  - 2026-08-26 | /brainstorm | initial brainstorm — redesign QC review detail layout cho preview 3-cam ScaleAI multicam
---

# Bố cục lại màn QC Review detail cho preview 3-video

> Feature: scaleai-qc-review | Idea: review-detail-3cam-layout
> 1 feature có thể có nhiều brainstorm — đây là 1 idea/draft độc lập.

## 1. Idea Seed

QC Review -> Click detailed item. Trong màn hình detailed item này, tôi muốn thay đổi lại layout. Lí do như sau: Hiện tại màn hình preview chỉ có 1 video. Nhưng bây giờ tôi muốn màn preview hiển thị 3 videos (bố cụ có thể dàn hàng ngang hoặc 1 trên hai dưới như hình tam giác tính sau). Do đó các component sẽ bị xô đẩy. Trong màn có 3 component chính là DELIVERY AUDIT, PREVIEW, REVIEW HISTORY. Tôi muốn bạn suggest cho tôi 1 layout mới đáp ứng được yêu cầu mới, vẫn giữ được sự đơn giản, tiện lợi, dễ dùng

*Raw input từ user — câu/đoạn description gốc.*

## 2. Context

Màn hình đang nói tới là màn QC Review → click 1 item để xem chi tiết, tương ứng file code `frontend/src/features/qc/MetadataQcReviewLayout.tsx`. 3 khối chính trong màn:

- **DELIVERY AUDIT** — panel bên trái, hiển thị các trường metadata bàn giao (episode UUID, operator, device kit...) + đếm số trường thiếu bắt buộc. Code: `MetadataSidecarPanel.tsx`.
- **PREVIEW** — khung xem video. Hiện tại render 1-2 video (stereo review) qua `StereoVideoView`, HOẶC 3 video (review loại ScaleAI multicam: Head + camera cổ tay trái + cổ tay phải) qua `ScaleAiMulticamVideoView` — component này đã tự dàn bố cục "1 trên (Head) - 2 dưới (cổ tay)" nội bộ.
- **REVIEW HISTORY** — danh sách các lần review trước của item, hiện đang nằm dưới khung Preview. Code: `ReviewHistoryPanel.tsx`.

Vấn đề: khung Preview cho case 3-video đã tự cao hơn (do phải chứa 3 video xếp tầng), nhưng khung tổng thể của màn (Delivery Audit cố định bề rộng, Review History nằm dưới Preview) chưa được thiết kế lại cho case này → các khối bị "xô đẩy", chật, Review History có thể bị đẩy khỏi màn hình cần scroll thêm.

Phạm vi brainstorm này: CHỈ redesign bố cục tổng thể (vị trí 3 khối) cho case review 3-video (ScaleAI multicam). Case review 1-2 video (stereo/single) giữ nguyên layout hiện tại — không đổi.

## 3. User Types (preliminary)

| User Type | Pain Point | Primary Need |
|-----------|-----------|--------------|
| QC Reviewer (Portal User có quyền review) | Xem 3 video multicam cùng lúc nhưng Delivery Audit + Review History chiếm chỗ, khung preview bị chật, khó soi chi tiết | Preview đủ lớn cho 3 video, vẫn truy cập nhanh Audit/History khi cần đối chiếu |

## 4. Capabilities Breakdown

### P0 — must have
- Sidebar trái gộp 2 tab **"Audit bàn giao"** / **"Lịch sử review"** (thay cho Audit cố định + History nằm dưới Preview) — áp dụng CHỈ cho review có 3 video (ScaleAI multicam).
- Preview 3 video giữ bố cục tam giác (1 trên — Head, 2 dưới — cổ tay trái/phải), tái dùng component `ScaleAiMulticamVideoView` hiện có, chỉ nới khung ngoài để chiếm không gian được giải phóng từ History.
- Tab "Audit bàn giao" mở mặc định khi vào màn.
- Badge số trường thiếu tiếp tục hiển thị NGAY trong nội dung tab Audit (như hiện tại) — không gắn badge lên nhãn tab.
- Review 1-2 video (stereo/single) GIỮ NGUYÊN layout hiện tại (Audit cố định bên trái không tab, History nằm dưới Preview) — không đổi.

### P1 — should have
- Dấu hiệu nhỏ trên tab "Lịch sử review" báo item đang xem đã từng có lịch sử reject trước đó (xem OQ-3).
- Giữ nút thu gọn sidebar (ẩn/hiện) cho cả 2 tab, như nút collapse Audit hiện có (xem OQ-1).

### P2 — nice to have
- Keyboard shortcut chuyển tab Audit/History, tương tự các shortcut Pass/Reject/Play hiện có.
- Responsive cho màn hình < 1024px (ngoài phạm vi hiện tại — màn này chủ yếu dùng desktop rộng).

> P0/P1/P2 là tentative; final scope chốt ở `/prd scaleai-qc-review`.

## 5. Core Flows (Happy Path)

### 5.1 Reviewer xem chi tiết item 3-video (ScaleAI multicam)

1. Reviewer bấm vào 1 item ScaleAI multicam trong QC Review queue.
2. Hệ thống mở màn detail: sidebar trái hiện tab **"Audit bàn giao"** (mặc định), Preview hiện 3 video theo bố cục tam giác — Head lớn ở trên, 2 camera cổ tay nhỏ hơn ở dưới.
3. Reviewer xem đủ 3 góc quay để đánh giá chất lượng bản ghi (khung hình, đồng bộ, nội dung).
4. Cần đối chiếu lịch sử review trước đó → reviewer bấm tab **"Lịch sử review"**; nội dung sidebar đổi, Preview không đổi.
5. Reviewer bấm Pass hoặc Reject trên toolbar (giữ nguyên vị trí/hành vi hiện tại).

```
┌──────────────────────────────────────────────────────────────────────────┐
│ ScaleAI_session_042.mp4    Project X          [ Pass ] [ Reject ] ( ← ) │
├───────────────────┬────────────────────────────────────────────────────┤
│┌─────────┬───────┐│                ┌──────────────────────┐             │
││ Audit   │History││                │        HEAD           │             │
│└─────────┴───────┘│                │                        │             │
│ Episode UUID       │                └──────────────────────┘             │
│  ep_a91c...        │        ┌───────────────────┐ ┌───────────────────┐  │
│ Operator ID         │        │   LEFT WRIST       │ │   RIGHT WRIST      │  │
│  op_1042            │        └───────────────────┘ └───────────────────┘  │
│ * Task ID           │                                                    │
│  ! Thiếu — cần audit │   [▶] [────────────●─────────────────] 00:42/03:10│
│ Device Kit ID        │                                                    │
│  kit_scaleai_07      │                                                    │
└───────────────────┴────────────────────────────────────────────────────┘
```

*Bố cục đã chọn: Phương án B (tam giác) — tận dụng component video-grid có sẵn, chỉ đổi khung ngoài (sidebar gộp tab, Preview nới rộng thay chỗ History cũ).*

### 5.2 Reviewer xem chi tiết item 1-2 video (không đổi)

1. Reviewer bấm vào 1 item stereo/single trong QC Review queue.
2. Hệ thống mở màn detail: sidebar trái vẫn là Audit cố định (không tab), Preview hiện 1-2 video, Review History nằm dưới Preview — **giữ nguyên hành vi hiện tại, không thuộc phạm vi thay đổi của brainstorm này**.

*Chỉ 2 flows chính cho phạm vi này — flow 5.2 liệt kê để làm rõ ranh giới scope, không phải flow mới.*

## 6. System Behavior Deep Dive

> `complexity_flags` của idea này đều false (không có external redirect/async/multi-role/state-machine mới) — các mục Interrupted Transactions, Scenario Matrix, State Transitions của template KHÔNG áp dụng, bỏ qua theo đúng rule.

### 6.1 Decision Points

| ID | Flow | Khi nào | YES (nhánh 3-video) | NO (nhánh 1-2 video) |
|---|---|---|---|---|
| D1 | Mở màn QC Review detail | Item đang review có phải loại ScaleAI multicam (3 video: Head/trái/phải)? | Dùng layout mới: sidebar trái = tab Audit/History, Preview tam giác 1 trên - 2 dưới, không còn History panel dưới video | Giữ layout cũ: sidebar Audit cố định (không tab), Preview 1-2 video, Review History nằm dưới Preview |

### 6.5 Other Edge Cases

- **Nút thu gọn sidebar hiện có** (`studio.metadataCollapsed`, đang ẩn/hiện khối Audit) — cần xác nhận có tiếp tục áp dụng cho sidebar tab mới (ẩn luôn cả 2 tab) hay bỏ vì đã có tab. → OQ-1.
- **Segment Summary Card** (thanh tóm tắt đoạn giữ/cắt, nếu review có segment) hiện nằm dưới Preview — khi Preview cao hơn (3 video tam giác), có thể vẫn bị chật. Cần xác nhận vị trí giữ nguyên hay dời/thu nhỏ. → OQ-2.
- **Badge thiếu trường** chỉ hiện trong nội dung tab Audit, không gắn lên nhãn tab (theo quyết định) — rủi ro: reviewer đang ở tab History có thể không biết Audit đang thiếu trường. Giảm rủi ro nhờ tab Audit mặc định mở khi vào màn, nhưng nếu reviewer đã tự chuyển sang tab History thì vẫn có thể bỏ sót — ghi nhận là trade-off đã chọn, không phải bug.
- **Desktop-only** — màn này (cả layout cũ và mới) chỉ tối ưu cho ≥1024px, không xử lý breakpoint nhỏ hơn ở brainstorm này.

## 7. Validation, Limits & Wording

Không áp dụng — brainstorm này KHÔNG thêm business rule, validation, hay limit/quota mới (chỉ tái sắp xếp bố cục UI của các component đã có sẵn dữ liệu).

**Wording tái dùng nguyên trạng** (không cần chuỗi mới):
- Nhãn tab "Delivery audit" → dùng lại string hiện có `qc_delivery_audit_title` ("Audit bàn giao").
- Nhãn tab "Review history" → dùng lại string hiện có `qc_review_history_title` ("Lịch sử review").

## 8. Assumptions

- Segment Summary Card (nếu review có segment) vẫn nằm dưới Preview, không đổi vị trí — trừ khi OQ-2 được xác nhận cần dời.
- Toolbar trên cùng (tên file, project, nút Pass/Reject) giữ nguyên vị trí và hành vi.
- Reject reason banner (khi item đã bị reject) giữ nguyên vị trí ngay dưới toolbar.
- Đối tượng dùng màn này là QC reviewer nội bộ dùng desktop/laptop — không cần tối ưu mobile.
- Nút thu gọn sidebar hiện có tiếp tục tồn tại ở dạng nào đó cho case layout mới, chi tiết chốt ở OQ-1.

## 9. Risks

| Rủi ro | Khả năng | Hậu quả nghiệp vụ | Cách phòng |
|--------|----------|-------------------|-----------|
| 2 layout khác nhau tồn tại song song (case 3-video vs case 1-2 video) gây nhầm lẫn khi test/QA hoặc cảm giác thiếu đồng bộ trải nghiệm | thường | Tăng effort QA/test case, risk bug lệch giữa 2 biến thể | Ghi rõ trong SRS/wireframe đây là 2 biến thể có chủ đích; UAT riêng cho từng biến thể |
| Reviewer quen thói cũ (Review History luôn hiện, không cần bấm) có thể quên bấm tab "Lịch sử review" khi cần đối chiếu, bỏ sót context quan trọng (vd item từng bị reject) | thỉnh thoảng | Risk chất lượng QC giảm — có thể pass nhầm item từng có vấn đề | Cân nhắc dấu hiệu nhỏ trên tab History khi có lịch sử reject (xem OQ-3); training/thông báo khi rollout |
| Adoption — reviewer đã dùng layout cũ lâu, cần thời gian làm quen tab mới | thỉnh thoảng | Giảm throughput QC ngắn hạn tuần đầu rollout | Release note/hướng dẫn ngắn trong app khi rollout |

## 10. Success Criteria (preliminary)

- Reviewer xem được đủ 3 video (Head/trái/phải) mà không cần scroll dọc thêm so với hiện tại.
- Không gian Preview tăng rõ rệt so với layout cũ khi review 3-video.
- Review History vẫn truy cập được trong ≤ 1 click từ màn detail.
- Không tăng số complaint "khó nhìn video QC" từ QC team sau rollout.

## 11. Open Questions

- [ ] OQ-1: Nút thu gọn sidebar hiện có (ẩn/hiện Audit) có tiếp tục áp dụng cho sidebar tab mới (ẩn luôn cả 2 tab) không, hay bỏ nút này khi đã có tab?
- [ ] OQ-2: Segment Summary Card (thanh tóm tắt đoạn giữ/cắt, nếu có) có cần dời/thu nhỏ khi Preview cao hơn (3 video), hay giữ nguyên vị trí dưới Preview như hiện tại?
- [ ] OQ-3: Tab "Lịch sử review" có cần 1 dấu hiệu nhỏ (không phải badge số) khi item đang xem đã từng có lịch sử reject/review trước đó, để tránh reviewer bỏ sót context quan trọng?
- [ ] OQ-4: Bề rộng sidebar tab (giữ 320px như hiện tại hay điều chỉnh) — có cần đo lại khi nội dung "Lịch sử review" dài (nhiều dòng lịch sử) hiển thị trong cùng width 320px?

## 12. Next Steps

Sau brainstorm này (sau khi BA approve):
- `/urd scaleai-qc-review` — capture user perspective
- `/brd scaleai-qc-review` — business case
- `/prd scaleai-qc-review` — product scope
- `/wireframe-ascii scaleai-qc-review` — vẽ ASCII wireframe chính xác (kèm bảng mô tả 5 cột) từ layout đã chọn ở đây

*KHÔNG nhảy thẳng SRS — qua PRD trước.*
