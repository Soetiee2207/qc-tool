---
type: brainstorm
feature: qc-queue
idea_slug: bulk-assign-group-redesign
status: draft
mode: deep
lang: vi
owner: "@binhhm"
created: 2026-09-10
updated: 2026-09-25
complexity_flags: [has_multi_role]
links: [docs/review/qc-queue/brainstorms/baseline-from-code.md, docs/review/qc-queue/urd.md, docs/review/qc-queue/srs.md]
tags: [brainstorm, qc-queue, review, assign]
stale_reason: ""
changelog:
  - 2026-09-25 | docs-sync | Lựa chọn giữ khi đổi trang (chỉ reset khi đổi filter); chia bulk assign cân bằng theo tổng thời lượng thay round-robin
  - 2026-09-22 | docs-sync | Đảo lại phần selection: đổi trang/filter nay reset lựa chọn (DP-394); nút Gán nằm ở thanh chọn hợp nhất
  - 2026-09-11 | docs-sync | Cập nhật theo code đã ship: route `/qc/review`, wording toast/CTA thực tế, nhóm người dùng nay có màn quản lý riêng `/user-groups`
  - 2026-09-10 | /brainstorm | initial brainstorm — redesign bulk assign: cross-page selection + gán nhóm round-robin
---

# Bulk Assign — gán hàng loạt cho 1 hoặc nhiều reviewer (QC Review Queue)

> Feature: qc-queue | Idea: bulk-assign-group-redesign
> 1 feature có thể có nhiều brainstorm — đây là 1 idea/draft độc lập, mở rộng trên baseline đã có ở `baseline-from-code.md`.

## 1. Idea Seed

"Tôi muốn cải thiện tính năng Assign trong QC Review. Mục đích: QC Lead vào QC review, chọn ra 1 danh sách video cần QC, sau đó assign cho 1 group hoặc member (hiện tại chỉ assign được cho 1 người đơn lẻ). Cần thiết kế lại sao cho UX đơn giản, dễ dùng, hiệu quả cao — ví dụ: chọn 1 list video ở nhiều page thì thế nào, chọn xong mới có phần assign hay có nút assign để mở tính năng ra trước, trong lúc chọn lại muốn filter thì ra sao."

## 2. Context

QC Review Queue (`/qc/review`; URL cũ `/qc/queue` redirect về đây) hiện đã có: checkbox chọn dòng theo trang, thanh hành động (bulk bar) hiện khi có chọn, và endpoint `POST /qc/queue/assign` đã nhận **nhiều `item_ids` cùng lúc** — nhưng chỉ 1 `assignee_id` duy nhất (gán 1 người cho cả batch). "Auto-Assign Rules" là một tính năng khác, chạy nền theo rule cấu hình sẵn (round-robin tự động cho item chưa gán), không phải thao tác thủ công của QC Lead.

Pain điểm tại thời điểm brainstorm (đã xác nhận qua research code lúc đó):
- Lựa chọn (`assignSelected`) bị **xoá sạch mỗi khi đổi trang HOẶC đổi filter** — QC Lead phải chọn lại từ đầu nếu muốn gán 1 batch trải dài nhiều trang, hoặc muốn lọc thêm để tìm video khác cho cùng 1 đợt gán.
- Không có cách nào gán 1 batch cho nhiều người cùng lúc — phải lặp lại thao tác N lần (mỗi lần gán cho 1 người).

> **Cập nhật 2026-09-11 — trạng thái đã ship:** cả 2 pain điểm trên đã được xử lý, xem [[docs/review/qc-queue/brainstorms/baseline-from-code.md|baseline-from-code]] §5.2 và [[docs/review/qc-queue/srs.md|srs.md]] F-05/F-11. Khác với assumption ban đầu ở §8, "nhóm" nay **có** màn quản lý riêng `/user-groups` (module Authorization → Users Admin) — picker trong modal Gán đọc danh sách nhóm từ đó, nhưng gán vẫn là thao tác trên tập reviewer cá nhân, không phải gán cho entity nhóm.

