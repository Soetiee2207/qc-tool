"""CLI của qc-tool.

    qctool init <tên>              # tạo projects/<tên>/qctool.yaml
    qctool check <tên>             # kiểm tra cấu hình/tài liệu, không gọi model/browser/API
    qctool run <tên>               # tài liệu → testcase → chạy → báo cáo
    qctool trace <tên> <MÃ_TEST>   # xem lại từng bước của một case
    qctool ui                      # giao diện web
    qctool demo                    # chạy thử trên API giả, không cần hệ thống thật
    qctool step ingest|generate|exec|crawl …   # từng chặng, khi cần kiểm soát chi tiết

<tên> là tên thư mục trong projects/, một thư mục chứa qctool.yaml, hoặc đường dẫn file YAML.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

from qctool import __version__, config, execute, generate, ingest, render, report
from qctool import pipeline as _pipeline
from qctool.pipeline import PipelineConfig, run_pipeline
from qctool.core.testcase import Step, StepKind, TestCase


def cmd_ingest(args: argparse.Namespace) -> int:
    feature_dir = Path(args.feature_dir).expanduser().resolve()
    if not feature_dir.is_dir():
        print(f"LỖI  Không phải thư mục: {feature_dir}", file=sys.stderr)
        return 2

    feature = args.feature or feature_dir.name
    data = ingest.ingest_feature(feature_dir, feature)

    out = Path(args.out) if args.out else _pipeline.ARTIFACTS_ROOT / feature / "requirements.yaml"
    ingest.write_yaml(data, out)

    print(ingest.summary(data))
    print()
    print(f"→ {out}")
    return 1 if data["warnings"] and args.strict else 0


def cmd_generate(args: argparse.Namespace) -> int:
    req_path = Path(args.requirements) if args.requirements else None
    api_path = Path(args.openapi) if args.openapi else None

    if not req_path and not api_path:
        print("LỖI  Cần ít nhất một nguồn: --requirements hoặc --openapi", file=sys.stderr)
        return 2
    for label, path in (("--requirements", req_path), ("--openapi", api_path)):
        if path and not path.is_file():
            print(f"LỖI  {label}: không tìm thấy file {path}", file=sys.stderr)
            return 2

    cases, report, meta = generate.generate_all(req_path, api_path, args.module)

    if args.out:
        out = Path(args.out)
    else:
        # `requirements.yaml` → lấy tên thư mục cha (`login-sso`) chứ không lấy
        # stem (`requirements`) — nếu không mọi feature đều ghi vào một chỗ.
        source = req_path or api_path
        stem = source.parent.name if source.stem in {"requirements", "openapi"} else source.stem
        out = _pipeline.ARTIFACTS_ROOT / stem / "testcases.yaml"
    generate.write_cases(cases, out, meta)

    print(report.text())
    print()
    print(f"→ {out}")

    if args.xlsx:
        xlsx_path = Path(args.xlsx)
        render.render(cases, xlsx_path, created_by=args.created_by or "qc-tool")
        print(f"→ {xlsx_path}   ({len(cases)} dòng, 14 cột)")

    if not report.ok:
        return 1
    return 1 if (report.warnings or report.gaps) and args.strict else 0


def cmd_run_testcases(args: argparse.Namespace) -> int:
    cases_path = Path(args.testcases)
    if not cases_path.is_file():
        print(f"LỖI  Không tìm thấy file testcase: {cases_path}", file=sys.stderr)
        return 2

    cfg = config.load_config()
    web_url = (args.web_url or "").rstrip("/")
    # Mặc định API lấy theo `--base-url`; nếu người dùng chỉ đưa `--web-url` thì
    # dùng chính địa chỉ web đó làm gốc (SPA và API thường cùng tên miền), chứ
    # KHÔNG lấy `QCTOOL_BASE_URL` trong `.env` — bài học từ lượt chạy thật: báo
    # cáo ghi môi trường là portal thật trong khi test đang trỏ vào mock.
    base_url = (args.base_url or web_url or cfg.base_url or "").rstrip("/")
    if not base_url and not web_url:
        print("LỖI  Cần --base-url (hoặc --web-url cho test UI), "
              "hoặc QCTOOL_BASE_URL trong .env", file=sys.stderr)
        return 2
    if args.base_url and web_url and _host(args.base_url) != _host(web_url):
        print(f"LƯU Ý  API và web khác tên miền: {_host(args.base_url)} "
              f"vs {_host(web_url)}")

    token = args.token
    if not token:
        try:
            cfg.validate()
            token = cfg.bearer_token
        except config.ConfigError as exc:
            # Không có credential thì vẫn chạy — case nào cần token sẽ Fail 401,
            # đó là thông tin thật, không phải lỗi của tool.
            print(f"LƯU Ý  {exc}")
            print("       Vẫn chạy tiếp; case cần token sẽ báo 401.")
    token = token or cfg.bearer_token or ("dummy-token-for-local-test" if args.allow_anonymous else None)

    cases = _load_cases(cases_path)
    if not cases:
        print(f"LỖI  Không đọc được testcase nào từ {cases_path}", file=sys.stderr)
        return 2

    session = execute.HttpSession(base_url or web_url, bearer_token=token,
                                  timeout=cfg.timeout_seconds, verify_ssl=cfg.verify_ssl)
    print(f"Chạy {len(cases)} testcase trên {base_url or web_url}")
    print(f"  xác thực: {'có token' if token else 'KHÔNG có token'}")

    browser = None
    if execute.needs_browser(cases):
        if not web_url:
            print("  ⚠ Có bước UI nhưng thiếu --web-url → các bước đó sẽ báo chưa chạy được")
        else:
            browser = _open_browser(web_url, args, cases_path)
            if browser is not None:
                print(f"  trình duyệt: {'ẩn' if args.headless else 'hiện'} · {web_url}")
    print()

    try:
        result = execute.run_cases(
            cases, session, environment=args.environment or web_url or base_url,
            browser=browser, retry=args.retry, soft_assert=args.soft_assert,
        )
    finally:
        if browser is not None:
            browser.close()

    out_dir = Path(args.out_dir) if args.out_dir else cases_path.parent / "runs" / _stamp(result)
    report.write_json(result, out_dir / "results.json")
    report.write_csv(result, out_dir / "results.csv")
    report.write_junit(result, out_dir / "junit.xml")
    report.render_markdown(result, out_dir / "report.md")

    counts = result.counts
    print(f"  Tổng      : {result.total}")
    print(f"  Đạt       : {counts[execute.STATUS_PASS]}")
    print(f"  Lỗi       : {counts[execute.STATUS_FAIL]}")
    print(f"  Bị chặn   : {counts[execute.STATUS_BLOCKED]}")
    print(f"  Chưa chạy : {counts[execute.STATUS_NOT_EXECUTED]}")
    if counts[execute.STATUS_PASS] + counts[execute.STATUS_FAIL]:
        print(f"  Tỉ lệ đạt : {result.pass_rate:.0f}%")
    if result.flaky_cases:
        print(f"  Chập chờn : {len(result.flaky_cases)} "
              f"({', '.join(c.case_id for c in result.flaky_cases[:5])})")
    print()
    print(f"→ {out_dir}/report.md")
    if browser is not None and args.evidence != "off":
        print(f"→ {cases_path.parent}/evidence/   (ảnh, trace, log console, request lỗi)")

    if args.xlsx:
        xlsx_path = Path(args.xlsx)
        updated = render.fill_results(xlsx_path, result,
                                      executed_by=args.executed_by or "qc-tool")
        print(f"→ {xlsx_path}   (đã điền kết quả vào {updated} dòng)")

    return 1 if counts[execute.STATUS_FAIL] else 0


def _open_browser(web_url: str, args: argparse.Namespace, cases_path: Path):
    """Mở BrowserSession cho `qctool run`.

    Chỉ đăng nhập khi người dùng **yêu cầu rõ** (`--login`), hoặc khi đã có phiên
    lưu từ trước. Bài học đã trả giá một lần trong `_default_auth_mode`: chỉ cần
    `.env` có tài khoản mà tự đi đăng nhập là đoán ý người dùng — và lần này nó
    làm hỏng cả lượt chạy UI trên một trang không có form đăng nhập.

    Đăng nhập hỏng **không** làm mất trình duyệt: case UI không cần xác thực vẫn
    chạy bình thường, còn case cần xác thực sẽ báo `Blocked` như đúng nghĩa của nó.
    """
    from qctool.execute.browser import BrowserSession

    state_path = cases_path.parent / ".auth-state.json"
    evidence_dir = None if args.evidence == "off" else cases_path.parent / "evidence"
    env = config.load_config()

    try:
        browser = BrowserSession(
            web_url, headless=args.headless,
            timeout_ms=cfg_timeout(args) * 1000,
            evidence_dir=evidence_dir,
            authenticated=bool(state_path.is_file()),
            storage_state=state_path if state_path.is_file() else None,
            trace=args.trace or args.trace_sensitive, axe=args.axe,
        )
        browser.trace_sensitive = args.trace_sensitive
        if args.trace_sensitive:
            print("  ⚠ --trace-sensitive: trace chứa MẬT KHẨU/TOKEN thật — không chia sẻ/commit")
        browser.start()
    except Exception as exc:                            # noqa: BLE001
        print(f"  ⚠ Không mở được trình duyệt: {type(exc).__name__}: {exc}")
        print("    Case UI sẽ báo «chưa chạy được» chứ không báo lỗi sản phẩm.")
        return None

    if state_path.is_file():
        print(f"  dùng lại phiên đăng nhập đã lưu: {state_path}")

    if args.login:
        if not (env.username and env.password):
            print("  ⚠ --login nhưng .env thiếu QCTOOL_USERNAME/QCTOOL_PASSWORD")
        else:
            try:
                print(f"  {browser.login(env.username, env.password)}")
                browser.save_state(state_path)
            except Exception as exc:                    # noqa: BLE001
                browser.authenticated = False
                print(f"  ⚠ Đăng nhập không thành công: {exc}")
                print("    Vẫn chạy tiếp; case cần xác thực sẽ báo «bị chặn».")
    return browser


def cfg_timeout(args: argparse.Namespace) -> int:
    return int(getattr(args, "timeout", 0) or config.load_config().timeout_seconds)


def _stamp(result) -> str:
    return result.started_at.replace("-", "").replace(":", "").replace(" ", "-")


def _host(url: str) -> str:
    from urllib.parse import urlparse

    return urlparse(url).netloc


def _load_cases(path: Path) -> list[TestCase]:
    """Đọc testcases.yaml → danh sách `TestCase` chạy được."""
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    cases: list[TestCase] = []
    for raw in data.get("testcases", []):
        steps = []
        for s in raw.get("steps", []):
            steps.append(Step(
                seq=s.get("seq", len(steps) + 1),
                kind=StepKind(s.get("kind", "when")),
                action=s["action"],
                args=s.get("args", {}),
                note=s.get("note", ""), source=s.get("source", {}),
            ))
        provenance = raw.get("provenance", {})
        cases.append(TestCase(
            id=raw["id"],
            module=raw.get("module", ""),
            title=raw.get("title", ""),
            objective=raw.get("objective", ""),
            steps=steps,
            preconditions=list(raw.get("preconditions", [])),
            test_data=dict(raw.get("test_data", {})),
            traces_to=list(raw.get("traces_to", [])),
            source_quote=provenance.get("source_quote", ""),
            source_ref=provenance.get("source_ref", ""),
            generated_by=raw.get("generated_by", "engine"),
            requires=raw.get("requires"),
            execution=raw.get("execution", "auto"),
            generation_status=raw.get("generation_status"), review_reasons=raw.get("review_reasons", []),
            obligation_ids=raw.get("obligation_ids", []), source_intent=raw.get("source_intent", {}),
        ))
    return cases


def cmd_crawl(args: argparse.Namespace) -> int:
    from qctool.ui import crawl as _crawl

    url = args.url.rstrip("/")
    print(f"Đang dò element trên {url} …")
    ui_map = _crawl(url, extra_paths=args.paths or ["/"],
                    wait_ms=args.wait * 1000,
                    on_progress=lambda m: print(f"  {m}"))
    out = Path(args.out) if args.out else _pipeline.ARTIFACTS_ROOT / "ui-map.yaml"
    ui_map.save(out)
    print()
    print(f"  {len(ui_map.pages)} trang · {len(ui_map.elements)} element")
    for page in ui_map.pages:
        print(f"    {page.url}")
        for element in page.elements[:6]:
            print(f"      [{element.role:<8}] {element.name[:56]}")
        if len(page.elements) > 6:
            print(f"      … và {len(page.elements) - 6} element nữa")
    print()
    print(f"→ {out}")
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    from qctool.web import serve
    serve(port=args.port, host=args.host, open_browser=not args.no_browser)
    return 0


PROJECTS = Path("projects")

PROJECT_TEMPLATE = """\
# {name} — cấu hình chung cho mọi feature; feature ghi đè trong <feature>/qctool.yaml.
# Tài khoản/khoá API chỉ ở .env, không ghi vào đây.
web: https://app.example.com         # link webapp (bỏ nếu chỉ test API)
api: https://api.example.com         # địa chỉ API (mặc định = web)
llm: true                            # agent viết case UI từ tài liệu (cần QCTOOL_LLM_* trong .env)
# account:
#   role: customer                   # đăng nhập bằng QCTOOL_USERNAME/QCTOOL_PASSWORD
# Tuỳ chọn khác (đều có mặc định): run.timeout_seconds, ui.evidence (off|on-fail|always),
# ui.trace, ui.retry, ui.axe, generation.budget, auth.mode (browser|token|manual).
"""

FEATURE_TEMPLATE = """\
# Feature {name}. Đặt tài liệu cạnh file này: urd.md, srs.md, (srs/*flow*.md), openapi.yaml.
# Kết quả mỗi lượt chạy nằm trong ./artifacts/ — chia theo bước 1-ingest … 6-report.
# Chỉ AC liệt kê ở đây được dùng tài khoản; AC kiểu "sai mật khẩu" thì KHÔNG liệt kê.
# account:
#   login_for: [001-1, 001-3]
"""


def _project_dir(target: str) -> Path:
    path = Path(target).expanduser()
    for candidate in (path, PROJECTS / target):
        if candidate.is_file() or (candidate / "qctool.yaml").is_file() or features_of(candidate):
            return candidate
    known = sorted(p.name for p in PROJECTS.iterdir() if p.is_dir()) if PROJECTS.is_dir() else []
    hint = f" Có sẵn: {', '.join(known)}." if known else " Tạo mới: qctool init <project>/<feature>."
    raise SystemExit(f"LỖI  Không tìm thấy project '{target}'.{hint}")


def features_of(project: Path) -> list[Path]:
    return sorted(p for p in project.glob("*/qctool.yaml")) if project.is_dir() else []


def resolve_targets(target: str, only: list[str] | None = None) -> list[Path]:
    """`salonhub` → mọi `<feature>/qctool.yaml`; `salonhub/auth` hoặc file YAML → một."""
    where = _project_dir(target)
    if where.is_file():
        found = [where]
    elif (where / "qctool.yaml").is_file():
        found = [where / "qctool.yaml"]
    else:
        found = features_of(where)
    if only:
        names = {p.parent.name for p in found}
        if missing := [f for f in only if f not in names]:
            raise SystemExit(f"LỖI  '{target}' không có feature {', '.join(missing)}. "
                             f"Có: {', '.join(sorted(names))}.")
        found = [p for p in found if p.parent.name in only]
    return found


def resolve_project(target: str) -> Path:
    """Một file cấu hình duy nhất — báo lỗi nếu project có nhiều feature."""
    found = resolve_targets(target)
    if len(found) != 1:
        raise SystemExit(f"LỖI  '{target}' có {len(found)} feature — chọn một: "
                         + ", ".join(f"--{p.parent.name}" for p in found))
    return found[0]


def _each_feature(args: argparse.Namespace, *, validate_only: bool) -> int:
    from qctool.cli_run import cmd_project
    if not getattr(args, "project", None):
        return cmd_project(args, validate_only=validate_only)
    if args.config:
        raise SystemExit("LỖI  Chọn <project> hoặc --config, không dùng cả hai.")
    targets = resolve_targets(args.project, args.features)
    from qctool import summary
    started = summary.now()
    if not validate_only:
        writes = [(p.parent.name, cfg) for p in targets if (cfg := _config_or_none(p))
                  and (args.write if getattr(args, "write", None) is not None else cfg.write_mode)]
        if writes:
            from qctool.cli_run import confirm_write
            for _, cfg in writes:
                cfg.write_mode = True
            if not confirm_write(writes, args):
                return 2
            args.write_confirmed = True
    codes = []
    for path in targets:
        if len(targets) > 1:
            print(f"\n━━ {path.parent.parent.name}/{path.parent.name} " + "━" * 40)
        args.config = str(path)
        codes.append((path, cmd_project(args, validate_only=validate_only)))
    if len(targets) > 1:
        print("\n━━ Tổng hợp " + "━" * 48)
        for path, code in codes:
            print(f"  {path.parent.name:<28} {_EXIT.get(code, code)}   → {path.parent / 'artifacts'}")
    # Báo cáo tổng hợp chỉ cho lượt chạy thật theo project (projects/<p>/<feature>/qctool.yaml).
    project = targets[0].parent.parent
    if not validate_only and all(p.name == "qctool.yaml" and p.parent.parent == project for p in targets) \
            and (project / "project.yaml").is_file():
        out = summary.write_project_summary(project, [(p.parent.name, code, _artifacts_of(p)) for p, code in codes], started)
        print(f"\nBáo cáo tổng hợp: {out / 'summary.md'}")
    return max(code for _, code in codes)


def _config_or_none(path: Path):
    try:
        return PipelineConfig.from_file(path)
    except Exception:   # preflight của từng feature sẽ báo lỗi cấu hình rõ ràng
        return None


def _artifacts_of(path: Path) -> Path:
    try:
        cfg = PipelineConfig.from_file(path)
        return cfg.out_dir or _pipeline.ARTIFACTS_ROOT / cfg.feature
    except Exception:   # cấu hình hỏng: feature không chạy, summary tự đánh dấu
        return path.parent / "artifacts"


_EXIT = {0: "OK", 1: "CÓ LỖI SẢN PHẨM", 2: "LỖI CẤU HÌNH/PIPELINE", 3: "SINH CASE CHƯA ĐỦ", 4: "CÓ CASE BỊ CHẶN"}


def cmd_run(args: argparse.Namespace) -> int:
    return _each_feature(args, validate_only=False)


def cmd_check(args: argparse.Namespace) -> int:
    return _each_feature(args, validate_only=True)


def cmd_init(args: argparse.Namespace) -> int:
    project, _, feature = args.name.partition("/")
    root = PROJECTS / project
    created = []
    if not (root / "project.yaml").exists():
        root.mkdir(parents=True, exist_ok=True)
        (root / "project.yaml").write_text(PROJECT_TEMPLATE.format(name=project), encoding="utf-8")
        created.append(root / "project.yaml")
    if feature:
        path = root / feature / "qctool.yaml"
        if path.exists():
            print(f"LỖI  {path} đã có — sửa trực tiếp file đó.", file=sys.stderr)
            return 2
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(FEATURE_TEMPLATE.format(name=feature), encoding="utf-8")
        created.append(path)
    if not created:
        print(f"LỖI  {root / 'project.yaml'} đã có. Thêm feature: qctool init {project}/<feature>", file=sys.stderr)
        return 2
    for path in created:
        print(f"Đã tạo {path}")
    print(f"Tiếp theo: đặt tài liệu vào {root}/<feature>/ → qctool check {project} → qctool run {project}")
    return 0


def cmd_trace(args: argparse.Namespace) -> int:
    import subprocess
    traces = []
    for path in resolve_targets(args.project, args.features):
        cfg = PipelineConfig.from_file(path)
        evidence = (cfg.out_dir or _pipeline.ARTIFACTS_ROOT / cfg.feature) / "5-execute" / "evidence"
        traces += sorted(evidence.glob(f"{args.case_id}*.trace.zip"))
    if not traces:
        print(f"LỖI  Không có trace cho {args.case_id} trong <feature>/artifacts/5-execute/evidence/. "
              "Bật `ui.trace: true` rồi chạy lại; case có mật khẩu cố ý không có trace.", file=sys.stderr)
        return 2
    return subprocess.call([sys.executable, "-m", "playwright", "show-trace", str(traces[-1])])


def cmd_demo(args: argparse.Namespace) -> int:
    import threading
    from tests.mock_server import create_server
    try:
        server = create_server(8099, "/api/v1")
    except OSError:
        print("LỖI  Cổng 8099 đang bận — tắt tiến trình đang dùng cổng đó rồi chạy lại.", file=sys.stderr)
        return 2
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print("API giả chạy ở http://127.0.0.1:8099/api/v1 (4 bug cài sẵn — sẽ thấy cả Đạt lẫn Lỗi)")
    try:
        args.project, args.config, args.features = "demo", None, None
        return cmd_run(args)
    finally:
        server.shutdown()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="qctool", description="Tự động hoá QC: tài liệu → testcase → thực thi → báo cáo",
    )
    parser.add_argument("--version", action="version", version=f"qc-tool {__version__}")
    sub = parser.add_subparsers(dest="command", required=True, metavar="<lệnh>")

    p = sub.add_parser("init", help="Tạo project/feature: init <project> | init <project>/<feature>")
    p.add_argument("name", help="salonhub (tạo project.yaml) hoặc salonhub/auth (thêm feature)")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("check", help="Kiểm tra project/feature, không gọi model/browser/API")
    _project_flags(p)
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("run", help="Chạy mọi feature của project, hoặc chỉ --<feature>")
    _project_flags(p)
    p.add_argument("--show-browser", dest="headless", action="store_false", help="Hiện cửa sổ trình duyệt")
    p.add_argument("--only", nargs="+", metavar="AC", help="Chỉ sinh case cho các AC này (vd: 001-1 001-3)")
    p.add_argument("--write", dest="write", action="store_const", const=True, default=None,
                   help="CHẾ ĐỘ GHI: cho tạo/sửa/xoá dữ liệu thật (đè `mode` trong config; cần xác nhận)")
    p.add_argument("--safe", dest="write", action="store_const", const=False,
                   help="Chỉ đọc, kể cả khi config đặt `mode: write`")
    p.add_argument("--yes", action="store_true", help="Không hỏi xác nhận chế độ ghi (CI)")
    p.add_argument("--trace-sensitive", action="store_true", default=None,
                   help="Trace cả case có mật khẩu (file chứa bí mật — chỉ dùng cục bộ)")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("trace", help="Mở trace Playwright của một testcase")
    p.add_argument("project", help="Tên project (thêm --<feature> để thu hẹp)")
    p.add_argument("case_id", help="Mã testcase, vd TC_AUTH_001")
    p.add_argument("-f", "--feature", dest="features", action="append", help=argparse.SUPPRESS)
    p.set_defaults(func=cmd_trace)

    p = sub.add_parser("ui", help="Mở giao diện web")
    p.add_argument("--port", type=int, default=8080, help="Cổng (mặc định 8080)")
    p.add_argument("--host", default="127.0.0.1", help="Địa chỉ lắng nghe")
    p.add_argument("--no-browser", action="store_true", help="Không tự mở trình duyệt")
    p.set_defaults(func=cmd_serve)

    p = sub.add_parser("demo", help="Chạy thử trên API giả (projects/demo)")
    p.add_argument("--show-browser", dest="headless", action="store_false", help=argparse.SUPPRESS)
    p.set_defaults(func=cmd_demo, config=None, llm=None, features=None)

    _step_parsers(sub.add_parser("step", help="Chạy từng chặng (nâng cao)")
                  .add_subparsers(dest="step", required=True, metavar="<chặng>"))
    return parser


def _step_parsers(sub) -> None:
    p_ingest = sub.add_parser("ingest", help="Đọc tài liệu feature → requirements.yaml")
    p_ingest.add_argument("feature_dir", help="Thư mục chứa urd.md + srs.md")
    p_ingest.add_argument("--feature", help="Tên feature (mặc định: tên thư mục)")
    p_ingest.add_argument("--out", help="Đường dẫn file ra (mặc định: artifacts/<feature>/requirements.yaml)")
    p_ingest.add_argument("--strict", action="store_true", help="Có cảnh báo thì trả mã lỗi 1")
    p_ingest.set_defaults(func=cmd_ingest)

    p_gen = sub.add_parser("generate", help="Sinh testcase từ requirement và/hoặc OpenAPI (không gọi LLM)")
    p_gen.add_argument("--requirements", help="File requirements.yaml (từ chặng ingest)")
    p_gen.add_argument("--openapi", help="File OpenAPI spec")
    p_gen.add_argument("--module", help="Ghi đè tên module cho case sinh từ requirement")
    p_gen.add_argument("--out", help="Đường dẫn file testcases.yaml")
    p_gen.add_argument("--xlsx", help="Xuất thêm file Excel theo template team")
    p_gen.add_argument("--created-by", help="Ghi vào cột 'Created By / Date'")
    p_gen.add_argument("--strict", action="store_true",
                       help="Có gap/cảnh báo thì trả mã lỗi 1 (dùng cho CI)")
    p_gen.set_defaults(func=cmd_generate)

    p_exec = sub.add_parser("exec", help="Chạy testcases.yaml đã có")
    p_exec.add_argument("testcases", help="File testcases.yaml")
    p_exec.add_argument("--base-url", help="Địa chỉ API cần test (mặc định: QCTOOL_BASE_URL)")
    p_exec.add_argument("--web-url", help="Link webapp — cần khi có bước UI/UX")
    p_exec.add_argument("--token", help="Bearer token (mặc định: lấy từ .env)")
    p_exec.add_argument("--allow-anonymous", action="store_true",
                        help="Chạy không token — case cần xác thực sẽ báo 401")
    p_exec.add_argument("--environment", help="Nhãn môi trường ghi vào báo cáo")
    p_exec.add_argument("--xlsx", help="Ghi kết quả ngược vào file testcase này")
    p_exec.add_argument("--executed-by", help="Ghi vào cột 'Executed By / Date'")
    p_exec.add_argument("--out-dir", help="Thư mục chứa kết quả")
    p_exec.add_argument("--show-browser", dest="headless", action="store_false",
                        help="Hiện cửa sổ trình duyệt thay vì chạy ẩn")
    p_exec.add_argument("--login", action="store_true",
                        help="Đăng nhập bằng tài khoản trong .env trước khi chạy")
    p_exec.add_argument("--retry", type=int, default=0, help="Số lần chạy lại case hỏng (0–3)")
    p_exec.add_argument("--evidence", choices=["off", "on-fail", "always"], default="on-fail",
                        help="Lưu ảnh bằng chứng (mặc định: khi hỏng)")
    p_exec.add_argument("--trace", action="store_true", help="Lưu trace Playwright mỗi case")
    p_exec.add_argument("--trace-sensitive", action="store_true",
                        help="Trace cả case có mật khẩu (file chứa bí mật — chỉ dùng cục bộ)")
    p_exec.add_argument("--axe", action="store_true", help="Bật quét accessibility")
    p_exec.add_argument("--soft-assert", action="store_true", help="Bước kiểm tra sai không dừng case")
    p_exec.add_argument("--timeout", type=int, help="Thời gian chờ mỗi bước (giây)")
    p_exec.set_defaults(func=cmd_run_testcases)

    p_crawl = sub.add_parser("crawl", help="Dò element trên webapp → ui-map.yaml")
    p_crawl.add_argument("url", help="Địa chỉ webapp")
    p_crawl.add_argument("--paths", nargs="*", help="Các đường dẫn phụ cần dò thêm")
    p_crawl.add_argument("--wait", type=float, default=2.0, help="Giây chờ trang render (mặc định 2)")
    p_crawl.add_argument("--out", help="Đường dẫn file ra (mặc định artifacts/ui-map.yaml)")
    p_crawl.set_defaults(func=cmd_crawl)


def _project_flags(parser):
    parser.add_argument('project', nargs='?', help='Project trong projects/ (vd salonhub), salonhub/<feature>, hoặc file YAML')
    parser.add_argument('-f', '--feature', dest='features', action='append', metavar='FEATURE',
                        help='Chỉ chạy feature này (lặp lại được). Viết tắt: --<tên feature>, vd --auth')
    parser.add_argument('--config', help=argparse.SUPPRESS)
    parser.add_argument('--docs', '--docs-dir', dest='docs', help='Ghi đè thư mục URD/SRS/flows')
    parser.add_argument('--openapi', help='Ghi đè file OpenAPI')
    parser.add_argument('--url', help='Ghi đè link webapp')
    parser.add_argument('--out', help='Thư mục artifacts')
    parser.add_argument('--profile', choices=('agent',), help=argparse.SUPPRESS)
    parser.add_argument('--module', help=argparse.SUPPRESS)
    parser.add_argument('--llm', action=argparse.BooleanOptionalAction, default=None,
                        help='Bật/tắt LLM (mặc định theo project); model/key lấy từ QCTOOL_LLM_*')
    parser.add_argument('--allow-provisioning', action=argparse.BooleanOptionalAction, default=None,
                        help=argparse.SUPPRESS)
    parser.add_argument('--test-environment', help=argparse.SUPPRESS)
    parser.add_argument('--skip-run', action='store_true', help='Chỉ sinh testcase, không chạy')


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args, unknown = parser.parse_known_args(argv)
    # `run salonhub --auth` — tên feature dùng thẳng làm cờ. Chỉ nhận đúng
    # tên thư mục feature có thật; còn lại vẫn là lỗi cờ lạ như argparse thường.
    if unknown and getattr(args, "project", None) and hasattr(args, "features"):
        names = {p.parent.name for p in resolve_targets(args.project)}
        for token in unknown:
            if token.startswith("--") and token[2:] in names:
                args.features = [*(args.features or []), token[2:]]
            else:
                parser.error(f"cờ không hợp lệ: {token}" + (f" (feature có: {', '.join(sorted(names))})" if token.startswith("--") else ""))
    elif unknown:
        parser.error(f"cờ không hợp lệ: {' '.join(unknown)}")
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
