#!/usr/bin/env bash
#
# qc-tool — chạy QC một lượt.
#
#   ./qc.sh --docs <thư-mục> --oas <file> --link <url> --acc <email> [mật-khẩu]
#
# Bốn đầu vào:
#   --docs   thư mục tài liệu (urd.md, srs.md)
#   --oas    file OpenAPI spec
#   --link   link webapp cần test
#   --acc    tài khoản đăng nhập
#
# Ví dụ:
#   ./qc.sh --docs ./docs/login-sso --oas ./openapi.json \
#           --link https://dev-qc-portal.datafactory.fit \
#           --acc v.binhhm1@vindynamics.net Abcd1234@
#
# Đưa được flag nào hay flag đó — thiếu thì tool chạy với phần còn lại.

set -euo pipefail

cd "$(dirname "$0")"

# ── Mặc định ────────────────────────────────────────────────────────────────
DOCS=""; OAS=""; LINK=""; API=""; FEATURE=""
ACC_USER=""; ACC_PASS=""; PASS_FROM_ENV=0
CONFIG=""; EXTRA=()

usage() {
  cat <<'EOF'

  qc-tool — tự động hoá QC: tài liệu + OAS + link web → testcase → chạy → báo cáo

  CÁCH DÙNG
    ./qc.sh [flags]

  BỐN ĐẦU VÀO
    --docs <thư-mục>        Thư mục tài liệu (chứa urd.md, srs.md)
    --oas  <file>           File OpenAPI spec (.yaml/.json)
    --link <url>            Link webapp cần test
    --acc  <email> [mật-khẩu]
                            Tài khoản đăng nhập.
                            Bỏ mật khẩu  → lấy từ .env
                            Ghi dấu `-`  → hỏi mật khẩu (không lưu vết)

  TUỲ CHỌN
    --api <url>             Địa chỉ API (mặc định lấy theo --link)
    --feature <tên>         Tên feature (mặc định: suy từ --docs, hoặc 'qc')
    --module <tên>          Module cho case sinh từ tài liệu
    --show-browser          Hiện cửa sổ Chrome thay vì chạy ẩn
    --skip-run              Chỉ sinh testcase, không chạy
    --config <file>         Dùng file cấu hình YAML thay cho các flag trên
    -h, --help              Hướng dẫn này

  VÍ DỤ
    # Đầy đủ bốn đầu vào
    ./qc.sh --docs ./docs/login-sso --oas ./openapi.json \
            --link https://dev-qc-portal.datafactory.fit \
            --acc user@company.com 'mật-khẩu'

    # Chưa có OAS — vẫn chạy được, chỉ ít case hơn
    ./qc.sh --docs ./docs/login-sso --link https://dev-qc-portal.datafactory.fit

    # Hỏi mật khẩu, không lưu vào lịch sử shell
    ./qc.sh --docs ./docs/login-sso --link https://portal.test --acc user@company.com -

    # Thử trên API giả, không cần hệ thống thật
    ./qc.sh --config qc_config/qc-demo.yaml

EOF
}

# ── Đọc tham số ─────────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
    --docs)    DOCS="$2"; shift 2 ;;
    --oas)     OAS="$2"; shift 2 ;;
    --link)    LINK="$2"; shift 2 ;;
    --api)     API="$2"; shift 2 ;;
    --feature) FEATURE="$2"; shift 2 ;;
    --config)  CONFIG="$2"; shift 2 ;;
    --module)  EXTRA+=(--module "$2"); shift 2 ;;
    --show-browser) EXTRA+=(--show-browser); shift ;;
    --skip-run)     EXTRA+=(--skip-run); shift ;;

    --acc)
      ACC_USER="${2:-}"
      # Mật khẩu là tham số TUỲ CHỌN: chỉ nhận nếu không phải flag kế tiếp
      if [[ -n "${3:-}" && "${3:0:2}" != "--" ]]; then
        ACC_PASS="$3"; shift 3
      else
        PASS_FROM_ENV=1; shift 2
      fi
      ;;

    -h|--help) usage; exit 0 ;;
    *) printf '\n  ✗ Flag không nhận ra: %s\n' "$1" >&2; usage >&2; exit 2 ;;
  esac
done

die() { printf '\n  ✗ %s\n\n' "$1" >&2; exit 1; }
warn() { printf '  ! %s\n' "$1"; }

# Đọc một khoá trong file cấu hình YAML (hỗ trợ khoá lồng nhau: "run.base_url")
read_cfg() {
  python3 - "$CONFIG" "$1" <<'PY' 2>/dev/null || true
import sys
try:
    import yaml
except ImportError:
    print(""); raise SystemExit
try:
    data = yaml.safe_load(open(sys.argv[1], encoding="utf-8")) or {}
    for key in sys.argv[2].split("."):
        data = (data or {}).get(key) if isinstance(data, dict) else None
    print(data if data not in (None, "") else "")
except Exception:
    print("")
PY
}

command -v uv >/dev/null 2>&1 || die "Chưa có 'uv'. Cài: curl -LsSf https://astral.sh/uv/install.sh | sh"

# ── Hỏi mật khẩu nếu người dùng ghi `-` ─────────────────────────────────────
if [[ "$ACC_PASS" == "-" ]]; then
  [[ -n "$ACC_USER" ]] || die "Ghi `--acc <email> -` thì cần email."
  printf '  Mật khẩu cho %s: ' "$ACC_USER"
  read -rs ACC_PASS
  printf '\n'
  [[ -n "$ACC_PASS" ]] || die "Chưa nhập mật khẩu."
fi