> **Cập nhật 2026-09-22, sửa lại 2026-09-25 — phần selection:** pain điểm #1 (giữ lựa chọn qua đổi trang/filter) chỉ còn đúng một nửa — từ DP-394, bản 2026-09-25, selection **giữ nguyên khi đổi trang** nhưng **reset khi đổi filter**, vì tập dòng khớp filter đã thay đổi. Cách thay thế cho nhu cầu "gán cả tập khớp lọc" vẫn là banner **"Chọn hết"** (gom toàn bộ N id khớp filter vào selection rồi gán 1 lần). Nút mở modal Gán nằm trên thanh chọn hợp nhất `QCQueueSelectionBar`, không phải bulk bar riêng. Pain điểm #2 (gán nhiều reviewer 1 lần) vẫn đúng như đã ship. Hệ quả: tiêu chí §10 "0 lần mất lựa chọn do đổi trang/filter" đạt được cả qua tick tay xuyên trang (không đổi filter) lẫn qua "Chọn hết".

Why now: pain lặp lại nhiều lần khi khối lượng video tăng, QC Lead cần chia việc nhanh cho cả team thay vì gán tay từng người.

## 3. User Types (preliminary)

| User Type | Pain Point | Primary Need |
|-----------|-----------|--------------|
| QC Lead | Chỉ gán được cho 1 người/lần; mất lựa chọn khi đổi trang hoặc filter → phải lặp lại thao tác nhiều lần cho batch lớn/nhiều người | Gán nhanh 1 batch video (chọn xuyên nhiều trang, có thể lọc thêm giữa chừng) cho 1 hoặc nhiều reviewer cùng lúc, có kiểm soát ai nhận video nào trước khi xác nhận |
| QC Reviewer | Không đổi trong idea này — vẫn nhận video qua assignee hiện có | Không áp dụng ở P0 của redesign này |

## 4. Capabilities Breakdown

### P0 — must have
- Giữ nguyên lựa chọn video khi đổi trang **và** khi đổi filter (không tự xoá như hiện tại) — chỉ mất khi Lead chủ động bấm "Bỏ chọn" hoặc rời khỏi màn hình.
- Badge cố định "Đã chọn N mục" hiển thị dù đang lọc/xem trang nào.
- Khi Lead tick hết toàn bộ dòng hiển thị trên 1 trang → hiện banner gợi ý "Chọn cả N mục khớp bộ lọc hiện tại?" để mở rộng ra ngoài trang, không cần tick tay từng trang.
- Hợp nhất gán 1 người và gán nhiều người vào **1 modal Gán duy nhất**: picker cho tick 1 hoặc nhiều reviewer (tái dùng kiểu multi-select đã có ở Auto-Assign Rules — search + tick từng người + chọn nhanh theo group Keycloak có sẵn).
- Chọn đúng 1 người → xác nhận ngay (giữ hành vi hiện tại). Chọn ≥2 người → hệ thống tự động chia video cân bằng theo tổng thời lượng, hiện bảng preview (video ↔ người), cho Lead sửa tay từng dòng trước khi xác nhận.
- Cảnh báo phụ khi batch > 200 video trước khi xác nhận — **đã ship dưới dạng checkbox bắt buộc tick**, chưa tick thì nút Xác nhận vẫn vô hiệu.
- Khi xác nhận, video đã có người gán → bỏ qua, báo rõ số lượng, vẫn gán các video hợp lệ còn lại.
- Wording xác nhận phân biệt rõ 3 trường hợp: gán 1 người, gán nhiều người, gán thành công một phần.
- Giao diện tiếp tục nằm trong trang QC Queue hiện có, theo đúng phong cách UI hiện tại (bulk bar dưới cùng, modal mở rộng khi bấm Phân công) — không tách route riêng.

### P1 — should have
- Chọn nhanh theo nhóm có sẵn (vd `vd-qc-reviewers`) để tự động tick hết thành viên nhóm đó vào picker. **Đã ship ở P0** (commit 130fadc/e92276e): combobox search + listbox trong modal Gán, đọc `GET /api/v1/admin/users/groups`, có badge số thành viên + ngày tạo, fallback 2 nhóm mặc định khi API rỗng. Khi user có `user:manage` còn tạo được nhóm nhanh ngay trong modal.
- Filter theo `assignee_id`/`batch_id` trên chính màn Queue để dễ tìm lại đã gán cho ai (tồn đọng từ OQ-1 của SRS gốc, có liên quan trực tiếp tới tính năng này).
- Cho phép đổi chiến lược chia ngoài round-robin (vd theo tải hiện tại của từng reviewer).

