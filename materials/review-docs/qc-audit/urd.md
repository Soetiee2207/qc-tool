<!-- doc-meta: type=urd | feature=docs/review/qc-audit | status=draft | updated=2026-09-25 -->
# **User Requirement** Documentation

Audit — vòng QC thứ 2 (module Review)

Version 1.2  |  2026-09-25

| **Version** | **Date** | **Author** | **Changes** |
| --- | --- | --- | --- |
| 1.2 | 2026-09-25 | @kimi-code | Đối chiếu code: mã lý do OTS chọn nhiều, kho thật thay mock |
| 1.0 | 2026-09-08 | @binhhm | Initial draft từ brainstorm audit-second-round-qc |
| 1.1 | 2026-09-11 | @binhhm | Đối chiếu code đã triển khai: sửa wording thực tế, cột hàng đợi, hộp thoại reject dùng nút vô hiệu hoá, ghi rõ US-005 chưa triển khai |

## 1. INTRODUCTION

**1.1. Purpose**

Tài liệu này ghi lại yêu cầu nghiệp vụ cho sub-module **Audit** — vòng kiểm tra chất lượng thứ hai nằm trong module Review.

- **Viết cho:** PO/PM (duyệt phạm vi và độ ưu tiên) và đội phát triển (hiểu nghiệp vụ trước khi đọc đặc tả kỹ thuật).
- **Mục tiêu:** làm baseline yêu cầu cho phase đầu tiên của Audit, làm nguồn đầu vào cho tài liệu đặc tả kỹ thuật (`srs.md`).
- **Phạm vi hợp lệ:** phase 1 của sub-module Audit. Các hạng mục đã chốt hoãn (lấy mẫu theo lô, màn thống kê chất lượng reviewer) không thuộc phạm vi tài liệu này.

**1.2. Scope**

**IN SCOPE**

- Hàng đợi Audit dạng danh sách, đặt ở mục menu "Audit QC" riêng trong nhóm "Đánh giá" của module Review.
- Tiếp nhận 100% item đã có quyết định ở QC Review vòng 1 — cả nhánh Passed lẫn nhánh Rejected.
- Màn chấm Audit: hiển thị đầy đủ kết quả vòng 1 (quyết định, mã lý do, ghi chú, người review, thời điểm) ở chế độ chỉ đọc.
- Chấm Pass hoặc Reject theo bộ tiêu chí dùng chung với QC Review; quyết định Audit ghi đè quyết định vòng 1 và là quyết định cuối cùng.
- Nhánh Pass: dữ liệu chuyển sang Warehousing (sub-module thuộc module Delivery).
- Nhánh Reject: bắt buộc chọn mã lý do, item chạy lại toàn bộ các bước xử lý dữ liệu rồi quay về hàng đợi QC Review vòng 1.
- Nhóm quyền riêng cho auditor, tách khỏi quyền QC Review vòng 1.
- Luật tách vai: chặn cứng auditor chấm chính item mình đã review ở vòng 1.
- Lưu lịch sử Audit để reviewer vòng 1 và QC Lead xem lại được — hiện mới có dữ liệu và API lịch sử riêng cho auditor (xem OUT OF SCOPE và US-005).

**OUT OF SCOPE**

