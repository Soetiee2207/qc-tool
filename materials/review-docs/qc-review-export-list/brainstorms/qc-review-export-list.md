---
type: brainstorm
feature: review/qc-review-export-list
idea_slug: qc-review-export-list
status: draft
mode: deep
lang: vi
owner: binhhm
created: 2026-09-03
updated: 2026-09-25
last_modified_by: binhhm
complexity_flags: [has_multi_role]
links:
  - frontend/src/features/qc/QCQueue.tsx
  - frontend/src/features/qc/QCQueueTable.tsx
tags: [brainstorm, qc-review-export-list, qc-review-module]
stale_reason: ""
changelog:
  - 2026-09-25 | docs-sync | Sửa kết luận 2026-09-22: selection chỉ reset khi đổi filter; sang trang vẫn giữ (DP-394)
  - 2026-09-22 | docs-sync | Trạng thái đã ship khác đề xuất gốc: bỏ nút Export header + bulk bar, "Xuất tất cả" chạy nền, selection không còn cross-page — xem ghi chú §4
  - 2026-09-03 | /brainstorm | initial brainstorm — QC Review list export Excel/CSV, deep mode, 3 OQs flagged
  - 2026-09-03 | /brainstorm | resolved OQ-1,OQ-2,OQ-3: cross-page UX, CSV UTF-8 BOM, audit log P1
  - 2026-09-03 | /brainstorm | rename feature slug qc-review → qc-review-export-list (function trong QC Review Listing)
---

# Export — QC Review List (Excel/CSV)

> Feature: qc-review-export-list | Idea: qc-review-export-list
> Function spec độc lập — nằm trong **QC Review Listing** (màn queue list), thuộc **QC Review Module**.

## 1. Idea Seed

Build **Export function** on QC Review list screen. Output: **Excel/CSV**. Chỉ cho phép **QC Lead**, **Platform Administrator**, và **Project Administrator** (theo phạm vi project). Mục tiêu: audit trail offline — QC lead / admin tải danh sách QC Review ra file để báo cáo và đối soát ngoài portal.

*Raw input từ user — export danh sách trên QC Review list, không giới hạn số dòng, user filter và download tự do.*

## 2. Context

- **Phân cấp sản phẩm:**
  - **Module:** QC Review
  - **Màn hình cha:** QC Review Listing (queue list — `QCQueue`)
  - **Function (doc này):** Export danh sách ra Excel/CSV
- **Why now:** Cần ngay — team QC / ops cần báo cáo offline mà không phụ thuộc màn hình portal.
- **Scope:** Áp dụng trên QC Review list cho mọi project và mọi QC type (final QC, annotation QC, Tapdata QC) — `/qc/queue` và biến thể mode.
- **Entry point:** QC Review **list** — export dữ liệu đang hiển thị / đã chọn trên list, không export từ màn detail.
- **Tham chiếu UI hiện tại:** `QCQueue` + `QCQueueTable` — đã có checkbox selection và bulk assign pattern.

## 3. User Types (preliminary)

| User Type | Pain Point | Primary Need |
|-----------|-----------|--------------|
| QC Lead | Không có file offline để báo cáo / đối soát batch QC | Export toàn bộ hoặc subset danh sách QC ra Excel/CSV |
| Platform Administrator | Cần audit trail cross-project | Export mọi project trong phạm vi portal |
| Project Administrator | Cần báo cáo trong phạm vi project được gán | Export chỉ project họ có quyền truy cập |
| QC Reviewer | — | **Không có quyền** — không thấy nút Export |

## 4. Capabilities Breakdown

> **Trạng thái đã ship (2026-09-22, sửa 2026-09-25) khác đề xuất dưới đây ở 3 điểm:** (1) không có nút **Export** trên toolbar/header lẫn bulk bar riêng — điểm vào duy nhất là thanh chọn hợp nhất `QCQueueSelectionBar`, chỉ render khi đã tick ≥1 dòng; (2) selection **reset khi đổi filter/project** nhưng **giữ khi sang trang** (DP-394); (3) "export toàn bộ khớp filter" chạy **job nền** rồi FE poll, không còn đồng bộ. Các mục P0/P1 dưới đây giữ nguyên như **đề xuất gốc** để đối chiếu, không phải mô tả hiện trạng.

