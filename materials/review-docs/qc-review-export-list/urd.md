<!-- doc-meta: type=urd | feature=review/qc-review-export-list | status=draft | updated=2026-09-22 -->
# **User Requirement** Documentation

Export — QC Review List (Excel/CSV)

Version 1.3  |  2026-09-22

|  |  |  |  |
| --- | --- | --- | --- |
| **Version**  | **Date**  | **Author**  | **Changes**  |
| 1.3  | 2026-09-22  | @binhhm  | Export "tất cả" chạy nền; bỏ nút Xuất header; selection reset theo filter/trang |
| 1.2  | 2026-09-11  | binhhm  | Đối chiếu code: nút **Xuất** ở header chỉ bật chế độ chọn-để-xuất (không export ngay); trong chế độ xuất có 2 nút hành động "Xuất theo lựa chọn" / "Xuất tất cả {N} mục khớp lọc" + "Hủy"; bỏ mô tả bulk bar `{N} selected` / `Clear selection` |
| 1.1  | 2026-09-10  | binhhm  | Sửa US-002 Business Rules: Export là chế độ chọn riêng (loại trừ với chế độ Gán bên qc-queue), không còn "khác behavior assign" |
| 1.0  | 2026-09-03  | binhhm  | Initial draft từ brainstorm qc-review-export-list |

**Table of Contents**

1. **INTRODUCTION**

**1.1. Purpose**

- Tài liệu này viết cho PO, BA, dev frontend/backend, QA — stakeholder triển khai function **Export** trên màn QC Review Listing.
- Phục vụ mục tiêu: baseline yêu cầu nghiệp vụ (ai export được gì, luồng thao tác, wording, phân quyền) làm đầu vào cho `/srs` và QC.
- Phạm vi: v1 function Export Excel/CSV trên QC Review list — ship cùng QC Review Module hiện tại.

**1.2. Scope**

- **IN SCOPE:**
  - Hai nút Export trên **thanh chọn** của màn **QC Review Listing** (route thật: `/qc/review` cho final QC, `/qc/annotation` cho annotation QC) — thanh này chỉ hiện khi đã tick ≥1 dòng. Biến thể Tapdata QC (`/tapdata/qc/queue`) hiện chỉ redirect về `/qc/review` — chưa có queue Tapdata riêng.
  - Export **Excel (.xlsx)** mặc định hoặc **CSV** (UTF-8 with BOM).
  - Hai chế độ phạm vi: (1) export toàn bộ kết quả khớp filter hiện tại — mọi trang; (2) export các dòng đã tick checkbox trên trang hiện tại.
  - Dialog xác nhận trước download (preview số dòng + chọn format).
  - **Export "Xuất tất cả" chạy nền**: server xếp job rồi dựng file ở worker; user vẫn chờ trong dialog cho tới khi file tải về (không có thông báo "xong sau"). **"Xuất theo lựa chọn"** vẫn đồng bộ.
  - Phân quyền: QC Lead + Platform Administrator (mọi project); Project Administrator (chỉ project được phép); QC Reviewer không thấy 2 nút Export. Backend còn chặn thêm bằng SSO group allowlist.
  - Cột export v1: cột hiển thị trên list + cột audit bổ sung (xem US-001 Business Rules).
  - Audit log export (đã ship): sự kiện `qc.queue.export` ghi `row_count`, `scope`, `format`.
- **OUT OF SCOPE:**
  - Export từ màn **QC Review detail** (chỉ list).
  - Gửi file qua email, S3 link, Slack — chỉ download trình duyệt.
  - Thông báo "export ready sau" / màn danh sách job để tải lại — user chờ trong dialog.
  - User chọn field export (column picker) — P2, version sau.
  - Hard cap số dòng mỗi lần export — v1 không giới hạn (có soft warning >10.000 dòng).
  - Thay đổi logic review Pass/Reject, assign, filter list ngoài phần cần cho export.
- **Integration boundary:** Không gọi dịch vụ bên thứ ba; hệ thống đọc dữ liệu QC queue nội bộ portal và sinh file tại server.

**1.3. Definitions and Acronyms**

|  |  |
| --- | --- |
| **Term / Acronym**  | **Definition**  |
| **URD** | User Requirement Documentation |
| **QC Review Module** | Module review chất lượng video trên portal (queue + detail) |
| **QC Review Listing** | Màn danh sách hàng chờ QC — bảng filter + checkbox + pagination |
| **QC Lead** | Trưởng nhóm QC — export được mọi project |
| **Platform Administrator** | Quản trị viên nền tảng — export được mọi project |
| **Project Administrator** | Quản trị viên project — export chỉ item thuộc project được phép |
| **Selection (theo trang)** | Tập dòng user đã tick checkbox; **reset** khi đổi filter hoặc chuyển trang — muốn export cả tập khớp lọc thì dùng nút "Xuất tất cả" thay vì tick tay nhiều trang |