### P2 — nice to have
- Nhớ "reviewer thường dùng gần đây" để gợi ý nhanh trong picker.
- Undo gán trong vài phút sau khi xác nhận.

> P0/P1/P2 là tentative; final scope chốt ở `/urd` hoặc `/prd`.

## 5. Core Flows (Happy Path)

### 5.1 Chọn video xuyên nhiều trang/filter, gán cho 1 hoặc nhiều reviewer

> **Cập nhật 2026-09-22, sửa lại 2026-09-25 — phần selection:** bước 4 dưới đây nay **đúng một phần**: tick từ trang này sang trang khác thì lựa chọn **được giữ**, chỉ đổi filter mới **reset** (DP-394), nên badge vẫn hiện xuyên trang. Muốn gom cả tập khớp filter cho 1 lượt gán thì dùng banner "Chọn hết" (nút mở modal Gán nay ở thanh chọn hợp nhất `QCQueueSelectionBar`, không phải bulk bar riêng).

1. QC Lead mở `/qc/review` (URL cũ `/qc/queue` redirect về đây), lọc theo tiêu chí cần (status/priority/project...).
2. Lead tick chọn video trên trang hiện tại (1, nhiều, hoặc tick hết trang).
3. Nếu tick hết trang → hệ thống hiện banner gợi ý "Chọn cả N mục khớp bộ lọc hiện tại?" — Lead có thể bấm để mở rộng lựa chọn ra toàn bộ kết quả khớp filter, hoặc bỏ qua và tiếp tục thủ công.
4. ~~Lead đổi sang trang khác hoặc đổi filter để tìm thêm video — lựa chọn cũ **vẫn giữ nguyên** (badge "Đã chọn N mục" luôn hiển thị).~~ → **Đúng một phần:** tick xuyên trang thì lựa chọn được giữ nguyên; đổi filter mới bị xoá (muốn gom cả tập khớp lọc thì dùng "Chọn hết" ở bước 3).
5. Lead lặp lại bước 2-4 tới khi đủ batch mong muốn.
6. Lead bấm nút **[Gán ▾]** trên thanh hành động (bulk bar hiện có) → mở modal Gán.
7. Trong modal, Lead chọn 1 hoặc nhiều reviewer (search + tick, hoặc chọn nhanh theo group có sẵn).
   - Chọn đúng 1 người → nút "Xác nhận gán" khả dụng ngay.
   - Chọn ≥2 người → hệ thống tự động chia cân bằng theo tổng thời lượng danh sách video, hiện bảng preview (video ↔ người), Lead có thể sửa tay từng dòng trước khi xác nhận.
8. Nếu batch > 200 video → hiện cảnh báo phụ "Bạn đang gán N video cùng lúc, thao tác có thể mất vài giây. Tiếp tục?".
9. Lead bấm **[Xác nhận gán]**.
10. Hệ thống kiểm tra từng video: hợp lệ (đúng quyền, chưa bị người khác gán) → gán + chuyển `pending → in_review`; không hợp lệ → bỏ qua, đếm riêng.
11. Toast kết quả: "Đã gán {N} mục cho {tên}" hoặc "cho {K} người", kèm cảnh báo nếu có mục bị bỏ qua.
12. Lựa chọn tự động clear sau khi gán xong.

```
┌──────────┐   tick chọn (giữ qua trang/filter)   ┌─────────────┐
│ QC Lead  │ ────────────────────────────────────►│ Queue Page  │
│ (Browser)│                                       │ (FE hiện có)│
└────┬─────┘                                       └──────┬──────┘
     │  tick hết trang → banner "Chọn cả N mục khớp lọc?"  │
     │◄──────────────────────────────────────────────────┘
     │  (badge "Đã chọn N mục" vẫn hiện khi đổi trang; đổi filter thì reset)
     │  bấm [Gán ▾] trên thanh hành động (bulk bar hiện có)
     ▼
┌───────────────────────────────────────────────────────────────┐
│ Modal Gán — chọn reviewer (search + tick từng người,           │
│ hoặc chọn nhanh theo group có sẵn)                              │
└───────────────────────────────┬─────────────────────────────────┘
                                │
                  ┌─────────────┴─────────────┐
           chọn 1 người?                       │
             YES  │                            │  NO (chọn ≥2 người)
                  ▼                            ▼
      [Xác nhận gán] khả dụng ngay     Tự động chia cân bằng theo thời lượng
                  │                            │
                  │                     Hiện bảng preview: video ↔ người
                  │                     Lead sửa tay từng dòng (tuỳ chọn)
                  │                            │
                  └─────────────┬──────────────┘
                                ▼
                   batch > 200 video? ──YES──► Cảnh báo phụ "gán N video,
                                │                có thể mất vài giây — tiếp tục?"
                                NO/tiếp tục
                                ▼
                        Bấm [Xác nhận gán]
                                │
                                ▼
        ┌────────────────────────────────────────────┐
        │ Backend: kiểm tra từng video                 │
        │  hợp lệ (đúng quyền, chưa bị gán) → gán +     │
        │  pending→in_review                             │
        │  không hợp lệ (đã bị gán/mất quyền) → bỏ qua   │
        └───────────────────────┬──────────────────────┘
                                 ▼
      Toast: "Đã gán {N} mục cho {tên}"  hoặc  "cho {K} người"
             (kèm cảnh báo nếu có mục bị bỏ qua: "X/Y mục — Z không gán được")
                                 │
                                 ▼
                    Selection tự động clear
```

