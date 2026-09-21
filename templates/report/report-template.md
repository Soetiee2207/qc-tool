# Báo cáo kiểm thử — {TÊN_TÍNH_NĂNG}

**Môi trường:** {DEV/STAGING/PROD} · **Ngày chạy:** {YYYY-MM-DD HH:mm} · **Người chạy:** {TÊN}

---

## 1. Tóm tắt

> **{KẾT_LUẬN_MỘT_CÂU}**
> Ví dụ: "Chức năng đăng nhập SSO chạy đúng. Có 4 lỗi, trong đó 1 lỗi nặng cần sửa trước khi lên production."

| | Số lượng |
|---|---|
| Tổng số test | {N} |
| Đạt | {N} |
| **Lỗi** | **{N}** |
| Bị chặn | {N} |
| Chưa chạy | {N} |

**Tỉ lệ đạt:** {N}% ({đạt}/{tổng})

---

## 2. Chi tiết theo module

| Module | Tổng | Đạt | Lỗi | Bị chặn | Chưa chạy |
|---|---|---|---|---|---|
| {Tên module} | {N} | {N} | {N} | {N} | {N} |
| **Tổng** | **{N}** | **{N}** | **{N}** | **{N}** | **{N}** |

---

## 3. Danh sách lỗi

> Sắp xếp theo mức độ: Cao → Trung bình → Thấp.

### Lỗi 1 — {TIÊU_ĐỀ_NGẮN_GỌN}

| | |
|---|---|
| Mã test | {TC_...} |
| Mức độ | {Cao / Trung bình / Thấp} |
| Module | {Tên module} |
| Yêu cầu liên quan | {ID requirement} |

**Làm gì để tái hiện:**
1. {Bước 1}
2. {Bước 2}

**Mong đợi:** {Hệ thống phải làm gì}

**Thực tế:** {Hệ thống đã làm gì}

**Bằng chứng:** {đường dẫn ảnh chụp / response body}

---

### Lỗi 2 — {TIÊU_ĐỀ}

*(lặp lại cấu trúc trên)*

---

## 4. Chưa chạy được

| Mã test | Lý do | Cần gì để chạy được | Ai xử lý |
|---|---|---|---|
| {TC_...} | {Ví dụ: môi trường dev sập lúc 14:30} | {Khởi động lại API} | {@ai} |

---

## 5. Test chập chờn

> Test lần đầu không đạt, chạy lại mới đạt. **Không tính là đạt** — một test lúc
> được lúc không là vấn đề cần tìm nguyên nhân (race condition của sản phẩm, hoặc
> test chờ chưa đúng chỗ). Bỏ mục này nếu không có test nào chập chờn.

| Mã test | Tên | Lần chạy | Lý do lần đầu | Nghi ngờ |
|---|---|---|---|---|
| {TC_...} | {Tên} | {2} | {Lý do} | {Sản phẩm / Test / Chưa rõ} |

---

## 6. Độ phủ yêu cầu

| | |
|---|---|
| Yêu cầu có test | {N} / {Tổng N} ({N}%) |
| Yêu cầu **chưa có test nào** | {N} |
| Test **không gắn với yêu cầu nào** | {N} |

**Yêu cầu chưa được test:**

| ID | Tên yêu cầu | Vì sao chưa test |
|---|---|---|
| {ID} | {Tên} | {Không kiểm chứng được / Ngoài phạm vi / Chưa làm} |

---

## 7. Ghi chú

{Các điểm cần lưu ý: môi trường có vấn đề gì, thay đổi so với lần chạy trước.}

---

*Nguồn số liệu: `results.csv` · `junit.xml` · bằng chứng: `evidence/`*
