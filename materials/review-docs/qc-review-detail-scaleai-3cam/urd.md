<!-- doc-meta: type=urd | feature=review/qc-review-detail-scaleai-3cam | status=draft | updated=2026-09-25 -->
# **User Requirement** Documentation

Bố cục lại màn QC Review detail cho preview 3-video (ScaleAI multicam)

Version 1.3  |  2026-09-25

|  |  |  |  |
| --- | --- | --- | --- |
| **Version**  | **Date**  | **Author**  | **Changes**  |
| 1.3  | 2026-09-25  | @kimi-code  | Sidebar 2 tab cho mọi item review; US-003 hết đúng phần sidebar |
| 1.2  | 2026-09-11  | @binhhm  | Đối chiếu code: bổ sung mô tả toolbar thật (Back/Pass/Reject + toggle sidebar/dark/help), header panel Delivery Audit (đếm trường thiếu), preview dùng 1 master timeline chung + tuỳ chọn "Xoay 2 cam cổ tay 180°"; làm rõ `activity_tags` không tính vào mẫu số required |
| 1.1  | 2026-08-26  | @binhhm  | US-001: thêm Delivery Audit Field Schema chi tiết (partner_name/collector_id/schema_version/activity_tags) |
| 1.0  | 2026-08-26  | @binhhm  | Initial draft từ brainstorm review-detail-3cam-layout  |

**Table of Contents**

1. **INTRODUCTION**

**1.1. Purpose**

- Tài liệu này viết cho PO, dev frontend, QA.
- Phục vụ mục tiêu: làm baseline nghiệp vụ để code trực tiếp việc redesign layout, và làm nguồn đầu vào cho `/srs` và wireframe chi tiết.
- Phạm vi: áp dụng cho màn QC Review detail hiện có (không phải feature mới hoàn toàn) — chỉ phần bố cục lại khi review có item loại ScaleAI multicam (3 video).

**1.2. Scope**

- **IN SCOPE:**
  - Bố cục lại 3 khối chính của màn QC Review detail (Delivery Audit / Preview / Review History) cho item review có 3 video (ScaleAI multicam: Head + camera cổ tay trái + cổ tay phải).
  - Gộp Delivery Audit và Review History thành 2 tab trong sidebar bên trái (thay cho Delivery Audit cố định + Review History nằm dưới Preview).
  - Preview mở rộng chiếm không gian được giải phóng, giữ bố cục tam giác (1 trên — Head, 2 dưới — camera cổ tay).
  - Toolbar màn detail (giữ nguyên vị trí, mô tả để đối chiếu QA): Back, tên file, project, chip trạng thái, `+N trong hàng đợi`, toggle ẩn/hiện sidebar, toggle dark mode, nút help shortcut, nút Pass/Reject.
  - Tuỳ chọn hiển thị **"Xoay 2 cam cổ tay 180°"** (mặc định bật) trong vùng Preview multicam — chỉ đổi hướng hiển thị, không đổi dữ liệu video.
- **OUT OF SCOPE:**
  - Vùng Preview của item review có 1-2 video (stereo/single) — giữ nguyên; sidebar dùng chung 2 tab với mọi item (từ 2026-09-23).
  - Logic nghiệp vụ Pass/Reject, luồng chấm QC, hoặc nội dung dữ liệu của Delivery Audit/Review History — tài liệu này chỉ đổi CÁCH SẮP XẾP hiển thị, không đổi luồng hay dữ liệu.
  - Responsive cho màn hình dưới 1024px.
  - Cách đồng bộ/hiển thị nội bộ của khung video 3-camera — giữ nguyên component đang có, chỉ đổi khung bố cục bên ngoài.
- **Integration boundary:** Không có — hoàn toàn nội bộ frontend, không gọi dịch vụ bên ngoài nào.

**1.3. Definitions and Acronyms**

|  |  |
| --- | --- |
| **Term / Acronym**  | **Definition**  |
| **URD** | User Requirement Documentation |
| **Delivery Audit** | Panel hiển thị các trường metadata bàn giao bắt buộc của bản ghi (`partner_name`, `collector_id`, `metadata.schema_version`, `activity_tags` gồm `task`/`environment`/`scene`) kèm đếm số trường thiếu |
| **Review History** | Danh sách các lần review trước đây của cùng 1 item (ai review, khi nào, kết quả) |
| **ScaleAI Multicam** | Loại project dùng 3 camera cố định (Head, cổ tay trái, cổ tay phải) quay đồng thời 1 tác vụ — kế thừa định nghĩa từ feature `scaleai-multicam-qr-sync` |