*Baseline flow "Bulk assign" cũ (1 người, không giữ lựa chọn qua trang) — xem `baseline-from-code.md` §5.2 — được thay thế hoàn toàn bởi flow này, KHÔNG chạy song song 2 luồng.*

## 6. System Behavior Deep Dive

### 6.1 Decision Points

| ID | Flow | Khi nào | YES (nhánh đồng ý) | NO (nhánh từ chối) |
|---|---|---|---|---|
| D1 | Chọn hết trang | Lead tick hết toàn bộ dòng hiển thị trên trang hiện tại | Hiện banner gợi ý "Chọn cả N mục khớp bộ lọc?" | Giữ nguyên chỉ các dòng đã tick, không hiện banner |
| D2 | Đổi trang khi đang chọn | Lead điều hướng sang trang khác trong lúc có lựa chọn | Giữ nguyên toàn bộ lựa chọn cũ, cho chọn thêm (đổi filter thì selection bị xoá) | *(không có nhánh NO — hành vi luôn giữ)* |
| D3 | Mở modal Gán | Số reviewer Lead tick trong picker | 1 người → nút Xác nhận khả dụng ngay | ≥2 người → tự động chia cân bằng theo tổng thời lượng + hiện bảng preview cho sửa tay |
| D4 | Trước khi gửi yêu cầu gán | Số video trong batch > 200? | Hiện cảnh báo phụ, chờ Lead xác nhận tiếp tục | Bỏ qua cảnh báo, gửi yêu cầu gán ngay |
| D5 | Backend xử lý từng video lúc gán | Video còn hợp lệ tại thời điểm gán (đúng quyền, chưa bị người khác gán)? | Gán + chuyển `pending → in_review` | Bỏ qua, đếm vào số "không gán được" |

### 6.2 Scenario Matrix

| From State (phạm vi chọn) | To State (số người nhận) | Rule | Action | Result |
|------------|----------|------|--------|--------|
| Chọn tay vài dòng, trong 1 trang | 1 reviewer | — | Gán trực tiếp | Giống hành vi hiện tại, không đổi |
| Chọn tay nhiều dòng, trải nhiều trang | 1 reviewer | — | Gán trực tiếp cho toàn batch | 1 người nhận hết N video |
| Chọn tay nhiều dòng, trải nhiều trang | ≥2 reviewer | cân bằng theo tổng thời lượng | Tự động chia + hiện bảng cho sửa tay | Tổng thời lượng mỗi người xấp xỉ nhau (số video có thể lệch), có thể lệch thêm do Lead sửa tay |
| Chọn "tất cả N mục khớp bộ lọc" (qua banner) | 1 reviewer | — | Gán trực tiếp cho toàn bộ N mục | Cảnh báo phụ nếu N > 200 (D4) |
| Chọn "tất cả N mục khớp bộ lọc" (qua banner) | ≥2 reviewer | cân bằng theo tổng thời lượng | Tự động chia + hiện bảng cho sửa tay | Cảnh báo phụ nếu N > 200 (D4) |
| Bất kỳ phạm vi nào ở trên | Lúc xác nhận, có video đã bị người khác gán trước | D5 | Bỏ qua video đó, vẫn gán các video còn lại | Toast báo "X/Y mục — Z mục không gán được" |