### P0 — must have

- Nút **Export** trên QC Review list — chỉ hiện với QC Lead, Platform Administrator, Project Administrator.
- Export **Excel (.xlsx)** (mặc định) hoặc **CSV**.
- **Selection persists** khi user đổi filter hoặc chuyển trang — có thể chọn dòng ở nhiều trang / nhiều filter khác nhau, gom export một lần.
- Quy tắc phạm vi:
  - Có ≥1 dòng được chọn → export **chỉ các dòng đã chọn** (theo ID, không phụ thuộc filter hiện tại).
  - Không chọn dòng nào → export **toàn bộ kết quả khớp filter hiện tại** (mọi trang, không giới hạn số dòng).
- Dialog xác nhận trước download — preview số dòng + chọn format.
- Export **đồng bộ** — user chờ trên màn (`"Preparing export…"`) đến khi file tải xong.
- Tên file: `qc-review-export-YYYY-MM-DD.xlsx` (hoặc `.csv`).
- Cột v1: giống màn hình list + cột audit đề xuất (xem Mục 5).
- **Phân quyền theo project:**
  - QC Lead + Platform Administrator → export **mọi project**.
  - Project Administrator → chỉ export item thuộc project họ được phép truy cập (server enforce, không tin client).
- Nút Export **ẩn hoàn toàn** với user không đủ quyền.

### P1 — should have

- **Audit log export (v1 = P1)** — lưu: ai export, thời điểm, số dòng, loại phạm vi (selected / filtered). Không chặn download nếu chưa có log.
- **Selection toolbar (khi ≥1 dòng được chọn):** bulk bar phía trên bảng hiện badge `"{N} selected"`, nút **Clear selection**, và nút **Export** cạnh nhau (pattern giống bulk assign hiện tại).
- Warning khi export >10.000 dòng: `"This may take a while"` — vẫn cho phép tiếp tục.

### P2 — nice to have

- User **chọn field** muốn export (column picker).
- Sheet metadata riêng trong Excel (filter snapshot, exported_by, exported_at).

> P0/P1/P2 là tentative; final scope chốt ở `/prd qc-review-export-list`.

## 5. Core Flows (Happy Path)

### 5.1 Export từ QC Review list (authorized user)

> **Cập nhật 2026-09-22:** flow dưới đây là **đề xuất gốc 2026-09-03**; các bước về tick xuyên trang và nút Export trên toolbar/bulk bar không còn đúng — xem ghi chú §4.

1. User (QC Lead / Platform Administrator / Project Administrator) mở QC Review list, áp dụng filter tùy ý (project, status, date range, priority, search…).
2. User tick checkbox trên một hoặc nhiều dòng — có thể đổi filter / sang trang khác và tiếp tục tick thêm (selection được giữ). Khi có selection, bulk bar hiện `"{N} selected"`, **Clear selection**, và **Export**.
3. User bấm **Export** (từ bulk bar khi có selection, hoặc từ toolbar list khi không có selection).
4. System kiểm tra có dòng để export không:
   - Nếu 0 selected AND 0 filtered → hiện `"No items to export"`, dừng.
   - Nếu >10.000 dòng → hiện warning `"This may take a while"`, user có thể tiếp tục hoặc hủy.
5. System hiện dialog: chọn format (Excel mặc định / CSV) + xác nhận số dòng:
   - Có selection: `"Export {N} selected items. Continue?"`
   - Không selection: `"Export {N} items matching current filters. Continue?"`
6. User bấm **Continue** — nút/dialog hiện `"Preparing export…"`.
7. System build file (server enforce project scope theo role), trả file về browser.
8. Browser download `qc-review-export-YYYY-MM-DD.xlsx` (hoặc `.csv`).

