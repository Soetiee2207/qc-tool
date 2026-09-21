---
type: tracking-readme
status: living
created: 2026-09-18
updated: 2026-09-18
lang: vi
owner: "@binhhm"
changelog:
  - 2026-09-18 | manual | khởi tạo — quy ước tracking cho repo qc-tool
---

# Tracking — quy ước

> Đây là **hợp đồng** của bộ tracking. Đọc trước khi ghi bất cứ thứ gì vào thư mục này.
> Mô phỏng theo bộ tracking của repo `vd-data-platform-portal` (`docs/reports/`) nhưng rút gọn
> cho một repo tool.

## Thư mục có gì

| File | Là gì | Tính chất |
|---|---|---|
| `milestones.md` | Registry M01..Mn — **xương sống** | Sửa ít, sửa là ghi changelog |
| `todo.md` | Danh sách việc cuốn chiếu | Sửa thường xuyên |
| `INDEX.md` | Điểm vào: tiến độ + danh mục | Sinh lại từ 2 file trên |
| `weekly/<YYYY-Www>.md` | Báo cáo tuần | **Đóng băng** sau khi công bố |

Thư mục ngoài:

| Thư mục | Là gì |
|---|---|
| `docs/brainstorms/` | Bối cảnh, quyết định thiết kế |
| `docs/findings/` | Phát hiện về hệ thống được test |

## Trục 1 — Thời gian

Tuần ISO, thứ 2 → chủ nhật. Báo cáo tuần đặt tên `<YYYY-Www>.md`.

Nếu một kỳ chưa đủ dữ liệu, hoặc cần báo cáo gộp để báo cáo cấp trên: giữ tên file theo kỳ **mới nhất**,
điền `merged_weeks:` trong frontmatter, mở rộng `from`/`to`, thêm cột **Kỳ**. Báo cáo cũ **không xoá**.

## Trục 2 — Milestone

`milestones.md` là một registry duy nhất, `M01`…`Mn`. Mỗi báo cáo tuần là một ảnh chụp của nó.

**Đánh số:** milestone mới → thêm dòng, `M<n>` tăng dần, **không đánh số lại** milestone cũ
(báo cáo cũ trỏ vào ID).

**Status enum** — chỉ dùng đúng các giá trị này:

| Status | Nghĩa |
|---|---|
| `Planned` | Đã thống nhất, chưa bắt đầu |
| `In progress` | Đã bắt đầu, chưa verify |
| `At risk` | Sẽ trễ mốc, hoặc đang phụ thuộc quyết định chưa có |
| `Blocked` | Không tiến được nếu không có hành động/quyết định từ bên ngoài (**ghi rõ ai**) |
| `Done` | Đã làm và **đã verify** trên môi trường đã thoả thuận |
| `Signed-off` | `Done`, **và** đã demo + được stakeholder có tên nghiệm thu |

**Definition of milestone-complete** — chỉ đủ khi **cả 4** điều kiện đúng:

1. Chạy được trên môi trường đã thoả thuận.
2. Đã demo, hoặc đã được người **khác tác giả** chạy end-to-end.
3. Được stakeholder có tên trong cột nghiệm thu chấp nhận.
4. Tài liệu liên quan đã đồng bộ.

> Commit đã merge **không phải** là hoàn thành.

## Trục 3 — Việc

`todo.md` chia mục:

| Mục | Nội dung | Cột |
|---|---|---|
| 1 | **Chờ người khác quyết định** | `# \| Việc \| Ai quyết \| Thuộc \| Nguồn \| Từ ngày` |
| 2 | Kỳ này | `# \| Việc \| Thuộc \| Nguồn` |
| 3 | Chưa xếp lịch | `# \| Việc \| Thuộc \| Nguồn` |
| 4 | Đã xong (giữ 1 kỳ rồi xoá) | `# \| Việc \| Xong ngày \| Vào báo cáo` |

Ô đánh dấu: `[ ]` chưa xong · `[x]` đã xong · `[~]` đang làm · `[!]` đang chặn.

Cột **Nguồn** ghi việc này từ đâu ra, để sau còn truy được.
Cột **Ai quyết** ở Mục 1 là bắt buộc — không có người quyết thì không phải vướng mắc.

## Báo cáo tuần chứa gì

Báo cáo tuần trả lời **"kỳ này làm ra được gì"**. Không phải work log, không phải commit dump.

**Được ghi:** tính năng mới · thay đổi hành vi · lỗi đã sửa thành gì · quyết định đã chốt (kèm ai chốt) ·
việc còn dở / kế tiếp / đang chờ ai quyết.

**Không ghi:** đồng bộ nhánh / merge / conflict · cập nhật chính bộ tracking này · chỉnh script, dọn dẹp,
dựng môi trường.

**Không dán vào báo cáo:** danh sách commit, sha từng việc, số file / số dòng code.

**Cách viết một dòng:** theo góc người dùng thấy, không theo góc code.

## Quy tắc bất di bất dịch

1. **Read-only trừ khi được yêu cầu sửa.** Câu hỏi nhận câu trả lời, không nhận edit.
2. **Không suy diễn.** Thiếu owner/acceptance → `TBC`. Chưa verify được → hỏi, **không** tick.
   Thêm một việc vào to-do là phán đoán của agent, không cần bằng chứng;
   đánh dấu *done* thì **luôn** cần bằng chứng.
3. **Thêm milestone thì được, nhưng phải tăng số, không đánh số lại.**
4. **`weekly/` là bản ghi đóng băng.** Muốn sửa phải nói rõ, và phải ghi lý do vào `changelog:` của file đó.
5. **Body tiếng Việt, frontmatter key tiếng Anh.** Timestamp GMT+7.

## Cách sinh lại một báo cáo

1. Xác định kỳ ISO và nói rõ ra ("kỳ này" = `2026-W38`).
2. Đọc `todo.md` §2 để lấy việc còn lại.
3. **Không tự bịa.** Ô nào chưa chắc → `TBC`.
4. Cập nhật `milestones.md` (status + `updated`) và `INDEX.md`.
5. Chuyển việc đã xong trong `todo.md` sang §4.

## Phrasebook — câu nói thường ngày → việc phải làm

| User nói | Nghĩa là | Đụng vào |
|---|---|---|
| "tuần này làm gì rồi?" | Đọc báo cáo tuần hiện tại | `weekly/<kỳ>.md` |
| "còn gì chưa xong?" | Đọc §2 + §1 của todo | `todo.md` |
| "thêm việc X vào to-do" | Append vào `todo.md` §2 hoặc §3 | `todo.md` |
| "thêm milestone X" | Append dòng vào registry, số kế tiếp | `milestones.md` |
| "dự án đang ở đâu?" | Đọc INDEX + registry | `INDEX.md`, `milestones.md` |
| "đánh dấu X xong" | **Verify bằng chứng trước**, rồi mới chuyển | `todo.md`, `milestones.md` |
| "bắt đầu báo cáo tuần" | Viết `weekly/<kỳ>.md` | `weekly/`, `INDEX.md`, `milestones.md` |