- **Cơ chế lấy mẫu theo lô** — audit một phần dữ liệu và lấy kết quả đại diện cho cả lô. Đã chốt hoãn sang phase sau; phase này chạy 1:1 theo từng item.
- **Màn thống kê / báo cáo chất lượng reviewer** — tỉ lệ lật quyết định, độ chính xác từng reviewer, nhóm lỗi hay gặp. Phase này chỉ tích lũy dữ liệu, chưa dựng màn báo cáo.
- **Auditor chỉnh sửa dữ liệu** — không sửa vùng làm mờ, không sửa metadata. Vòng 2 thuần là kiểm tra.
- **Thông báo tự động** — không gửi thông báo cho reviewer vòng 1 hay QC Lead khi Audit lật quyết định; chỉ lưu lịch sử.
- **Giới hạn số vòng lặp reject** — item có thể quay vòng Audit → xử lý lại → QC Review nhiều lần không giới hạn. Điểm dừng để phase sau.
- **Khóa item khi đang chấm** — không khóa; hai auditor cùng mở được, người gửi trước được tính.
- **Phân công item cho auditor** — không có giao việc thủ công hay tự động; auditor tự lấy item từ hàng đợi.
- **Hồi tố** — item đã bàn giao trước khi có Audit không bị kéo ngược vào hàng đợi.
- **Nghiệp vụ bên trong Warehousing** — Audit chỉ bàn giao sang đó, không đặc tả phần tiếp theo.
- **Tra cứu kết quả Audit trên màn lịch sử của reviewer vòng 1 / QC Lead** — code mới chỉ có API lịch sử Audit riêng, bọc quyền auditor, và chưa màn nào gọi tới; xem ghi chú ở US-005.

**Integration boundary**

| Hệ thống / module | Mục đích tương tác |
| --- | --- |
| QC Review (vòng 1) | Nguồn cấp item cho hàng đợi Audit; cũng là nơi item quay về sau khi bị Audit reject |
| Các bước xử lý dữ liệu | Chạy lại toàn bộ khi item bị Audit reject, trước khi item quay về QC Review. Hiện mới phát yêu cầu (outbox + Kafka), chưa có bước nhận kết quả để item tự quay về |
| Warehousing (module Delivery) | Điểm ra của nhánh Audit Pass — dữ liệu được bàn giao vào kho thật (bảng `portal_warehouse_items`, màn `/warehousing` đọc `GET /api/v1/warehousing/items`); `GET /api/v1/delivery/warehousing/mock-items` cũ chỉ còn phục vụ bộ chọn item của đơn giao hàng |
| QC Checklists | Cung cấp bộ tiêu chí chấm; Audit dùng chung, không có danh mục riêng. Màn chấm Audit hiện chưa render checklist |
| Hệ thống định danh dùng chung (SSO) | Cung cấp nhóm quyền auditor |

**1.3. Definitions and Acronyms**

| **Term / Acronym** | **Definition** |
| --- | --- |
| **URD** | User Requirement Documentation |
| **Audit** | Vòng kiểm tra chất lượng thứ hai, chạy sau QC Review. Trong tài liệu này luôn hiểu theo nghĩa này |
| **QC Review vòng 1** | Vòng kiểm tra chất lượng đầu tiên, đã có sẵn trong module Review |
| **Auditor** | Người thực hiện vòng Audit; thuộc nhóm quyền riêng, tách khỏi reviewer vòng 1 |
| **Warehousing** | Sub-module thuộc module Delivery, tiếp nhận dữ liệu sau khi Audit chấm đạt |
| **Mã lý do** | Giá trị phân loại lỗi chọn ở hộp thoại reject; bắt buộc khi reject. Project dùng template `ots-gopro-v1` có 6 mã riêng và cho chọn nhiều mã (gửi lên dạng `ots:<code>,<code>`); item còn lại chọn một mã trong danh mục dùng chung |
| **Lô** | Tập item được gom lại để lấy mẫu audit. Khái niệm dành cho phase sau, chưa định nghĩa ở tài liệu này |

## 2. System Overview

### 2.1 High-Level User Flow

1. Dữ liệu đi qua các bước xử lý, vào hàng đợi QC Review vòng 1.
2. Reviewer vòng 1 mở item và chấm Pass hoặc Reject.
3. Hệ thống chuyển item sang hàng đợi Audit — cả hai nhánh đều vào, không nhánh nào được bỏ qua.
4. Auditor mở menu "Audit QC", tự lấy item từ hàng đợi. Item do chính người đó chấm ở vòng 1 không xuất hiện trong danh sách.
5. Auditor xem đầy đủ kết quả vòng 1, chấm theo bộ tiêu chí dùng chung, ở chế độ chỉ xem.
6. Auditor chấm Pass hoặc Reject. Đây là quyết định cuối cùng, ghi đè quyết định vòng 1.
7. Nhánh Pass: dữ liệu chuyển sang Warehousing, kết thúc luồng.
8. Nhánh Reject: auditor chọn mã lý do bắt buộc, item chạy lại toàn bộ các bước xử lý dữ liệu rồi quay về bước 1.