## 2. System Overview

### 2.1 High-Level User Flow

1. User có quyền export (QC Lead / Platform Administrator / Project Administrator) mở **QC Review Listing**.
2. User áp dụng filter (project, status, ngày, priority, tìm kiếm…) và/hoặc tick checkbox trên trang hiện tại.
3. User bấm **"Xuất theo lựa chọn"** (các dòng đã tick) hoặc **"Xuất tất cả {N} mục khớp lọc"** (theo filter) trên thanh chọn.
4. Hệ thống hiện dialog xác nhận: chọn Excel/CSV, preview số dòng; nếu >10.000 dòng hiện warning `"Việc này có thể mất một lúc"`.
5. User bấm **Tiếp tục** — nút hiện `"Đang chuẩn bị xuất…"`. Với "Xuất tất cả", hệ thống xếp job và dựng file ở worker nền nên user chờ lâu hơn; khi xong, trình duyệt tải `qc-review-export-YYYY-MM-DD.xlsx` (hoặc `.csv`) và hệ thống xóa selection.
6. User dùng file offline để báo cáo / đối soát.

### 2.2 System User Profile

|  |  |  |  |
| --- | --- | --- | --- |
| **User Role**  | **Description**  | **Permission Level**  | **Key Actions**  |
| QC Lead  | Trưởng nhóm QC  | Export mọi project trên QC Review list  | Filter list, chọn dòng, export Excel/CSV  |
| Platform Administrator  | Quản trị nền tảng  | Export mọi project  | Filter list, chọn dòng, export Excel/CSV  |
| Project Administrator  | Quản trị project được gán  | Export chỉ item thuộc project trong phạm vi quyền  | Filter list, chọn dòng, export Excel/CSV  |
| QC Reviewer  | Nhân viên review QC  | Không có quyền export  | Xem list, mở review — **không thấy** 2 nút Export trên thanh chọn  |

## 3. User Stories

### 3.1 User Story List

| **US Code** | **US Name** | **US Description** |
| --- | --- | --- |
| US-001 | Export danh sách theo filter | Export toàn bộ item khớp filter hiện tại (mọi trang) ra Excel/CSV |
| US-002 | Export các dòng đã chọn | Export chỉ các dòng đã tick trên trang hiện tại |
| US-003 | Phân quyền export theo role | Chỉ QC Lead / Administrator thấy Export; Project Admin bị giới hạn phạm vi project |
| US-004 | Dialog xác nhận và xử lý lỗi | Dialog chọn format, confirm số dòng, warning lớn, thông báo lỗi/empty |

### 3.2 User Story Detail

#### 3.2.1 US-001 Export danh sách theo filter

**Story**

**As a** `QC Lead` **I want** `export toàn bộ danh sách QC khớp bộ lọc hiện tại ra file Excel hoặc CSV` **So that** `tôi có báo cáo offline để đối soát mà không cần copy từng trang trên portal`

**Acceptance Criteria**

- **AC 1 (Happy path — export filtered):**
    - **Given** tôi là QC Lead hoặc Platform Administrator, QC Review list có ≥1 item khớp filter hiện tại và tôi **không** tick dòng nào,
    - **When** tôi tick 1 dòng bất kỳ để thanh chọn hiện ra, rồi bấm **"Xuất tất cả {N} mục khớp lọc"**, chọn Excel trong dialog và bấm **Tiếp tục**,
    - **Then** dialog hiện `"Xuất {N} mục khớp bộ lọc hiện tại. Tiếp tục?"`; file `qc-review-export-YYYY-MM-DD.xlsx` chứa **tất cả** item khớp filter (mọi trang, không chỉ trang hiện tại) và được dựng bởi job nền — nút vẫn ở trạng thái `"Đang chuẩn bị xuất…"` đến khi file tải xong.
- **AC 2 (Edge — không có dòng):**
    - **Given** filter hiện tại không trả kết quả nào,
    - **When** tôi nhìn màn list,
    - **Then** không có dòng nào để tick nên **thanh chọn không render** (nó chỉ hiện khi `assignSelected.size > 0`) — do đó không có nút "Xuất tất cả" để bấm; trạng thái disabled khi `filteredTotal === 0` chỉ là lớp phòng vệ trong component.

**Business Requirement Table**