```
┌─────────────────────────────────────────────────────────────────┐
│  QC Review List (QC Lead / Administrator only sees Export btn)  │
└─────────────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────┐     filter / paginate / tick rows (selection persists)
│  User works on  │──── across pages & filter changes
│  list           │
└────────┬────────┘
         │ click [Export]
         ▼
┌─────────────────┐     NO                          YES
│ Any rows to     │─────────────────────────────► Show dialog
│ export?         │         (0 selected AND          │
│                 │          0 filtered)            │
└────────┬────────┘                               │
         │ NO                                       ▼
         ▼                              ┌──────────────────────┐
┌─────────────────┐                    │ >10k rows?           │
│ Alert:          │                    │ → warning (optional  │
│ "No items to    │                    │   continue)          │
│  export"        │                    └──────────┬───────────┘
└─────────────────┘                               │
                                                  ▼
                                       ┌──────────────────────┐
                                       │ Dialog:              │
                                       │ • Format: Excel (def)  │
                                       │   or CSV               │
                                       │ • Scope preview:       │
                                       │   N selected OR        │
                                       │   M filtered (all pg)  │
                                       │ • [Continue]           │
                                       └──────────┬───────────┘
                                                  │
                                                  ▼
                                       ┌──────────────────────┐
                                       │ "Preparing export…"    │
                                       │ (sync — user waits)    │
                                       └──────────┬───────────┘
                                                  │
                              ┌───────────────────┴───────────────────┐
                              │ SUCCESS                               │ FAIL
                              ▼                                       ▼
                   ┌─────────────────┐                    ┌─────────────────┐
                   │ Browser download│                    │ "Export failed. │
                   │ qc-review-export│                    │  Please try     │
                   │ -YYYY-MM-DD.xlsx│                    │  again or narrow│
                   └─────────────────┘                    │  your filters." │
                                                            └─────────────────┘
```

### 5.2 Cột export v1

**Giống màn hình list:**

| # | Cột | Ghi chú |
|---|-----|---------|
| 1 | QC Item ID | Đối soát nội bộ |
| 2 | Upload ID | |
| 3 | Filename | |
| 4 | Project | Tên project |
| 5 | Duration | |
| 6 | Status | |
| 7 | Reject reason | Khi status = rejected |
| 8 | Priority | |
| 9 | Assignee | |
| 10 | Created at | |

**Thêm cho audit trail offline:**

| # | Cột | Lý do |
|---|-----|-------|
| 11 | Project ID | Đối soát khi trùng tên project |
| 12 | Batch ID | Nếu có batch |
| 13 | Reject comment | Chi tiết từ chối |
| 14 | Last reviewed at | Thời điểm QC cuối |
| 15 | Last reviewed by | Người review cuối |
| 16 | QC type | final_qc / annotation / tapdata |
| 17 | Tags | Nếu có |

**Metadata export (P2 — sheet riêng hoặc header row):** `exported_at`, `exported_by`, `filter_applied`.

## 6. System Behavior Deep Dive

### 6.1 Decision Points

| ID | Flow | Khi nào | YES (nhánh đồng ý) | NO (nhánh từ chối) |
|---|---|---|---|---|
| D1 | Mở list | User có role QC Lead, Platform Administrator, hoặc Project Administrator? | Hiện nút Export | Ẩn nút Export hoàn toàn |
| D2 | Bấm Export | Có ≥1 dòng selected HOẶC filter có kết quả? | Mở dialog export | Hiện `"No items to export"` |
| D3 | Dialog | User đã chọn ≥1 dòng (selection)? | Export theo selected IDs | Export toàn bộ filtered (all pages) |
| D4 | Dialog | Số dòng >10.000? | Hiện warning `"This may take a while"`, user có thể Continue | Bỏ qua warning, tiếp tục bình thường |
| D5 | Build file | User là Project Administrator? | Chỉ include item thuộc project được phép | Include theo scope role (all projects cho QC Lead / Platform Admin) |
| D6 | Build file | Server build thành công? | Browser download file | Hiện `"Export failed. Please try again or narrow your filters."` |