Xem lưu đồ nghiệp vụ: [[docs/review/qc-audit/srs/qc-audit-flows.md|Audit — Activity flow]]

**Điểm mấu chốt:** kết quả cuối chỉ phụ thuộc quyết định Audit, không phụ thuộc quyết định vòng 1. Vòng 1 Rejected nhưng Audit Pass thì dữ liệu vẫn đi Warehousing — đây là cách một luồng duy nhất vừa chặn được hàng lỗi lọt ra, vừa cứu được dữ liệu bị loại oan.

### 2.2 System User Profile

| **User Role** | **Description** | **Permission Level** | **Key Actions** |
| --- | --- | --- | --- |
| Auditor | Người thực hiện vòng kiểm tra thứ hai; thuộc nhóm quyền riêng, tách khỏi reviewer vòng 1 | Truy cập hàng đợi Audit + chấm Audit; chỉ đọc với dữ liệu nội dung | Xem hàng đợi Audit, xem kết quả vòng 1, chấm Pass, chấm Reject kèm mã lý do |
| QC Reviewer (vòng 1) | Người chấm ở QC Review vòng 1 | Không có quyền chấm Audit; **chưa có đường xem kết quả Audit** của item mình đã chấm (US-005 chưa triển khai) | — |
| QC Lead | Cấp quản lý đội QC | Các quyền QC vòng 1 (`qc:queue:view`, `qc:review:perform`); **không có** `qc:audit:perform` nên chưa xem được kết quả Audit | Theo dõi chất lượng đội qua dashboard QC sẵn có |
| System | Tác nhân tự động của hệ thống | — | Chuyển item sang hàng đợi Audit sau vòng 1, ẩn item vi phạm luật tách vai, bàn giao sang Warehousing khi Audit Pass, đẩy item chạy lại xử lý dữ liệu khi Audit Reject |

## 3. User Stories

### 3.1 User Story List

| **US Code** | **US Name** | **US Description** |
| --- | --- | --- |
| US-001 | Xem hàng đợi Audit | Auditor mở menu "Audit QC", xem danh sách item đã có quyết định vòng 1 đang chờ audit |
| US-002 | Xem kết quả QC Review vòng 1 | Auditor mở một item, xem quyết định + lý do + người review vòng 1, ở chế độ chỉ đọc |
| US-003 | Chấm Audit đạt | Auditor chấm Pass, dữ liệu chuyển sang Warehousing |
| US-004 | Chấm Audit không đạt | Auditor chấm Reject kèm mã lý do bắt buộc, item chạy lại xử lý dữ liệu rồi quay về QC Review |
| US-005 | Reviewer xem lại kết quả Audit | Reviewer vòng 1 mở lịch sử item mình đã chấm, xem Audit kết luận gì |

### 3.2 User Story Detail

#### 3.2.1 US-001 Xem hàng đợi Audit

**Story**

**As a** `Auditor` **I want** `xem danh sách item đã qua QC Review vòng 1 đang chờ audit` **So that** `tôi biết còn bao nhiêu việc và tự lấy item để chấm`

**Acceptance Criteria**

- **AC 1 (Hàng đợi có item):**
    - **Given** tôi thuộc nhóm quyền auditor và hàng đợi đang có item,
    - **When** tôi mở menu "Audit QC" trong module Review,
    - **Then** tôi thấy danh sách item dạng bảng, mỗi dòng gồm: ảnh đại diện, tên file, project, thời lượng, kết quả vòng 1 (Pass/Reject), người review vòng 1, thời điểm vào audit và nút Audit.
- **AC 2 (Luật tách vai):**
    - **Given** tôi là người đã chấm item X ở QC Review vòng 1,
    - **When** tôi mở hàng đợi Audit,
    - **Then** item X không xuất hiện trong danh sách của tôi, kể cả khi tôi là QC Lead hay Admin.