|  |  |
| --- | --- |
| **User Story** | US-001 Export danh sách theo filter |
| **Description**  | Export toàn bộ kết quả filter (all pages); file dựng ở job nền |
| **Actor**  | QC Lead, Platform Administrator, Project Administrator |
| **Pre-Conditions** | User đã đăng nhập; có quyền export; list đã load; thanh chọn đang hiện (≥1 dòng tick) |
| **Trigger** | Bấm "Xuất tất cả {M} mục khớp lọc" trên thanh chọn (`{M}` = `pagination.total`) |
| **Post-Conditions** | File tải về máy user; tên `qc-review-export-YYYY-MM-DD.xlsx` hoặc `.csv` |
| **Business Rules** | Không hard cap số dòng; >10.000 dòng → warning `"Việc này có thể mất một lúc"` trước Tiếp tục; Project Administrator chỉ nhận item trong project được phép; export chạy nền nên user phải chờ trong dialog (timeout poll 10 phút); cột gồm: QC Item ID, Upload ID, Filename, Project, Duration, Status, Reject reason, Priority, Assignee, Created at, Project ID, Batch ID, Reject comment, Last reviewed at, Last reviewed by, QC type, Tags |

**UI/UX**

> [[docs/review/qc-review-export-list/ascii-screen/qc-review-list-export-default.md|qc-review-list-export-default]]
> [[docs/review/qc-review-export-list/ascii-screen/qc-review-export-dialog-confirm.md|qc-review-export-dialog-confirm]]

#### 3.2.2 US-002 Export các dòng đã chọn

**Story**

**As a** `QC Lead` **I want** `tick các dòng cần báo cáo rồi export một lần` **So that** `tôi gom đúng tập item cần báo cáo mà không phải export cả danh sách`

**Acceptance Criteria**

- **AC 1 (Happy path — selected export):**
    - **Given** tôi đã tick ≥1 dòng trên trang hiện tại, thanh chọn hiện `"Đã chọn {N} mục"`,
    - **When** tôi bấm **"Xuất theo lựa chọn"** trên thanh chọn và bấm **Tiếp tục** trong dialog,
    - **Then** file tải về chỉ chứa **đúng N dòng đã chọn** (theo ID), dialog hiện `"Xuất {N} mục đã chọn. Tiếp tục?"`, và phạm vi export **không** phụ thuộc filter hiện tại trên màn hình.
- **AC 2 (Edge — hủy chọn):**
    - **Given** thanh chọn đang hiện `"Đã chọn 5 mục"`,
    - **When** tôi bấm **Hủy** trên thanh chọn,
    - **Then** toàn bộ checkbox bỏ chọn, thanh chọn ẩn, và lần export tiếp theo (nếu có) phải tick lại từ đầu.
- **AC 3 (Edge — đổi filter/trang khi đang chọn):**
    - **Given** tôi đã tick 5 dòng,
    - **When** tôi đổi bất kỳ filter nào hoặc sang trang khác,
    - **Then** selection **bị xóa** (thanh chọn ẩn) vì tập chọn không còn trỏ tới dòng đang hiển thị; muốn export cả tập khớp lọc thì dùng "Xuất tất cả" (US-001).

**Business Requirement Table**

|  |  |
| --- | --- |
| **User Story** | US-002 Export các dòng đã chọn |
| **Description**  | Export theo tập ID đã tick trên trang hiện tại |
| **Actor**  | QC Lead, Platform Administrator, Project Administrator |
| **Pre-Conditions** | ≥1 dòng được tick; user có quyền đọc từng item selected |
| **Trigger** | Bấm "Xuất theo lựa chọn" trên thanh chọn khi `selected count ≥ 1` |
| **Post-Conditions** | File chứa đúng các dòng selected; sau khi tải xong hệ thống xóa selection |
| **Business Rules** | Khi có selection → selection **thắng** filter (export selected only); selection **bị xóa khi đổi filter/trang** (chỉ giữ trong lúc đứng nguyên trang); item selected mà user mất quyền → server loại bỏ, nếu 0 còn lại → `"No items to export"` |

**UI/UX**

> [[docs/review/qc-review-export-list/ascii-screen/qc-review-list-export-selection.md|qc-review-list-export-selection]]
> [[docs/review/qc-review-export-list/ascii-screen/qc-review-export-dialog-confirm.md|qc-review-export-dialog-confirm]]

#### 3.2.3 US-003 Phân quyền export theo role

**Story**

**As a** `Platform Administrator` **I want** `chỉ user đủ quyền mới thấy và dùng được Export` **So that** `dữ liệu QC không bị tải ra ngoài bởi reviewer thường hoặc admin project ngoài phạm vi`

**Acceptance Criteria**