### 6.5 Other Edge Cases

- **2 QC Lead thao tác trùng cùng lúc**: cùng chọn trùng 1 số video, ai xác nhận gán trước "thắng"; người xác nhận sau nhận cảnh báo theo D5 (một số video đã được gán bởi người khác).
- **Rời trang/đóng tab giữa chừng** (trước khi bấm Xác nhận gán): lựa chọn mất, không có server-side draft lưu lại — chấp nhận được vì thao tác chưa commit, không phát sinh dữ liệu treo.
- **Danh sách reviewer rỗng hoặc tất cả đã đầy tải**: picker hiện wording đã có "Không có reviewer khả dụng" (giữ nguyên từ tính năng Auto-Assign hiện tại).
- **Batch còn 0 video hợp lệ sau khi lọc bỏ**: chặn xác nhận ngay tại modal, không gọi API.

## 7. Validation, Limits & Wording

### 7.1 Validation rules

| Field | Rule |
|---|---|
| Danh sách reviewer trong modal Gán | Tối thiểu 1 người được chọn mới bật nút "Xác nhận gán" |
| Batch video | Tối thiểu 1 video hợp lệ còn lại; batch = 0 sau khi lọc bỏ video không hợp lệ → chặn xác nhận |

### 7.2 Limits & Quotas (exact values)

| Tham số | Giá trị | Window | Behavior khi vượt |
|---|---|---|---|
| Ngưỡng cảnh báo batch lớn | 200 video | mỗi lần gán | Hiện dialog cảnh báo phụ, chờ Lead xác nhận tiếp tục |
| Giới hạn API hiện tại (không đổi trong idea này) | 500 item/lần gọi | mỗi request | Batch vượt 500 (thường do "chọn tất cả theo lọc" trên tập rất lớn) — hành vi CHƯA quyết, xem OQ-1 |

### 7.3 Wording samples (exact strings)

#### Error messages

| Tình huống | Wording | Code |
|---|---|---|
| Chưa chọn reviewer nào trong modal | "Chọn ít nhất 1 người để gán" | E-? |
| Không còn video hợp lệ để gán (batch = 0 sau lọc) | "Không còn video nào hợp lệ để gán" | E-? |
| Gán thất bại toàn bộ (lỗi hệ thống) | "Gán thất bại" *(giữ nguyên wording hiện có)* | E-? |

#### Success messages

| Tình huống | Wording |
|---|---|
| Gán cho 1 người, tất cả thành công | "Đã gán {N} mục cho {tên}" *(giữ nguyên wording hiện có)* |
| Gán cho nhiều người, tất cả thành công | "Đã gán {N} mục cho {K} người" |
| Gán thành công một phần | "Đã gán {X}/{Y} mục — {Z} mục không gán được (đã được gán bởi người khác hoặc không còn khớp)" |

#### Info / neutral messages

| Tình huống | Wording |
|---|---|
| Gợi ý chọn tất cả theo bộ lọc (sau khi tick hết trang) | "Đã chọn {số lượng trên trang} mục trên trang này. Chọn cả {N} mục khớp bộ lọc?" |
| Cảnh báo batch lớn trước khi xác nhận | "Bạn đang gán {N} video cùng lúc, thao tác có thể mất vài giây. Tiếp tục?" |
| Badge lựa chọn hiện tại | "Đã chọn {N} mục" |

## 8. Assumptions

- Quyền `qc:assign` không đổi — chỉ QC Lead/role tương đương (đã có quyền này) mới thấy nút Phân công; không cần permission mới. Việc tạo/quản lý nhóm dùng `user:manage` có sẵn.
- Thuật toán chia ở V1 **cân bằng theo tổng thời lượng** (item dài nhất xét trước, gán cho reviewer đang ít tổng thời lượng nhất; hoà thì ưu tiên người ít video hơn), KHÔNG cân nhắc tải hiện tại của từng reviewer — bảng preview cho sửa tay là cách bù ở V1.
- "Group" ở V1 = tập hợp reviewer được Lead chọn thủ công trong picker, mồi nhanh bằng cách chọn theo 1 nhóm có sẵn trong danh sách nhóm (`GET /api/v1/admin/users/groups`) — vẫn KHÔNG gán cho entity nhóm, mỗi item nhận 1 reviewer cá nhân.
- ~~KHÔNG phải một entity "Team" mới cần màn quản lý riêng~~ → **Đã thay đổi (code 2026-09-11):** có màn quản lý nhóm riêng `/user-groups` (module Authorization → Users Admin); picker chỉ tiêu thụ dữ liệu nhóm đó.
- Giao diện tiếp tục nằm trong trang QC Queue hiện có (`/qc/review`), giữ đúng phong cách UI hiện tại (thanh chọn trên bảng, style bảng) — không tách route/màn riêng cho luồng gán.
- Lựa chọn (selection) vẫn là state phía client, không lưu server-side draft — **reset khi đổi filter**, giữ nguyên khi đổi trang (DP-394), và mất khi rời trang/tab trước khi xác nhận.
- Flow "Bulk assign" cũ (1 người, không giữ chọn qua trang) được thay thế hoàn toàn, không giữ song song 2 luồng.