### 6.2 Scenario Matrix

| From State | User action | Rule | Action | Result |
|------------|-------------|------|--------|--------|
| QC Lead | Export, ≥1 selected | Selection wins | Build file từ selected IDs | Download N rows |
| Platform Administrator | Export, 0 selected, filter có kết quả | All filtered, all pages | Query toàn bộ filtered | Download M rows |
| Project Administrator | Export, filtered có item ngoài phạm vi | Server filter theo project access | Loại bỏ / không trả item không được phép | Download chỉ item trong scope |
| QC Lead / Administrator | Export, 0 selected, 0 kết quả | Block | Không build file | `"No items to export"` |
| QC Reviewer | View list | Không có export permission | — | Export button hidden |
| Authorized user | Chọn rows ở page 1, đổi filter, chọn thêm ở page 2 | Selection persists cross-page/filter | Export gom tất cả selected IDs | Download tổng selected |
| Authorized user | >10.000 rows | Soft warning | User confirm Continue | Download (có thể chậm) |
| Authorized user | Mất mạng giữa export | Không resume | User bấm Export lại | Retry từ đầu hoặc error message |

### 6.5 Other Edge Cases

| Tình huống | Hành vi |
|---|---|
| User đóng tab khi `"Preparing export…"` | Coi như hủy — không resume, không file |
| 2 user export cùng lúc | Cho phép song song — không lock |
| Mất kết nối giữa chừng | Hiện `"Export failed. Please try again or narrow your filters."` — user retry |
| Selection chứa item user mất quyền (edge admin) | Server loại item không hợp lệ; nếu 0 còn lại → `"No items to export"` |
| Filter đổi sau khi tick — item cũ không còn trên list | Selection vẫn giữ theo ID — vẫn export được nếu user có quyền |
| Export CSV có ký tự tiếng Việt | CSV dùng **UTF-8 with BOM** — Excel Windows mở đúng dấu tiếng Việt |

## 7. Validation, Limits & Wording

### 7.1 Validation rules

| Field / Rule | Validation |
|---|---|
| Export permission | Chỉ QC Lead, Platform Administrator, Project Administrator |
| Project scope | Project Administrator — server chỉ trả item thuộc project được phép |
| Empty export | 0 selected AND 0 filtered → block |
| Selected IDs | Phải tồn tại và user có quyền đọc từng item |
| Format | Excel (.xlsx) hoặc CSV — user chọn trong dialog |
| CSV encoding | UTF-8 **with BOM** (Excel Windows đọc tiếng Việt đúng) |

### 7.2 Limits & Quotas (exact values)

| Tham số | Giá trị | Window | Behavior khi vượt |
|---|---|---|---|
| Max rows per export | **Không giới hạn** (hard cap) | — | Cho phép export toàn bộ filtered/selected |
| Large export warning | **10.000 dòng** | per export | Hiện warning `"This may take a while"` — user vẫn có thể Continue |
| Rate limit export | <!-- TBD --> | — | Không chốt trong brainstorm — đề xuất không rate limit v1 (volume thấp) |
| Selection cross-page | **Không giới hạn** | — | User tick tự do; UI hiện badge count |

### 7.3 Wording samples (exact strings)

#### Error messages

| Tình huống | Wording | Code |
|---|---|---|
| Không có dòng để export | "No items to export" | E-EXPORT-EMPTY |
| Server / network fail | "Export failed. Please try again or narrow your filters." | E-EXPORT-FAIL |

#### Success messages

| Tình huống | Wording |
|---|---|
| *(Không dùng toast — chỉ browser download)* | — |

#### Info / neutral messages

| Tình huống | Wording |
|---|---|
| Dialog confirm — filtered | "Export {N} items matching current filters. Continue?" |
| Dialog confirm — selected | "Export {N} selected items. Continue?" |
| Loading state | "Preparing export…" |
| Large export warning | "This may take a while" |
| Selection badge | "{N} selected" |
| Clear selection button | "Clear selection" |