## 2. System Overview

### 2.1 High-Level User Flow

1. QC Reviewer vào màn QC Review Queue, chọn 1 item để xem chi tiết.
2. Hệ thống mở màn detail: sidebar trái **luôn** hiện 2 tab (Delivery Audit mở mặc định + Review History) cho mọi item; vùng Preview mới rẽ nhánh theo loại item — ScaleAI multicam (3 video) → 3 video bố cục tam giác; stereo/single (1-2 video) → 1-2 video.
3. Reviewer xem Preview, đối chiếu Delivery Audit hoặc Review History khi cần (bấm tab nếu là item 3-video).
4. Reviewer bấm Pass hoặc Reject.
5. Hệ thống ghi nhận quyết định, chuyển sang item tiếp theo (nếu có hàng đợi) hoặc quay về QC Review Queue.

### 2.2 System User Profile

|  |  |  |  |
| --- | --- | --- | --- |
| **User Role**  | **Description**  | **Permission Level**  | **Key Actions**  |
| QC Reviewer  | Nhân viên nội bộ thực hiện kiểm tra chất lượng bản ghi trước khi duyệt  | Quyền truy cập QC Review Queue và các item được giao — không có phân quyền riêng cho tính năng bố cục lại này  | Xem Delivery Audit, xem Preview video, xem Review History, bấm Pass/Reject  |

## 3. User Stories

### 3.1 User Story List

| **US Code** | **US Name** | **US Description** |
| --- | --- | --- |
| US-001 | Xem preview 3-video bố cục tam giác kèm sidebar tab | Mở 1 item ScaleAI multicam → sidebar trái hiện tab Delivery Audit/Review History, Preview hiện 3 video theo bố cục tam giác |
| US-002 | Chuyển đổi tab Delivery Audit ↔ Review History | Khi đang xem item 3-video, bấm chuyển tab để đối chiếu Delivery Audit hoặc Review History mà không ảnh hưởng Preview |
| US-003 | Giữ nguyên layout hiện tại cho item 1-2 video | **Không còn đúng ở phần sidebar (2026-09-25):** sidebar 2 tab đã áp dụng cho mọi item review; item stereo/single chỉ khác vùng Preview (1-2 video, không tam giác 3 cam) |

### 3.2 User Story Detail

#### 3.2.1 US-001 Xem preview 3-video bố cục tam giác kèm sidebar tab

**Story**

**As a** `QC Reviewer` **I want** `xem đủ 3 video (Head, cổ tay trái, cổ tay phải) trong 1 khung Preview đủ lớn, cùng lúc vẫn truy cập được Delivery Audit` **So that** `tôi đánh giá chất lượng bản ghi 3 camera chính xác hơn mà không bị các panel khác chiếm chỗ`

**Acceptance Criteria**

- **AC 1 (Happy path):**
    - **Given** QC Reviewer mở 1 item thuộc loại ScaleAI multicam từ QC Review Queue,
    - **When** màn detail được tải xong,
    - **Then** sidebar trái hiện 2 tab (Delivery Audit, Review History) với tab Delivery Audit đang mở mặc định, và khung Preview hiện đủ 3 video theo bố cục tam giác (Head lớn ở trên, camera cổ tay trái/phải nhỏ hơn ở dưới), không còn panel Review History nằm dưới Preview.
- **AC 2 (Edge — thiếu trường bắt buộc vẫn phải nhận biết được dù đang ở tab khác):**
    - **Given** item đang xem thiếu ít nhất 1 trường Delivery Audit bắt buộc, và Reviewer đang ở tab Review History,
    - **When** Reviewer chưa chuyển lại tab Delivery Audit,
    - **Then** hệ thống KHÔNG hiện badge số trường thiếu trên nhãn tab (theo quyết định giữ đơn giản) — số trường thiếu chỉ hiện khi Reviewer mở tab Delivery Audit; đây là hành vi CHỦ Ý, không phải lỗi.

**Business Requirement Table**