- **AC 3 (Hàng đợi rỗng):**
    - **Given** không có item nào đang chờ audit,
    - **When** tôi mở menu "Audit QC",
    - **Then** hệ thống hiển thị khối rỗng "Không có item chờ audit" kèm dòng mô tả "Sau khi reviewer submit QC vòng 1, item sẽ xuất hiện ở đây.", và vẫn giữ thanh tìm kiếm cùng bộ lọc để tôi tự kiểm tra bộ lọc.
- **AC 4 (Không có quyền):**
    - **Given** tôi không thuộc nhóm quyền auditor,
    - **When** tôi truy cập đường dẫn hàng đợi Audit,
    - **Then** hệ thống chặn truy cập và hiển thị "Bạn không có quyền truy cập Audit.", hoặc ẩn hẳn mục menu "Audit QC".

**Business Requirement Table**

| | |
| --- | --- |
| **User Story** | US-001 Xem hàng đợi Audit |
| **Description** | Auditor xem danh sách item đã có quyết định QC Review vòng 1, đang chờ vòng kiểm tra thứ hai |
| **Actor** | Auditor |
| **Pre-Conditions** | Người dùng đã đăng nhập và thuộc nhóm quyền auditor. Có ít nhất một item đã được chấm ở vòng 1 (nếu không, áp dụng AC 3) |
| **Trigger** | Người dùng mở mục menu "Audit QC" trong module Review |
| **Post-Conditions** | Danh sách item chờ audit được hiển thị. Trạng thái item không đổi — chỉ xem, chưa chấm |
| **Business Rules** | 100% item có quyết định vòng 1 đều vào hàng đợi này, cả Passed lẫn Rejected, không lấy mẫu. Item do chính người đang đăng nhập chấm ở vòng 1 bị ẩn khỏi hàng đợi của họ, chặn cứng không có ngoại lệ. Hệ thống không khóa item — nhiều auditor cùng thấy và cùng mở được một item. Không có cơ chế giao việc; auditor tự lấy item |

**UI/UX**

Wireframe: [[docs/review/qc-audit/ascii-screen/audit-queue.md|US-001 Hàng đợi Audit]] · [[docs/review/qc-audit/ascii-screen/audit-queue-empty.md|US-001 Hàng đợi rỗng]]

#### 3.2.2 US-002 Xem kết quả QC Review vòng 1

**Story**

**As a** `Auditor` **I want** `xem đầy đủ kết quả chấm của QC Review vòng 1 khi mở một item` **So that** `tôi biết vòng trước kết luận gì và tập trung soát vào điểm nghi ngờ`

**Acceptance Criteria**

- **AC 1 (Hiển thị đầy đủ):**
    - **Given** tôi bấm nút Audit trên một dòng trong hàng đợi,
    - **When** màn chấm mở ra,
    - **Then** tôi thấy khối "QC vòng 1" nằm trên cùng sidebar trái, gồm quyết định (Pass/Reject), mã lý do, tên người review, thời điểm chấm và ghi chú; trường nào rỗng thì ẩn hẳn dòng đó thay vì để trống.
- **AC 2 (Chế độ chỉ xem):**
    - **Given** tôi đang ở màn chấm Audit,
    - **When** tôi tìm cách chỉnh sửa nội dung (vùng làm mờ, metadata),
    - **Then** không có thao tác chỉnh sửa nào khả dụng, và màn hiển thị chú thích "Màn audit chỉ đọc" trên thanh công cụ.
- **AC 3 (Vòng 1 Passed không có lý do):**
    - **Given** item được vòng 1 chấm Pass và không có mã lý do,
    - **When** tôi xem khối "QC vòng 1",
    - **Then** dòng "Lý do" không được render, tránh gây hiểu nhầm là dữ liệu thiếu.

**Business Requirement Table**