## 8. Assumptions

> **Cập nhật 2026-09-22:** các assumption về selection cross-page và "không job nền" dưới đây **không còn đúng** — xem ghi chú §4.

- Volume export **không nhiều** — chủ yếu QC lead / admin dùng thỉnh thoảng.
- User hiểu: có tick → export selected; không tick → export all filtered.
- QC Review list API đã có đủ field cho cột export (hoặc backend bổ sung trong implementation).
- ~~Selection cross-page là **behavior mới** — khác với hiện tại (list clear selection khi đổi filter); cần implement riêng cho export use case.~~ → **Cập nhật 2026-09-25:** code clear selection khi **đổi filter/project** nhưng **giữ** khi chỉ sang trang (DP-394).
- ~~Chỉ download trình duyệt — không email, không S3 link, không job nền.~~ → **Cập nhật:** kênh phân phối vẫn chỉ là download trình duyệt, nhưng "Xuất tất cả" nay dùng job nền nội bộ portal để dựng file (DP-382).
- `"Administrator"` = role có `platform_admin` hoặc `project_admin` trong portal RBAC; QC Lead = `qc_lead`.
- CSV export dùng **UTF-8 with BOM** — ưu tiên tương thích Excel Windows cho tiếng Việt.
- Audit log export là **P1** cho v1 — ship export download trước, log audit follow ngay sau.
- Doc scope là **function** Export — không phải toàn bộ QC Review Module; màn listing và các function khác có doc riêng.

## 9. Risks

| Rủi ro | Khả năng | Hậu quả nghiệp vụ | Cách phòng |
|--------|----------|-------------------|-----------|
| File quá lớn làm treo trình duyệt / chờ lâu | Thỉnh thoảng | QC lead mất thời gian, phải export lại hoặc thu hẹp filter | Warning >10.000 dòng; khuyến khích filter nhỏ hơn |
| Project Administrator export nhầm / vượt phạm vi | Hiếm | Rò rỉ dữ liệu project không được phép — vi phạm compliance | Server enforce project scope; audit log (P1) |
| User nhầm selected vs all filtered | Thỉnh thoảng | Báo cáo sai tập dữ liệu — quyết định QC ops sai | Dialog preview số dòng rõ ràng; badge selection count |
| Selection cross-page gây confusion | Thỉnh thoảng | User export dòng không mong muốn | Nút Clear selection + badge `{N} selected` |
| Audit log chưa kịp ship cùng export v1 | Thỉnh thoảng | Không truy vết ai đã tải dữ liệu ra ngoài trong giai đoạn đầu | Audit log đã chốt P1 — ưu tiên ngay sau P0 export |

## 10. Success Criteria (preliminary)

- QC Lead / Administrator export được danh sách QC ra Excel/CSV trong **một lần thao tác** (filter → export hoặc select → export).
- **100%** export của Project Administrator không chứa item ngoài project được phép (verify bằng test case).
- QC Reviewer **không thấy** nút Export trên mọi QC list mode.
- Thời gian export <30 giây cho batch ≤1.000 dòng (mục tiêu UX, không hard SLA).

## 11. Open Questions

- [x] OQ-1: UX chi tiết selection cross-page — **Resolved:** bulk bar phía trên bảng khi ≥1 selected; hiện badge `"{N} selected"`, nút `"Clear selection"`, và `"Export"` cạnh nhau. Không giới hạn hiển thị số trên badge.
- [x] OQ-2: CSV encoding — **Resolved:** UTF-8 **with BOM** (Excel Windows mở đúng tiếng Việt).
- [x] OQ-3: Audit log export — **Resolved:** **P1** cho v1 (không chặn ship P0 export download).

## 12. Next Steps

Sau brainstorm này (sau khi BA approve):
- `/urd qc-review-export-list` — capture user perspective cho function Export
- `/brd qc-review-export-list` — business case
- `/prd qc-review-export-list` — product scope

*KHÔNG nhảy thẳng SRS — qua PRD trước.*