## 9. Risks

| Rủi ro | Khả năng | Hậu quả nghiệp vụ | Cách phòng |
|--------|----------|-------------------|-----------|
| Chia theo tổng thời lượng nhưng không tính tải hiện tại của từng reviewer | Thường | 1 reviewer đang quá tải vẫn nhận thêm khối lượng tương đương người rảnh → tiến độ QC tổng thể chậm hơn kỳ vọng | Bảng preview bắt buộc hiển thị + cho sửa tay từng dòng trước khi xác nhận; roadmap P1 tính theo tải hiện tại |
| QC Lead quen thao tác cũ (chỉ 1 người), bấm nhầm chọn nhiều người khi chỉ định gán 1 người cụ thể cho từng video khác nhau | Thỉnh thoảng | Video bị gán sai người, phải sửa lại thủ công, làm chậm bàn giao review | Bảng preview luôn hiển thị khi ≥2 người được chọn, cho sửa tay trước khi xác nhận — không có bước "gán mù" |
| Batch từ "chọn tất cả theo bộ lọc" vượt giới hạn API hiện tại (500 item/lần gọi) | Hiếm nhưng có thể xảy ra khi bộ lọc rất rộng | Gán thất bại hoặc phải chia nhiều lần thao tác, trải nghiệm gián đoạn, mất niềm tin vào tính năng mới | Đánh OQ-1, cần `/srs` quyết định hướng xử lý trước khi launch |
| 2 QC Lead thao tác trùng video cùng lúc | Hiếm | 1 người bị "gán hụt" một số video, phải kiểm tra lại danh sách | Wording rõ ràng báo số lượng bị bỏ qua + lý do (đã có ở D5) |

## 10. Success Criteria (preliminary)

- Giảm số lần thao tác cần thiết để gán N video cho nhiều người: từ N lần gán đơn lẻ (hiện tại) xuống 1 lần gán hàng loạt duy nhất.
- QC Lead hoàn tất 1 batch gán trải dài ≥3 trang mà không phải chọn lại từng trang một (đạt được qua đường "Chọn hết" của banner, **không** qua tick tay xuyên trang — xem ghi chú §2).
- Thời gian hoàn tất 1 lượt gán 50-200 video (cho nhiều người) dưới 5 giây kể từ lúc bấm Xác nhận gán.

## 11. Open Questions

- [ ] OQ-1: Batch từ "chọn tất cả theo bộ lọc" có thể vượt giới hạn API hiện tại (max 500 item/lần gọi) — tăng limit hay tự động chia nhiều lệnh gọi ngầm ở tầng FE/BE?
- [ ] OQ-2: Round-robin V1 có cần loại trừ reviewer đang nghỉ phép/không active không, hay chỉ dựa trên danh sách "khả dụng" đã có sẵn từ Auto-Assign Rules?
- [ ] OQ-3: Có cần audit log (ai gán, khi nào, cho ai) riêng cho hành động bulk-assign nhóm không — hiện tại hệ thống chưa log riêng hành động assign nào?

## 12. Next Steps

Sau brainstorm này (sau khi BA approve):
- `/urd qc-queue` — capture user perspective, chốt formal user story cho tính năng gán nhóm này
- `/srs qc-queue` (hoặc update `srs.md` hiện có) — đặc tả kỹ thuật: API contract chia cân bằng theo tổng thời lượng, xử lý OQ-1 (limit 500), audit log (OQ-3)

*KHÔNG nhảy thẳng SRS — qua URD trước để chốt góc nhìn nghiệp vụ.*