| | |
| --- | --- |
| **User Story** | US-002 Xem kết quả QC Review vòng 1 |
| **Description** | Auditor xem lại toàn bộ kết luận của vòng 1 trước khi tự đưa ra quyết định vòng 2 |
| **Actor** | Auditor |
| **Pre-Conditions** | Item đang ở trạng thái chờ audit và không vi phạm luật tách vai với người đang đăng nhập |
| **Trigger** | Người dùng bấm nút Audit trên một dòng hàng đợi |
| **Post-Conditions** | Màn chấm hiển thị video bên phải, sidebar trái gồm khối kết quả vòng 1 và hai tab "Audit bàn giao" (metadata chỉ đọc) + "Lịch sử review". Trạng thái item vẫn là chờ audit |
| **Business Rules** | Auditor được phép biết trước kết quả vòng 1 — đây là quyết định nghiệp vụ đã chốt, không phải chấm mù. Rủi ro đi kèm: auditor dễ chấm theo quán tính vòng 1, cần theo dõi tỉ lệ lật quyết định. Auditor chỉ đọc, không sửa được dữ liệu nội dung. Bộ tiêu chí chấm dùng chung với QC Review, không có danh mục riêng cho Audit; màn Audit hiện **chưa render checklist tiêu chí** — API chi tiết vẫn trả `criteria` nằm trong khối review vòng 1 |

**UI/UX**

Wireframe: [[docs/review/qc-audit/ascii-screen/audit-review-detail.md|US-002 Màn chấm Audit]]

#### 3.2.3 US-003 Chấm Audit đạt

**Story**

**As a** `Auditor` **I want** `chấm một item là đạt ở vòng 2` **So that** `dữ liệu được bàn giao sang Warehousing`

**Acceptance Criteria**

- **AC 1 (Chấm đạt thành công):**
    - **Given** tôi đang ở màn chấm của một item chờ audit,
    - **When** tôi bấm nút Pass rồi xác nhận trong hộp thoại "Xác nhận duyệt",
    - **Then** hệ thống ghi nhận kết quả đạt, hiển thị toast "Đã ghi nhận audit pass.", chuẩn bị bàn giao sang Warehousing và đưa tôi về hàng đợi Audit.
- **AC 2 (Lật quyết định vòng 1 — cứu dữ liệu bị loại oan):**
    - **Given** item được vòng 1 chấm Reject,
    - **When** tôi chấm Audit là Pass,
    - **Then** dữ liệu vẫn được chuyển sang Warehousing, vì quyết định Audit ghi đè quyết định vòng 1.
- **AC 3 (Item vừa bị người khác chấm):**
    - **Given** một auditor khác vừa chấm xong chính item này trước tôi,
    - **When** tôi bấm Pass,
    - **Then** hệ thống không ghi nhận quyết định của tôi, đưa tôi về hàng đợi đã cập nhật, kèm thông báo "Item vừa được người khác chấm. Đang làm mới danh sách."
    - *Ghi chú triển khai (2026-09-11):* backend hiện trả 404 trong ca này (không phải thông báo tranh chấp) vì bước tra item đã lọc `status='pending_audit'`; frontend chỉ hiện thông báo trên khi nhận 409. Cần chốt lại mã lỗi — xem OQ-07 trong [[docs/cross-module/qc-audit-to-warehousing.md|XM-01]].

**Business Requirement Table**

| | |
| --- | --- |
| **User Story** | US-003 Chấm Audit đạt |
| **Description** | Auditor kết luận item đạt chất lượng ở vòng kiểm tra thứ hai |
| **Actor** | Auditor; System (thực hiện bàn giao sang Warehousing) |
| **Pre-Conditions** | Item đang ở trạng thái chờ audit và chưa được auditor nào chấm xong |
| **Trigger** | Người dùng bấm nút Pass ở góc phải thanh công cụ màn chấm Audit, rồi xác nhận trong hộp thoại |
| **Post-Conditions** | Item chuyển sang trạng thái `audit_passed`. Bundle bàn giao được chuẩn bị (delivery_overrides). Lịch sử Audit được lưu gồm người chấm, quyết định, vòng audit và thời điểm |
| **Business Rules** | Quyết định Audit là quyết định cuối cùng, ghi đè quyết định vòng 1 bất kể vòng 1 là Pass hay Reject. Chấm Pass không yêu cầu nhập thêm thông tin gì, chỉ xác nhận qua hộp thoại. Chỉ khi Audit Pass thì dữ liệu mới được bàn giao — vòng 1 Pass không còn tự bàn giao như trước khi có Audit. Hệ thống không gửi thông báo cho bất kỳ ai. Hệ thống không khóa item nên phải xử lý được trường hợp hai auditor cùng chấm: người gửi trước được tính |