- **AC 1 (Happy path — authorized roles):**
    - **Given** tôi đăng nhập với role QC Lead, Platform Administrator, hoặc Project Administrator,
    - **When** tôi mở QC Review Listing và tick ≥1 dòng,
    - **Then** tôi thấy 2 nút **"Xuất theo lựa chọn"** / **"Xuất tất cả … mục khớp lọc"** trên thanh chọn.
- **AC 2 (Negative — QC Reviewer):**
    - **Given** tôi đăng nhập với role QC Reviewer (không phải lead/admin),
    - **When** tôi mở QC Review Listing và tick ≥1 dòng,
    - **Then** 2 nút **Export** **không hiển thị** (ẩn hoàn toàn, không disabled) — tôi chỉ thấy nút Phân công nếu có `qc:assign`.

**Business Requirement Table**

|  |  |
| --- | --- |
| **User Story** | US-003 Phân quyền export theo role |
| **Description**  | Kiểm soát ai được export và phạm vi project |
| **Actor**  | Hệ thống (enforce); QC Lead, Platform Administrator, Project Administrator, QC Reviewer |
| **Pre-Conditions** | User đã đăng nhập |
| **Trigger** | Mở QC Review list; thực hiện export |
| **Post-Conditions** | Chỉ authorized user export được; file không chứa item ngoài phạm vi |
| **Business Rules** | QC Lead + Platform Administrator → mọi project; Project Administrator → chỉ project được phép (server enforce, không tin client); QC Reviewer → không có quyền export |

**UI/UX**

> [[docs/review/qc-review-export-list/ascii-screen/qc-review-list-export-default.md|qc-review-list-export-default]] (authorized)
> QC Reviewer: cùng màn list nhưng **không có** nút Export — không cần wireframe riêng.

#### 3.2.4 US-004 Dialog xác nhận và xử lý lỗi

**Story**

**As a** `Project Administrator` **I want** `xác nhận số dòng và định dạng file trước khi tải, và nhận thông báo rõ khi lỗi` **So that** `tôi không export nhầm tập dữ liệu hoặc không biết vì sao export thất bại`

**Acceptance Criteria**

- **AC 1 (Happy path — dialog confirm):**
    - **Given** tôi bấm "Xuất theo lựa chọn" / "Xuất tất cả … mục khớp lọc" với N dòng hợp lệ,
    - **When** dialog mở,
    - **Then** tôi thấy chọn format (Excel (.xlsx) mặc định / CSV), câu confirm đúng ngữ cảnh (selected vs filtered), nút **Tiếp tục** và **Hủy**; sau Tiếp tục nút đổi thành `"Đang chuẩn bị xuất…"` (Hủy bị disable) cho đến khi file tải xong.
- **AC 2 (Edge — export fail / large batch):**
    - **Given** N >10.000 dòng HOẶC server không build được file,
    - **When** tôi bấm Tiếp tục (hoặc hệ thống lỗi giữa chừng),
    - **Then** với N >10.000: dialog hiện thêm warning `"Việc này có thể mất một lúc"` nhưng vẫn cho Tiếp tục; với lỗi server/mạng: hiện `"Xuất thất bại. Vui lòng thử lại hoặc thu hẹp bộ lọc."` và không có file tải về.
- **AC 3 (Edge — job nền quá lâu):**
    - **Given** tôi chọn "Xuất tất cả" cho một hàng đợi rất lớn,
    - **When** job nền chạy quá 10 phút,
    - **Then** hệ thống báo lỗi timeout thay vì treo dialog vô hạn; tôi thu hẹp bộ lọc rồi thử lại.

**Business Requirement Table**

|  |  |
| --- | --- |
| **User Story** | US-004 Dialog xác nhận và xử lý lỗi |
| **Description**  | Dialog format + confirm + loading + error wording |
| **Actor**  | QC Lead, Platform Administrator, Project Administrator |
| **Pre-Conditions** | Có ≥1 dòng để export (selected hoặc filtered) |
| **Trigger** | Bấm một trong hai nút Export trên thanh chọn |
| **Post-Conditions** | User confirm hoặc hủy; thành công → download + xóa selection; thất bại → error message |
| **Business Rules** | Excel (.xlsx) là default; CSV = UTF-8 with BOM; đóng tab khi đang export = hủy, không resume; không toast success — chỉ browser download; "Xuất tất cả" có thể lâu hơn vì chạy nền |

**UI/UX**

> [[docs/review/qc-review-export-list/ascii-screen/qc-review-export-dialog-confirm.md|qc-review-export-dialog-confirm]]
> [[docs/review/qc-review-export-list/ascii-screen/qc-review-export-dialog-large-warning.md|qc-review-export-dialog-large-warning]]