|  |  |
| --- | --- |
| **User Story** | US-001 Xem preview 3-video bố cục tam giác kèm sidebar tab |
| **Description**  | Redesign khung tổng thể màn QC Review detail cho item ScaleAI multicam: sidebar trái gộp 2 tab, Preview mở rộng giữ bố cục tam giác 3 video |
| **Actor**  | QC Reviewer |
| **Pre-Conditions** | Item đang mở thuộc loại ScaleAI multicam (có đủ 3 video: Head, cổ tay trái, cổ tay phải) |
| **Trigger** | Reviewer bấm vào 1 item ScaleAI multicam từ QC Review Queue |
| **Post-Conditions** | Màn detail hiển thị đúng layout mới: sidebar 2 tab (Delivery Audit mở mặc định) + Preview tam giác 3 video, không hiện panel Review History dưới Preview |
| **Business Rules** | Chỉ áp dụng cho item có đủ 3 video (ScaleAI multicam); tab Delivery Audit luôn mở mặc định khi vào màn; badge số trường thiếu chỉ hiện trong **header panel** Delivery Audit (dòng "Thiếu {missing}/{total} trường bắt buộc"), không gắn lên nhãn tab; bố cục tam giác tái dùng đúng component video-grid hiện có; 3 camera phát **đồng bộ** qua 1 thanh timeline/controls chung gắn head camera (2 pane cổ tay không có toolbar riêng); có checkbox "Xoay 2 cam cổ tay 180°" mặc định bật trong vùng Preview; Delivery Audit gồm 4 nhóm trường schema cố định (xem bảng Field Schema ngay dưới) |

**Delivery Audit — Field Schema chi tiết**

| Field | Type | Required | Default / Ví dụ | Ý nghĩa nghiệp vụ | Khi thiếu giá trị |
| --- | --- | --- | --- | --- | --- |
| `partner_name` | string | Yes | Mặc định `"VinDynamics"` | Tên đối tác/tổ chức thu thập dữ liệu — phân loại nguồn dữ liệu khi audit, đặc biệt khi 1 dự án có nhiều đối tác cùng thu thập | Tính vào số trường thiếu bắt buộc, hiện "! Thiếu — cần audit" |
| `collector_id` | string | Yes | Alphanumeric duy nhất, vd `op-8432562934` | Định danh người/thiết bị thực hiện thu thập — phục vụ truy vết (audit trail) khi cần xác minh nguồn gốc bản ghi | Tính vào số trường thiếu bắt buộc |
| `metadata.schema_version` | string | No | Mặc định `v1.0` | Phiên bản schema của khối metadata đi kèm — giúp phân biệt cấu trúc dữ liệu tương ứng, tránh đọc sai field khi schema đổi version về sau | KHÔNG tính vào số trường thiếu (optional) |
| `activity_tags` | object | Yes | Gồm 3 trường con: `task`, `environment`, `scene` | Nhóm thông tin mô tả chính xác hoạt động được quay — nền tảng để phân loại/tra cứu dữ liệu theo loại tác vụ sau này | Thiếu BẤT KỲ trường con nào → cả `activity_tags` tính là thiếu (xem 3 dòng dưới) |
| `↳ activity_tags.task` | string | Yes | Định dạng: ≥2 động từ + ≥1 vật thể + ≥1 dụng cụ/thành phần. Vd: "Disassemble, clean, and reassemble a fan using a screwdriver and cloth." | Mô tả định danh activity của collector — gắn nhãn tác vụ nhất quán giữa các bản ghi, phục vụ phân loại/tra cứu theo loại việc | Tính vào số trường thiếu bắt buộc |
| `↳ activity_tags.environment` | string (enum) | Yes | Chỉ 1 trong 6 giá trị: `Industrial Workspace`, `Logistics Floor`, `Workshop & Field Service`, `Commercial Kitchen`, `Retail & Merchandising Floor`, `Service & Care Environment` | Phân loại môi trường quay ở cấp cao — dùng để lọc/gộp dữ liệu theo loại bối cảnh khi phân tích | Tính vào số trường thiếu bắt buộc; giá trị ngoài 6 enum trên coi như invalid, không phải "thiếu" |
| `↳ activity_tags.scene` | string | Yes | Vd: `assembly line`, `kitchen prep counter`, `grocery store aisle`, `workshop bench`, `stockroom` | Vị trí/trạm làm việc cụ thể TRONG `environment` đã chọn — chi tiết hoá bối cảnh quay hơn `environment`, hữu ích khi cần phân biệt nhiều scene trong cùng 1 environment | Tính vào số trường thiếu bắt buộc |

*Bảng này là nguồn schema chính thức cho panel Delivery Audit — wireframe `docs/review/qc-review-detail-scaleai-3cam/ascii-screen/qc-review-detail-3cam-audit.md` trích dẫn lại đúng field/rule ở đây, không định nghĩa riêng.*

**UI/UX**

- Wireframe: [[docs/review/qc-review-detail-scaleai-3cam/ascii-screen/qc-review-detail-3cam-audit.md|US-001 QC Review detail 3-cam (tab Delivery Audit mở) — wireframe]]