**UI/UX**

Wireframe: [[docs/review/qc-audit/ascii-screen/audit-review-detail.md|US-003 Màn chấm Audit]] · [[docs/review/qc-audit/ascii-screen/audit-pass-dialog.md|US-003 Hộp thoại xác nhận duyệt]]

#### 3.2.4 US-004 Chấm Audit không đạt

**Story**

**As a** `Auditor` **I want** `chấm một item là không đạt kèm lý do cụ thể` **So that** `dữ liệu được xử lý lại và quay về QC Review thay vì bị bàn giao sai`

**Acceptance Criteria**

- **AC 1 (Chấm không đạt thành công):**
    - **Given** tôi bấm nút Reject và hộp thoại chọn lý do mở ra,
    - **When** tôi chọn một mã lý do và bấm "Xác nhận từ chối",
    - **Then** hệ thống ghi nhận kết quả không đạt kèm mã lý do và ghi chú, hiển thị "Đã ghi nhận audit reject — đã yêu cầu reprocess.", phát yêu cầu chạy lại toàn bộ các bước xử lý dữ liệu để item quay về hàng đợi QC Review vòng 1.
- **AC 2 (Thiếu mã lý do):**
    - **Given** hộp thoại đang mở và tôi chưa chọn mã lý do,
    - **When** tôi nhìn nút xác nhận,
    - **Then** nút "Xác nhận từ chối" ở trạng thái vô hiệu hoá, hệ thống không gửi gì; hộp thoại và nội dung ghi chú tôi đã gõ được giữ nguyên.
- **AC 3 (Lật quyết định vòng 1 — chặn hàng lỗi lọt ra):**
    - **Given** item được vòng 1 chấm Pass,
    - **When** tôi chấm Audit là Reject,
    - **Then** dữ liệu không được chuyển sang Warehousing mà quay lại vòng xử lý và QC Review.
- **AC 4 (Item bị reject nhiều lần):**
    - **Given** item này đã từng bị Audit reject ở vòng trước và vừa quay lại sau khi xử lý lại,
    - **When** tôi chấm Reject lần nữa,
    - **Then** hệ thống vẫn ghi nhận bình thường và item tiếp tục quay vòng — phase này không giới hạn số vòng lặp.
- **AC 5 (Hủy hộp thoại):**
    - **Given** hộp thoại xác nhận đang mở,
    - **When** tôi bấm Hủy,
    - **Then** hộp thoại đóng, không ghi nhận gì, item vẫn ở trạng thái chờ audit.

**Business Requirement Table**

| | |
| --- | --- |
| **User Story** | US-004 Chấm Audit không đạt |
| **Description** | Auditor kết luận item không đạt ở vòng hai, kèm mã lý do bắt buộc để khâu xử lý lại biết cần sửa gì |
| **Actor** | Auditor; System (đẩy item chạy lại xử lý dữ liệu) |
| **Pre-Conditions** | Item đang ở trạng thái chờ audit và chưa được auditor nào chấm xong |
| **Trigger** | Người dùng bấm nút Reject ở góc phải thanh công cụ màn chấm Audit, rồi xác nhận trong hộp thoại |
| **Post-Conditions** | Item chuyển sang trạng thái `audit_rejected`, `reprocess_status='requested'`, yêu cầu chạy lại toàn bộ các bước xử lý dữ liệu được phát đi; xử lý lại xong item quay về hàng đợi QC Review vòng 1. Lịch sử Audit được lưu gồm người chấm, vòng audit, mã lý do, ghi chú và thời điểm |
| **Business Rules** | Mã lý do bắt buộc ở giao diện (nút xác nhận chỉ bật khi đã chọn); item thuộc template `ots-gopro-v1` chọn nhiều mã trong 6 mã riêng của template, item còn lại chọn một mã trong danh mục dùng chung với QC Review; backend chấp nhận reject khi có mã lý do **hoặc** ghi chú. Ghi chú tùy chọn. Không giới hạn số vòng lặp reject ở phase này — đây là quyết định có ý thức, rủi ro item quay vòng nhiều lần đã được chấp nhận. Quyết định Audit ghi đè quyết định vòng 1. Hệ thống không gửi thông báo cho reviewer vòng 1 hay QC Lead |