# ── Suy tên feature nếu không đưa ───────────────────────────────────────────
if [[ -z "$FEATURE" && -z "$CONFIG" ]]; then
  if [[ -n "$DOCS" ]]; then
    FEATURE="$(basename "${DOCS%/}")"
  elif [[ -n "$OAS" ]]; then
    FEATURE="$(basename "${OAS%.*}")"
  else
    FEATURE="qc"
  fi
fi

# ── Kiểm tra đầu vào ────────────────────────────────────────────────────────
if [[ -z "$CONFIG" ]]; then
  [[ -n "$DOCS" || -n "$OAS" ]] || die "Cần ít nhất --docs hoặc --oas. Chạy ./qc.sh -h để xem hướng dẫn."

  [[ -z "$DOCS" || -d "$DOCS" ]] || die "Không thấy thư mục tài liệu: $DOCS"
  [[ -z "$OAS"  || -f "$OAS"  ]] || die "Không thấy file OpenAPI: $OAS"
  [[ -z "$LINK" || "$LINK" =~ ^https?:// ]] || die "--link phải bắt đầu bằng http:// hoặc https:// (đang là: $LINK)"

  [[ -n "$DOCS" ]] || warn "Chưa có --docs — sẽ sinh ít testcase hơn"
  [[ -n "$OAS"  ]] || warn "Chưa có --oas — phần lớn case sẽ ở trạng thái 'bị chặn'"
  [[ -n "$LINK" ]] || warn "Chưa có --link — không test được giao diện"
fi

[[ -f .env ]] || [[ -n "$ACC_USER" ]] || warn "Chưa có .env và chưa có --acc — sẽ chạy không đăng nhập"

# ── Chạy ────────────────────────────────────────────────────────────────────
if [[ -n "$CONFIG" ]]; then
  ARGS=(--config "$CONFIG")
  LABEL="config: $CONFIG"
  # Tên feature nằm trong file cấu hình — đọc ra để biết tìm kết quả ở đâu
  [[ -n "$FEATURE" ]] || FEATURE="$(read_cfg feature)"
else
  ARGS=(--feature "$FEATURE")
  [[ -n "$DOCS" ]] && ARGS+=(--docs-dir "$DOCS")
  [[ -n "$OAS"  ]] && ARGS+=(--openapi  "$OAS")
  [[ -n "$LINK" ]] && ARGS+=(--web-url  "$LINK")
  [[ -n "$API"  ]] && ARGS+=(--base-url "$API")
  LABEL="$FEATURE"
fi
ARGS+=(${EXTRA[@]+"${EXTRA[@]}"})
FEATURE="${FEATURE:-qc}"

echo
echo "  ══════════════════════════════════════════════════════"
echo "   qc-tool · $LABEL"
[[ -n "$CONFIG" ]] || {
  printf '   tài liệu : %s\n' "${DOCS:-—}"
  printf '   OpenAPI  : %s\n' "${OAS:-—}"
  printf '   web      : %s\n' "${LINK:-—}"
  printf '   tài khoản: %s\n' "${ACC_USER:-—}"
}
echo "  ══════════════════════════════════════════════════════"
echo

# Mật khẩu đi qua BIẾN MÔI TRƯỜNG, không qua tham số dòng lệnh.
# Tham số dòng lệnh hiện trong `ps` cho mọi user trên máy đọc được.
RUN_ENV=()
[[ -n "$ACC_USER" ]] && RUN_ENV+=("QCTOOL_USERNAME=$ACC_USER")
[[ -n "$ACC_PASS" ]] && RUN_ENV+=("QCTOOL_PASSWORD=$ACC_PASS")

STARTED_AT=$(date +%s)

set +e
env "${RUN_ENV[@]+"${RUN_ENV[@]}"}" uv run qctool all "${ARGS[@]}"
STATUS=$?
set -e

# ── Kết quả ─────────────────────────────────────────────────────────────────
if [[ "$STATUS" -le 1 ]]; then
  # Chỉ báo cáo do CHÍNH lượt chạy này sinh ra. Nếu tool dừng vì lỗi, hoặc chỉ
  # sinh testcase mà không chạy, thì không được chỉ vào báo cáo cũ — người dùng
  # sẽ đọc kết quả của lần trước và tưởng là mới.
  REPORT=""
  if [[ -d "artifacts/$FEATURE/runs" ]]; then
    REPORT="$(find "artifacts/$FEATURE/runs" -name report.md -newermt "@$STARTED_AT" 2>/dev/null | head -1 || true)"
  fi

  if [[ -n "$REPORT" ]]; then
    echo
    echo "  ──────────────────────────────────────────────────────"
    echo "   Báo cáo : $REPORT"
    echo "   Testcase: artifacts/$FEATURE/testcases.xlsx"
    echo "  ──────────────────────────────────────────────────────"
    if [[ -n "${QCTOOL_OPEN_REPORT:-}" ]] && command -v xdg-open >/dev/null; then
      xdg-open "$REPORT" 2>/dev/null || true
    fi
  elif [[ "$STATUS" -eq 0 ]]; then
    echo
    echo "  Testcase: artifacts/$FEATURE/testcases.xlsx"
  fi
fi

echo
case "$STATUS" in
  0) echo "  ✓ Xong — không có test nào lỗi. Đọc Mục 4 trong báo cáo để biết phần chưa chạy được." ;;
  1) echo "  ✗ Có test LỖI. Mở báo cáo ở Mục 3." ;;
  *) echo "  ✗ Tool dừng vì lỗi. Đọc thông báo phía trên." ;;
esac
echo

exit "$STATUS"