#### 3.2.2 US-002 Chuyển đổi tab Delivery Audit ↔ Review History

**Story**

**As a** `QC Reviewer` **I want** `chuyển qua lại giữa tab Delivery Audit và Review History khi đang xem 1 item 3-video` **So that** `tôi đối chiếu đúng thông tin cần (audit hoặc lịch sử review) mà không mất tập trung khỏi Preview đang xem`

**Acceptance Criteria**

- **AC 1 (Happy path):**
    - **Given** Reviewer đang xem item 3-video ở tab Delivery Audit (mặc định),
    - **When** Reviewer bấm tab Review History,
    - **Then** nội dung sidebar đổi sang danh sách lịch sử review, khung Preview và trạng thái phát video (play/pause, vị trí) giữ nguyên không bị gián đoạn.
- **AC 2 (Edge — bấm lại tab đang active):**
    - **Given** Reviewer đang ở tab Review History,
    - **When** Reviewer bấm lại đúng tab Review History (tab đang active),
    - **Then** hệ thống không có hiệu ứng hay reload nội dung thừa — giữ nguyên trạng thái hiện tại.

**Business Requirement Table**

|  |  |
| --- | --- |
| **User Story** | US-002 Chuyển đổi tab Delivery Audit ↔ Review History |
| **Description**  | Cho phép Reviewer chuyển đổi nội dung sidebar giữa 2 tab mà không ảnh hưởng khung Preview đang phát |
| **Actor**  | QC Reviewer |
| **Pre-Conditions** | Đang ở màn detail của item 3-video (đã áp dụng US-001) |
| **Trigger** | Reviewer bấm vào tab Delivery Audit hoặc Review History trong sidebar |
| **Post-Conditions** | Nội dung sidebar hiển thị đúng tab được chọn; Preview không bị reload/gián đoạn khi đổi tab |
| **Business Rules** | Chuyển tab chỉ đổi nội dung sidebar, không ảnh hưởng trạng thái phát video hoặc dữ liệu Delivery Audit/Review History; bấm tab đang active không có tác dụng phụ |

**UI/UX**

- Wireframe: [[docs/review/qc-review-detail-scaleai-3cam/ascii-screen/qc-review-detail-3cam-history.md|US-002 QC Review detail 3-cam (tab Review History mở) — wireframe]]

#### 3.2.3 US-003 Giữ nguyên layout hiện tại cho item 1-2 video

**Story**

**As a** `QC Reviewer` **I want** `layout màn detail giữ đúng như hiện tại khi tôi xem item stereo hoặc single-video` **So that** `tôi không bị xáo trộn thói quen làm việc với các item không thuộc ScaleAI multicam`

**Acceptance Criteria**

- **AC 1 (Happy path):**
    - **Given** Reviewer mở 1 item thuộc loại stereo hoặc single-video (không phải ScaleAI multicam),
    - **When** màn detail được tải xong,
    - **Then** vùng Preview hiện 1-2 video như trước, nhưng sidebar **đã đổi từ 2026-09-23**: dùng chung 2 tab (Delivery Audit + Review History) cho mọi item — không còn Delivery Audit cố định hay Review History dưới Preview.
- **AC 2 (Edge — item không đủ dữ liệu để xác định loại video):**
    - **Given** item đang mở thiếu dữ liệu để xác định là 1/2/3 video,
    - **When** hệ thống không xác định được là ScaleAI multicam,
    - **Then** sidebar vẫn dùng 2 tab như mọi item (không phụ thuộc nhận diện 3 video); chỉ vùng Preview mặc định về player 1-2 video.

**Business Requirement Table**

|  |  |
| --- | --- |
| **User Story** | US-003 Giữ nguyên layout hiện tại cho item 1-2 video |
| **Description**  | Đảm bảo redesign layout của US-001/US-002 không ảnh hưởng tới trải nghiệm xem item stereo/single-video |
| **Actor**  | QC Reviewer |
| **Pre-Conditions** | Item đang mở KHÔNG thuộc loại ScaleAI multicam (1 hoặc 2 video) |
| **Trigger** | Reviewer bấm vào 1 item stereo/single từ QC Review Queue |
| **Post-Conditions** | Layout hiển thị giống hoàn toàn hành vi hiện tại trước redesign |
| **Business Rules** | Sidebar 2 tab áp dụng cho **mọi** item review, không phụ thuộc loại video; việc xác định loại video chỉ còn quyết định vùng Preview (1-2 video hay tam giác 3 cam), không phải lựa chọn thủ công của Reviewer |

**UI/UX**

> *Leave it empty*