**UI/UX**

Wireframe: [[docs/review/qc-audit/ascii-screen/audit-reject-dialog.md|US-004 Hộp thoại xác nhận không đạt]] · [[docs/review/qc-audit/ascii-screen/audit-reject-dialog-error.md|US-004 Trạng thái thiếu mã lý do]]

#### 3.2.5 US-005 Reviewer xem lại kết quả Audit

> **Trạng thái triển khai (2026-09-11):** chưa có trong code ở dạng mô tả dưới đây. Backend mới có endpoint lịch sử Audit riêng `GET /api/v1/qc/audit/queue/{item_id}/history` và endpoint này bọc quyền `qc:audit:perform` — reviewer vòng 1 (`vd-qc-reviewers`) và QC Lead (`vd-qc-leads`) không có quyền này, nên không truy cập được. Endpoint lịch sử cũ `/qc/queue/{item_id}/review-sessions` vẫn chỉ trả phiên vòng 1, không kèm kết quả Audit; không màn frontend nào hiển thị kết quả Audit cho reviewer. Các AC dưới đây giữ nguyên làm yêu cầu, chưa phải hành vi hiện có.

**Story**

**As a** `QC Reviewer (vòng 1)` **I want** `xem kết quả Audit của item mình đã chấm` **So that** `tôi biết mình chấm đúng hay sai và rút kinh nghiệm cho lần sau`

**Acceptance Criteria**

- **AC 1 (Xem được kết quả):**
    - **Given** tôi đã chấm item X ở vòng 1 và item đó đã được audit,
    - **When** tôi mở lịch sử của item X,
    - **Then** tôi thấy quyết định Audit, mã lý do, ghi chú và thời điểm chấm.
- **AC 2 (Không có thông báo chủ động):**
    - **Given** item tôi chấm Pass ở vòng 1 vừa bị Audit lật thành Reject,
    - **When** auditor hoàn tất việc chấm,
    - **Then** hệ thống không gửi cho tôi bất kỳ thông báo nào — tôi chỉ biết khi tự mở lịch sử item.
- **AC 3 (Item chưa được audit):**
    - **Given** item tôi chấm vẫn đang chờ audit,
    - **When** tôi mở lịch sử item đó,
    - **Then** phần kết quả Audit hiển thị trạng thái chờ, không hiển thị quyết định rỗng gây hiểu nhầm là đã audit xong.

**Business Requirement Table**

| | |
| --- | --- |
| **User Story** | US-005 Reviewer xem lại kết quả Audit |
| **Description** | Reviewer vòng 1 tự tra cứu kết luận của vòng 2 cho item mình đã chấm |
| **Actor** | QC Reviewer (vòng 1); QC Lead cũng xem được với mọi item |
| **Pre-Conditions** | Người dùng đã đăng nhập và là người đã chấm item đó ở vòng 1 (hoặc là QC Lead) |
| **Trigger** | Người dùng mở lịch sử của một item |
| **Post-Conditions** | Kết quả Audit được hiển thị. Không có thay đổi trạng thái nào |
| **Business Rules** | Reviewer vòng 1 xem được đầy đủ kết quả Audit item mình đã chấm, gồm cả tên auditor. Hệ thống không gửi thông báo chủ động khi Audit lật quyết định — chỉ lưu lịch sử. Reviewer không có quyền chấm Audit và không phản hồi lại được quyết định Audit trong phạm vi phase này |

**UI/UX**

> *Leave it empty*
