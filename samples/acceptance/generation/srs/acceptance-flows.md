# Luồng hư cấu — acceptance generation

## 5. Core Flows

### 5.1 Duyệt dự án trước khi chuẩn bị tài khoản

1. Open /ui/du-an → URL /ui/du-an
2. Provision account → Account provisioned

Kỳ vọng của bước 1 là một nghĩa vụ riêng. Case legacy của cả luồng chỉ assert
kỳ vọng cuối; coverage generation phải bổ sung case route, không giả vờ đã cấp
tài khoản để biến cả luồng thành tự động.
