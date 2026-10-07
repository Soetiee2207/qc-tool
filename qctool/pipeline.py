"""Chạy cả 4 chặng trong một lần — đây là thứ người dùng thật sự gọi.

    tài liệu + spec + môi trường  →  requirements  →  testcase  →  chạy  →  báo cáo

Một hàm `run_pipeline()` duy nhất, để CLI, web UI, và CI dùng chung một đường đi.
Không có logic nào chỉ tồn tại trong giao diện.
"""

from __future__ import annotations

import json
import traceback
import urllib.parse
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import yaml

from . import config as cfg_mod
from . import execute, generate, ingest, render, report, validate
from .generation import GenerationResult, GenerationStatus, run_generation
from .coverage import analyze_coverage
from .executability import analyze_executability
from .llm_resolution import ResolutionLLM
from .llm_exploration import ExplorationLLM
from .llm_provider import load_llm_provider
from .test_fixtures import FixtureStore, load_fixture_store

ProgressFn = Callable[[str, str], None]      # (bước, mô tả)


def _noop(stage: str, message: str) -> None:
    pass


@dataclass
class PipelineConfig:
    """Mọi thứ cần để chạy một lượt QC."""

    # Đầu vào
    docs_dir: Path | None = None        # thư mục chứa urd.md + srs.md
    openapi: Path | None = None         # file OpenAPI spec
    web_url: str = ""                   # link webapp cần test (dùng trình duyệt)
    feature: str = "feature"            # tên feature, dùng cho ID và tên thư mục
    module: str | None = None           # module cho case sinh từ tài liệu

    # Môi trường chạy
    base_url: str = ""
    auth_mode: str = "manual"           # password | token | manual
    username: str | None = None
    password: str | None = None
    bearer_token: str | None = None
    timeout_seconds: int = 30
    verify_ssl: bool = True

    # Hành vi
    skip_run: bool = False              # chỉ sinh testcase, không chạy
    headless: bool = True               # chạy trình duyệt ẩn
    out_dir: Path | None = None         # mặc định: artifacts/<feature>/
    created_by: str = "qc-tool"
    fixture_store: FixtureStore | None = field(default=None, repr=False)
    llm_enabled: bool = False          # chỉ bật tường minh; không suy từ credential
    allow_provisioning: bool = False   # opt-in, vẫn phải qua reviewed engine policy
    data_environment: str | None = None

    # ── UI/UX test (Playwright) ────────────────────────────────────────────
    ui_retry: int = 0                   # số lần chạy lại case hỏng (tối đa 3)
    ui_evidence: str = "on-fail"        # off | on-fail | always
    ui_trace: bool = False              # lưu trace Playwright (.zip) mỗi case
    ui_axe: bool = False                # bật quét accessibility
    soft_assert: bool = False           # bước kiểm tra sai không dừng case
    viewport: tuple[int, int] = (1440, 900)

    @classmethod
    def from_file(cls, path: Path) -> "PipelineConfig":
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        base = path.parent

        def resolve(value: str | None) -> Path | None:
            if not value:
                return None
            p = Path(value).expanduser()
            return p if p.is_absolute() else (base / p)

        run = data.get("run", {}) or {}
        auth = data.get("auth", {}) or {}
        out = data.get("out", {}) or {}
        ui = data.get("ui", {}) or {}
        llm = data.get("llm", {}) or {}
        provisioning = data.get("provisioning", {}) or {}
        allow_provisioning = provisioning.get("enabled", False)
        if type(allow_provisioning) is not bool:
            raise cfg_mod.ConfigError("provisioning.enabled must be a boolean.")

        # Tài khoản lấy từ `.env` nếu file cấu hình không ghi.
        # Nhờ vậy `qc.yaml` commit được mà không lộ bí mật, còn người dùng vẫn
        # chỉ cần chạy một lệnh.
        env = cfg_mod.load_config()
        llm_enabled = llm.get("enabled", cfg_mod._flag("QCTOOL_LLM_ENABLED", False))
        if type(llm_enabled) is not bool:
            raise cfg_mod.ConfigError("llm.enabled must be a boolean.")

        username = auth.get("username") or env.username
        password = auth.get("password") or env.password
        bearer_token = auth.get("token") or env.bearer_token
        web_url = (data.get("web_url") or "").rstrip("/")

        if (mode := auth.get("mode")) is None:
            if web_url and username:
                mode = "browser"
            elif bearer_token:
                mode = "token"
            else:
                mode = "manual"

        return cls(
            docs_dir=resolve(data.get("docs_dir")),
            openapi=resolve(data.get("openapi")),
            web_url=web_url,
            feature=data.get("feature") or "feature",
            module=data.get("module"),
            base_url=(run.get("base_url") or "").rstrip("/"),
            auth_mode=mode,
            username=username,
            password=password,
            bearer_token=bearer_token,
            timeout_seconds=int(run.get("timeout_seconds", 30)),
            verify_ssl=bool(run.get("verify_ssl", True)),
            skip_run=bool(out.get("skip_run", False)),
            headless=bool(out.get("headless", True)),
            out_dir=resolve(out.get("dir")),
            created_by=out.get("created_by") or "qc-tool",
            llm_enabled=llm_enabled,
            allow_provisioning=allow_provisioning,
            data_environment=provisioning.get("environment"),
            fixture_store=load_fixture_store(data.get("test_fixtures")),
            ui_retry=max(0, min(int(ui.get("retry", 0) or 0), 3)),
            ui_evidence=str(ui.get("evidence", "on-fail") or "on-fail"),
            ui_trace=bool(ui.get("trace", False)),
            ui_axe=bool(ui.get("axe", False)) or "assert.axe" in _verbs_in_file(path),
            soft_assert=bool(ui.get("soft_assert", False)),
            viewport=_viewport_of(ui),
        )


def _viewport_of(ui: dict) -> tuple[int, int]:
    raw = ui.get("viewport") or {}
    if isinstance(raw, str) and "x" in raw.lower():
        width, _, height = raw.lower().partition("x")
        raw = {"width": width, "height": height}
    if not isinstance(raw, dict):
        return (1440, 900)
    try:
        return (int(raw.get("width", 1440)), int(raw.get("height", 900)))
    except (TypeError, ValueError):
        return (1440, 900)


def _verbs_in_file(path: Path) -> set[str]:
    """Verb xuất hiện trong file — để bật axe khi case nào đó cần `assert.axe`.

    Đọc bằng regex chứ không parse YAML: file cấu hình có thể trỏ tới testcase
    ở nơi khác, và ở đây chỉ cần biết "có hay không".
    """
    import re

    with_path = path.with_name("testcases.yaml")
    if not with_path.is_file():
        return set()
    return set(re.findall(r"action:\s*([a-z_.]+)", with_path.read_text(encoding="utf-8")))


@dataclass
class PipelineResult:
    ok: bool = False
    feature: str = ""
    out_dir: Path | None = None
    requirements_path: Path | None = None
    testcases_path: Path | None = None
    xlsx_path: Path | None = None
    run_dir: Path | None = None
    report_path: Path | None = None
    counts: dict = field(default_factory=dict)
    total_cases: int = 0
    generated_report: object | None = None      # validate.Report
    run_result: object | None = None            # execute.RunResult
    error: str | None = None
    log: list[str] = field(default_factory=list)
    generation_result: GenerationResult | None = None
    generation_path: Path | None = None

    @property
    def generation_status(self) -> str | None:
        return self.generation_result.status.value if self.generation_result is not None else None

    @property
    def generation_success(self) -> bool:
        return self.generation_result is not None and self.generation_result.success

    @property
    def pass_rate(self) -> float:
        executed = self.counts.get("Pass", 0) + self.counts.get("Fail", 0)
        return (self.counts.get("Pass", 0) / executed * 100) if executed else 0.0


def run_pipeline(cfg: PipelineConfig, on_progress: ProgressFn | None = None, *,
                 resolution_llm: ResolutionLLM | None = None,
                 exploration_llm: ExplorationLLM | None = None) -> PipelineResult:
    """Chạy toàn bộ pipeline. Không bao giờ ném lỗi ra ngoài — trả về `error`."""
    progress = on_progress or _noop
    result = PipelineResult(feature=cfg.feature)

    def safe(message: str) -> str:
        return cfg.fixture_store.redact(message) if cfg.fixture_store else message

    def notify(stage: str, message: str) -> None:
        progress(stage, safe(message))

    def log(message: str) -> None:
        result.log.append(safe(message))

    try:
        if cfg.llm_enabled and (resolution_llm is None or exploration_llm is None):
            adapter = load_llm_provider()
            resolution_llm = resolution_llm if resolution_llm is not None else adapter
            exploration_llm = exploration_llm if exploration_llm is not None else adapter
            log("LLM provider bật tường minh; proposal/plan vẫn qua deterministic validator")
        out_dir = cfg.out_dir or Path("artifacts") / cfg.feature
        result.out_dir = out_dir
        out_dir.mkdir(parents=True, exist_ok=True)

        # ── Chặng 1 ────────────────────────────────────────────────────────
        requirements_path: Path | None = None
        if cfg.docs_dir:
            notify("ingest", f"Đọc tài liệu từ {cfg.docs_dir}")
            if not cfg.docs_dir.is_dir():
                raise FileNotFoundError(f"Không tìm thấy thư mục tài liệu: {cfg.docs_dir}")
            data = ingest.ingest_feature(cfg.docs_dir, cfg.feature)
            requirements_path = out_dir / "requirements.yaml"
            ingest.write_yaml(data, requirements_path)
            counts = data["counts"]
            message = (f"Đọc được {counts.get('total', 0)} requirement "
                       f"({counts.get('user_story', 0)} US, "
                       f"{counts.get('acceptance_criterion', 0)} AC, "
                       f"{counts.get('functional', 0)} FR, "
                       f"{counts.get('non_functional', 0)} NFR)")
            notify("ingest", message)
            log(message)
            for warning in data.get("warnings", []):
                log(f"  ⚠ {warning}")
        else:
            notify("ingest", "Không có tài liệu — bỏ qua chặng ingest")

        result.requirements_path = requirements_path

        # ── Chặng 2 ────────────────────────────────────────────────────────
        notify("generate", "Sinh testcase…")
        if not requirements_path and not cfg.openapi:
            raise ValueError(
                "Cần ít nhất một nguồn đầu vào: thư mục tài liệu (`docs_dir`) "
                "hoặc file OpenAPI (`openapi`)"
            )

        # File OpenAPI khai trong cấu hình nhưng không có → cảnh báo rồi đi tiếp,
        # KHÔNG dừng cả lượt chạy. Người dùng có thể chưa kịp export spec.
        # Nhưng phải cảnh báo thật rõ: gõ sai đường dẫn mà im lặng thì nguy hiểm.
        openapi_path = cfg.openapi
        if openapi_path and not openapi_path.is_file():
            if not requirements_path:
                raise FileNotFoundError(f"Không tìm thấy file OpenAPI: {openapi_path}")
            warning = (f"Không thấy file OpenAPI ở `{openapi_path}` — bỏ qua. "
                       f"Sẽ sinh được ít testcase hơn nhiều.")
            notify("generate", warning)
            log(f"  ⚠ {warning}")
            openapi_path = None

        # Không truyền module mặc định: `generate_all` tự suy module theo từng
        # feature. Truyền cứng ở đây sẽ dồn 29 feature vào một module duy nhất và
        # làm ID testcase đụng nhau.
        # Compatibility seeds retain existing API/NFR/flow generators and IDs.
        # run_generation below owns final generation and executable coverage.
        cases, validation, meta = generate.generate_all(
            requirements_path, openapi_path, cfg.module,
        )
        source_data = (yaml.safe_load(requirements_path.read_text(encoding="utf-8")) or {}
                       if requirements_path else {})
        endpoints = generate.load_endpoints(openapi_path)[0] if openapi_path else None
        cases = deepcopy(cases)
        # Legacy OAS seeds without x-qc-id have source_ref but no traces_to.
        # Attach only a verified interface identity, never an invented requirement.
        for case in cases:
            if case.traces_to or not case.source_ref.startswith("openapi:"):
                continue
            operation = case.source_ref.removeprefix("openapi:").split("#", 1)[0]
            requests = [step for step in case.steps if step.action == "http.request"]
            matches = [endpoint for endpoint in endpoints or []
                       if endpoint.operation_id == operation and requests
                       and all(step.args.get("method") == endpoint.method
                               and step.args.get("path") == endpoint.path for step in requests)]
            if len(matches) == 1:
                case.traces_to = [f"openapi:{operation}"]
                log(f"  Trace interface OpenAPI: {case.id} → openapi:{operation}")
        coverage_probe = analyze_coverage(
            source_data.get("requirements", []),
            [case for case in cases if analyze_executability(case).executable],
            flows=source_data.get("flows"))
        needs_ui_evidence = (any(c.needs_mapping for c in cases)
                             or bool(coverage_probe.missing_obligations))

        # ── Chặng 2b: đăng nhập + map văn xuôi → hành động cụ thể ──────────
        # Cảnh báo từ lúc đọc spec (operation bị bỏ qua, spec trộn nhiều service…)
        # phải hiện ra ngay. Nếu im lặng, người dùng chỉ thấy số testcase tụt mà
        # không biết vì sao — và sẽ tưởng tool bỏ sót phần quan trọng.
        for warning in meta.get("warnings", []):
            log(f"  ⚠ {warning}")
            notify("generate", f"⚠ {warning}"[:90])

        state_path = out_dir / ".auth-state.json"
        token_path = out_dir / ".token"
        ui_map = None
        if cfg.web_url and (needs_ui_evidence or not cfg.skip_run):
            notify("crawl", f"Mở trình duyệt tới {cfg.web_url}…")
            # Đăng nhập chỉ khi người dùng CHỌN chế độ trình duyệt. `auth.mode:
            # manual` nghĩa là "không xác thực" — chỉ vì `.env` có sẵn tài khoản
            # mà tự đi đăng nhập là đoán ý người dùng, và nó làm hỏng cả lượt chạy
            # khi webapp không có form đăng nhập (đã gặp thật).
            #
            # Phiên đã lưu **hết hạn** cũng phải đăng nhập lại: nếu không, crawl
            # chạy trong trạng thái chưa đăng nhập, UI map chỉ có màn hình login,
            # và gần như mọi case UI rơi vào "chưa map" mà không có lỗi nào được báo.
            if cfg.auth_mode == "browser" and cfg.username and cfg.password:
                need_login = not state_path.is_file()
                if not need_login:
                    from .execute.browser import BrowserSession

                    with BrowserSession(cfg.web_url, headless=cfg.headless,
                                        timeout_ms=cfg.timeout_seconds * 1000,
                                        storage_state=state_path,
                                        authenticated=True) as probe:
                        if probe.session_alive():
                            notify("crawl", "Phiên đăng nhập đã lưu còn dùng được")
                        else:
                            notify("crawl", "Phiên đăng nhập đã lưu đã hết hạn — "
                                            "đăng nhập lại")
                            need_login = True

                if need_login:
                    try:
                        notify("crawl", f"Đăng nhập bằng {cfg.username}…")
                        from .execute.browser import BrowserSession

                        with BrowserSession(cfg.web_url, headless=cfg.headless,
                                            timeout_ms=cfg.timeout_seconds * 1000) as session:
                            notify("crawl", session.login(cfg.username, cfg.password))
                            session.save_state(state_path)
                            # Lấy token để test API dùng chính phiên đăng nhập này.
                            # Không có bước này thì mọi case cần xác thực đều 401.
                            if api_token := session.extract_token():
                                token_path.write_text(api_token, encoding="utf-8")
                                notify("crawl", "Lấy được access token cho test API")
                            else:
                                notify("crawl", "Không lấy được token — case cần xác thực sẽ 401")
                    except Exception as exc:            # noqa: BLE001
                        # Đăng nhập hỏng KHÔNG được chặn phần còn lại: crawl ẩn danh
                        # vẫn dựng được UI map, và case cần xác thực sẽ báo `Blocked`
                        # kèm lý do — đúng nghĩa "thiếu điều kiện", không phải lỗi sản phẩm.
                        log(f"  ⚠ Đăng nhập không thành công: {type(exc).__name__}: {exc}")
                        notify("crawl", "Đăng nhập không thành công — crawl không cần "
                                        "đăng nhập vẫn chạy tiếp")
            try:
                if needs_ui_evidence:
                    from .ui import crawl as _crawl

                    doc_paths = _paths_from_docs(requirements_path)
                    if doc_paths:
                        notify("crawl", f"Dò thêm {len(doc_paths)} đường dẫn trích từ tài liệu")
                    fresh = _crawl(cfg.web_url, on_progress=lambda m: notify("crawl", m),
                                   storage_state=state_path if state_path.is_file() else None,
                                   extra_paths=["/", *doc_paths],
                                   anonymous_paths=["/", "/login", *doc_paths[:5]])

                    # Không ghi đè bản đồ TỐT bằng bản nghèo. Crawl có thể ra ít
                    # element vì lý do tạm thời (phiên vừa hết hạn, mạng chập), và
                    # ghi đè khi đó làm mất bản đồ đầy đủ đã dò hôm trước — lần sau
                    # mọi case UI lại thành "chưa map" mà không rõ vì sao.
                    old_path = out_dir / "ui-map.yaml"
                    kept = _keep_better_map(fresh, old_path)
                    ui_map = fresh if kept is fresh else _load_map(old_path)
                    if kept is not fresh:
                        warn = (f"⚠ Crawl lần này chỉ ra {len(fresh.elements)} element, "
                                f"ít hơn bản đồ đã có ({len(ui_map.elements)}) — giữ bản "
                                "cũ. Kiểm tra đăng nhập nếu con số này cứ thấp.")
                        notify("crawl", warn)
                        log(f"  {warn}")
                    else:
                        fresh.save(old_path)
                    notify("crawl", f"Dùng bản đồ {len(ui_map.elements)} element "
                                    f"trên {len(ui_map.pages)} trang" +
                                    ("" if kept is not fresh else " (mới dò)"))
                    # UI map nghèo là **nguyên nhân gốc** của "case chưa map được",
                    # và nó không tự lộ ra: người dùng chỉ thấy báo cáo đầy case thủ
                    # công mà không biết vì sao. Nói thẳng ra ở đây.
                    if len(ui_map.elements) < 10:
                        warn = (f"⚠ Chỉ có {len(ui_map.elements)} element — quá ít. "
                                "Nhiều khả năng chưa vào được bên trong app (chưa đăng "
                                "nhập, hoặc phiên hết hạn). Phần lớn case UI sẽ ở trạng "
                                "thái «chưa map», không phải vì tài liệu thiếu.")
                        notify("crawl", warn)
                        log(f"  {warn}")
            except Exception as exc:                    # noqa: BLE001
                log(f"  ⚠ Không crawl được: {type(exc).__name__}: {exc}")
                notify("crawl", f"Không crawl được: {type(exc).__name__}: {str(exc)[:60]}")

        if ui_map is not None:
            from .generate.mapper import map_testcases

            api_paths = _api_paths_from(meta)
            notify("map", "Map bước văn xuôi sang hành động cụ thể…")
            before = sum(1 for c in cases if c.needs_mapping)
            stats = map_testcases(cases, ui_map, cfg.web_url, api_paths)
            message = f"Map được {stats.mapped}/{before} case từ tài liệu"
            notify("map", message)
            log(message)
            if not api_paths:
                note = ("  (không có OpenAPI spec nên không map HTTP — đường dẫn "
                        "trong tài liệu chưa chắc là đường dẫn API thật)")
                notify("map", note.strip())
                log(note)
            for reason in stats.reasons[:8]:
                log(f"    · {reason}")
            if len(stats.reasons) > 8:
                log(f"    · … và {len(stats.reasons) - 8} câu nữa")

        # Reuse a cached map even when no fresh crawl is required or available.
        # Only evidence from this application may ground new resolutions.
        if ui_map is None and cfg.web_url and (out_dir / "ui-map.yaml").is_file():
            try:
                cached = _load_map(out_dir / "ui-map.yaml")
                if cached.base_url.rstrip("/") == cfg.web_url.rstrip("/"):
                    ui_map = cached
            except Exception:
                log("  ⚠ Không đọc được UI map đã lưu — generation không dùng bản đồ này")

        notify("generate", "Phân tích coverage và giải quyết testcase còn thiếu…")
        generation_result = run_generation(
            source_data.get("requirements", []), existing_cases=cases,
            flows=source_data.get("flows"), ui_map=ui_map, endpoints=endpoints,
            base_url=cfg.web_url or _resolve_base_url(cfg, meta) or None,
            storage_state=state_path if state_path.is_file() else None,
            resolution_llm=resolution_llm, exploration_llm=exploration_llm,
            module=cfg.module or "COV", fixture_store=cfg.fixture_store,
            allow_provisioning=cfg.allow_provisioning, environment=cfg.data_environment,
        )
        result.generation_result = generation_result
        generation_path = out_dir / "generation.json"
        generation_payload = generation_result.to_dict()
        if cfg.fixture_store:
            generation_payload = cfg.fixture_store.redact(generation_payload)
        generation_path.write_text(json.dumps(generation_payload,
                                             ensure_ascii=False, indent=2), encoding="utf-8")
        result.generation_path = generation_path
        summary = (f"Generation: {result.generation_status} · "
                   f"{len(generation_result.executable_cases)} executable · "
                   f"{len(generation_result.unresolved_cases)} unresolved")
        notify("generate", summary)
        log(summary)
        if not generation_result.success:
            log("  ⚠ Coverage executable chưa được xác nhận đầy đủ; xem generation.json")
        for issue in generation_result.issues:
            log(f"  ⚠ Generation {issue.code}: {issue.message}")

        cases = list(deepcopy(generation_result.cases))
        # Keep unresolved generated candidates in Excel/results for diagnosis,
        # while the unchanged runner's manual gate prevents any execution.
        pending_ids = {case.id for case in generation_result.generated_cases} - {
            case.id for case in generation_result.accepted_generated_cases}
        for case in cases:
            if case.id in pending_ids:
                case.execution = "manual"
        validation = validate.validate_batch(cases, source_data.get("requirements", []),
                                             sources=meta.get("coverage_sources"))
        result.total_cases = len(cases)
        result.generated_report = validation

        testcases_path = out_dir / "testcases.yaml"
        generate.write_cases(cases, testcases_path, meta)
        result.testcases_path = testcases_path

        xlsx_path = out_dir / "testcases.xlsx"
        render.render(cases, xlsx_path, created_by=cfg.created_by)
        result.xlsx_path = xlsx_path

        message = f"Sinh được {len(cases)} testcase"
        manual = sum(1 for c in cases if c.execution == "manual")
        if manual:
            message += f" ({manual} cần người chạy thủ công)"
        notify("generate", message)
        log(message)

        # Độ phủ theo từng nguồn — để trả lời "bộ test này có cover đủ không?"
        # bằng số liệu, thay vì để người dùng tự đoán từ con số tổng.
        coverage = validate.coverage_line(validation)
        if coverage:
            notify("generate", f"Độ phủ: {coverage}")
            log(f"Độ phủ: {coverage}")
        if validation.gaps:
            for kind, missing in sorted(validation.gaps.items()):
                if len(missing) > 6:
                    shown = f"{', '.join(missing[:6])} … +{len(missing) - 6}"
                else:
                    shown = ", ".join(missing)
                log(f"  chưa có test · {kind}: {shown}")

        # ── Chặng 3 + 4 ────────────────────────────────────────────────────
        if (not validation.ok or generation_result.status in {
                GenerationStatus.INVALID_TESTCASES, GenerationStatus.FAILED}):
            result.error = f"Generation {result.generation_status}: xem generation.json"
            log(f"LỖI: {result.error}")
            notify("error", result.error)
            return result
        if cfg.skip_run:
            notify("run", "Bỏ qua chạy test (skip_run = true)")
            log("Bỏ qua chạy test theo cấu hình")
            result.ok = True
            return result

        if not cfg.base_url and not cfg.web_url:
            notify("run", "Không có `base_url` / `web_url` — chỉ sinh testcase, không chạy")
            log("Không có địa chỉ môi trường nên không chạy test")
            result.ok = True
            return result

        # Địa chỉ API: ưu tiên cái người dùng khai, nhưng **kiểm tra lại** với spec.
        # Spec khai `servers: [https://host/api/v1]` mà config ghi `https://host` thì
        # mọi request rơi vào SPA catch-all → 404 hàng loạt → 9 case `Fail` giả
        # (đã gặp thật 2026-09-21). Thiếu tiền tố đường dẫn là lỗi im lặng: nó chỉ
        # lộ ra khi request chạy, và lúc đó trông y như bug của sản phẩm.
        target = _resolve_base_url(cfg, meta)
        if cfg.base_url and target != cfg.base_url:
            changed = (f"Địa chỉ API sửa lại theo spec: {cfg.base_url} → {target} "
                       "(config thiếu/sai tiền tố đường dẫn, để nguyên thì mọi "
                       "request sẽ 404 và báo lỗi giả)")
            notify("run", changed)
            log(f"  ⚠ {changed}")
        token = cfg.bearer_token
        if cfg.auth_mode == "browser" and cfg.username and cfg.password:
            token = None          # phiên nằm trong trình duyệt, không phải token rời
        if not token and token_path.is_file():
            # Dùng lại token lấy từ phiên đăng nhập của trình duyệt
            token = token_path.read_text(encoding="utf-8").strip() or None
            if token:
                notify("run", "Dùng access token lấy từ phiên đăng nhập")
        if cfg.auth_mode == "password" and cfg.username and cfg.password:
            notify("run", f"Đăng nhập lấy token cho {cfg.username}…")
            token = _login(cfg)
            if token:
                notify("run", "Lấy được token")
            else:
                log("  ⚠ Không lấy được token — vẫn chạy, case cần xác thực sẽ báo 401")

        session = execute.HttpSession(
            target, bearer_token=token,
            timeout=cfg.timeout_seconds, verify_ssl=cfg.verify_ssl,
        )

        # Mở trình duyệt nếu có bước UI cần chạy. Danh sách verb UI nằm một chỗ
        # duy nhất (`runner.UI_VERBS`) — trước đây chép ở hai nơi nên thêm verb
        # là phải nhớ sửa cả hai.
        browser = None
        needs_browser = execute.needs_browser(cases)
        if needs_browser and cfg.web_url:
            notify("run", "Mở trình duyệt…")
            try:
                from .execute.browser import BrowserSession

                browser = BrowserSession(
                    cfg.web_url, headless=cfg.headless,
                    timeout_ms=cfg.timeout_seconds * 1000,
                    evidence_dir=(None if cfg.ui_evidence == "off"
                                  else out_dir / "evidence"),
                    authenticated=bool(token or cfg.username),
                    storage_state=state_path if state_path.is_file() else None,
                    viewport={"width": cfg.viewport[0], "height": cfg.viewport[1]},
                    trace=cfg.ui_trace,
                    axe=cfg.ui_axe,
                )
                browser.start()
                if cfg.auth_mode == "browser" and cfg.username and not state_path.is_file():
                    # Đăng nhập hỏng KHÔNG làm mất trình duyệt: case UI không cần
                    # xác thực vẫn chạy được, còn case cần xác thực sẽ báo `Blocked`
                    # kèm lý do — đúng nghĩa "thiếu điều kiện", không phải lỗi sản phẩm.
                    try:
                        notify("run", browser.login(cfg.username, cfg.password))
                    except Exception as exc:            # noqa: BLE001
                        browser.authenticated = False
                        log(f"  ⚠ Đăng nhập không thành công: {type(exc).__name__}: {exc}")
                        notify("run", "Đăng nhập không thành công — vẫn chạy tiếp; "
                                      "case cần xác thực sẽ báo bị chặn")
            except Exception as exc:                    # noqa: BLE001
                log(f"  ⚠ Không mở được trình duyệt: {type(exc).__name__}: {exc}")
                notify("run", "Không mở được trình duyệt — case UI sẽ bị chặn")
                browser = None

        if needs_browser and browser is not None:
            extra = []
            if cfg.ui_retry:
                extra.append(f"chạy lại tối đa {cfg.ui_retry} lần khi hỏng")
            if cfg.soft_assert:
                extra.append("kiểm tra mềm")
            if cfg.ui_evidence != "off":
                extra.append("lưu ảnh bằng chứng")
            if extra:
                notify("ui", "UI/UX: " + ", ".join(extra))

        notify("run", f"Chạy {len(cases)} testcase trên {target}…")
        try:
            run_result = execute.run_cases(
                cases, session, environment=cfg.web_url or target,
                browser=browser, retry=cfg.ui_retry, soft_assert=cfg.soft_assert,
                fixture_store=cfg.fixture_store,
            )
        finally:
            if browser is not None:
                browser.close()
        result.run_result = run_result
        result.counts = run_result.counts

        # ── Chặng 4 ────────────────────────────────────────────────────────
        notify("report", "Xuất báo cáo…")
        run_dir = out_dir / "runs" / run_result.started_at.replace("-", "").replace(":", "").replace(" ", "-")
        report.write_json(run_result, run_dir / "results.json")
        report.write_csv(run_result, run_dir / "results.csv")
        report.write_junit(run_result, run_dir / "junit.xml")
        report.render_markdown(run_result, run_dir / "report.md")
        result.run_dir = run_dir
        result.report_path = run_dir / "report.md"

        # Ghi kết quả ngược vào chính file testcase — bản ghi hai pha
        filled = render.fill_results(xlsx_path, run_result, executed_by=cfg.created_by)
        notify("report", f"Đã điền kết quả vào {filled} dòng của file testcase")

        counts = run_result.counts
        summary = (f"{run_result.total} test · {counts['Pass']} đạt · "
                   f"{counts['Fail']} lỗi · {counts['Blocked']} bị chặn · "
                   f"{counts['Not Executed']} cần người chạy")
        notify("done", summary)
        log(summary)

        # Chập chờn phải được nói riêng: case chỉ đạt ở lần chạy lại không phải
        # bằng chứng chất lượng, mà là một vấn đề (race condition của sản phẩm,
        # hoặc test viết giòn) cần người xem.
        if run_result.flaky_cases:
            notify("run", f"⚠ {len(run_result.flaky_cases)} test CHẬP CHỜN "
                          f"(chỉ đạt sau khi chạy lại): "
                          + ", ".join(c.case_id for c in run_result.flaky_cases[:5]))

        # Tỉ lệ đạt chỉ tính trên test ĐÃ CHẠY ĐƯỢC — phải nói kèm mẫu số, và nói
        # rõ phần còn lại. "0 lỗi" đứng một mình rất dễ bị đọc thành "xong hết",
        # trong khi thực tế phần lớn case có thể chưa ai chạm tới.
        executed = counts['Pass'] + counts['Fail']
        parts = []
        if counts['Fail']:
            parts.append(f"{counts['Fail']} test sản phẩm trả sai")
        if counts['Not Executed']:
            parts.append(f"{counts['Not Executed']} test cần người chạy thủ công")
        if counts['Blocked']:
            parts.append(f"{counts['Blocked']} test thiếu điều kiện môi trường")
        rate = (f"Tỉ lệ đạt {run_result.pass_rate:.0f}% "
                f"({counts['Pass']}/{executed} test tự động chạy được)")
        if parts:
            rate += " · " + " · ".join(parts)
        notify("done", rate)
        log(rate)
        result.ok = True
        return result

    except Exception as exc:                       # noqa: BLE001 — báo cho người dùng, không sập
        result.error = safe(f"{type(exc).__name__}: {exc}")
        result.log.append(f"LỖI: {result.error}")
        result.log.append(safe(traceback.format_exc()))
        notify("error", result.error)
        return result


def _keep_better_map(fresh, old_path: Path):
    """Bản đồ mới hay bản đồ cũ tốt hơn?

    Trả bản **mới** nếu nó không nghèo hơn bản cũ, ngược lại trả bản cũ (đã nạp).
    Crawl có thể ra ít element vì lý do tạm thời — ghi đè khi đó làm mất dữ liệu
    dò được hôm trước, và lần sau mọi case UI lại thành "chưa map".
    """
    from .ui.crawl import UIMap

    if not old_path.is_file():
        return fresh
    try:
        old = UIMap.load(old_path)
    except Exception:                                   # noqa: BLE001
        return fresh
    if old.base_url != fresh.base_url:
        return fresh                                    # khác môi trường, không so
    return fresh if len(fresh.elements) >= len(old.elements) else old


def _load_map(path: Path):
    from .ui.crawl import UIMap

    return UIMap.load(path)


def _resolve_base_url(cfg, meta: dict) -> str:
    """Địa chỉ API cuối cùng, có đối chiếu với `servers` của spec.

    Quy tắc: nếu config trỏ **cùng tên miền** với một server trong spec nhưng
    **thiếu hoặc sai tiền tố đường dẫn**, lấy theo spec và nói ra. Đây là loại lỗi
    đã gây 9 `Fail` giả trên portal thật: `base_url: https://host` trong khi API
    nằm ở `https://host/api/v1` — request bay vào SPA catch-all và nhận HTML/404.

    Không đoán khi tên miền khác: người dùng có thể cố ý trỏ sang môi trường khác.
    """
    from_spec = _pick_base_url(meta, cfg.web_url or "")

    if not cfg.base_url:
        return from_spec or cfg.web_url

    if not from_spec:
        return cfg.base_url

    mine, theirs = urllib.parse.urlparse(cfg.base_url), urllib.parse.urlparse(from_spec)
    if mine.netloc != theirs.netloc:
        return cfg.base_url

    same_path = mine.path.rstrip("/") == theirs.path.rstrip("/")
    if same_path:
        return cfg.base_url

    # Cùng tên miền, khác đường dẫn. Spec là nguồn ground cho API — theo spec.
    return from_spec


def _pick_base_url(meta: dict, web_url: str) -> str | None:
    """Chọn địa chỉ API từ `servers` mà file OpenAPI tự khai báo.

    Đây là thông tin spec đã nói rõ — bắt người dùng gõ lại `--api` vừa thừa vừa
    dễ sai. Sai kiểu này rất khó thấy: thiếu `/api/v1` thì mọi request rơi vào
    SPA catch-all và trả về HTML, rồi báo `Lỗi` hàng loạt trong khi sản phẩm
    không có vấn đề gì.

    Ưu tiên server **cùng tên miền với link web**, vì đó gần như chắc chắn là
    môi trường người dùng đang muốn test. Không có thì lấy cái đầu tiên.
    """
    servers = ((meta.get("sources") or {}).get("openapi") or {}).get("servers") or []
    servers = [s for s in servers if s]
    if not servers:
        return None

    if web_url:
        host = urllib.parse.urlparse(web_url).netloc
        for server in servers:
            if host and urllib.parse.urlparse(server).netloc == host:
                return server.rstrip("/")

    return servers[0].rstrip("/")


def _api_paths_from(meta: dict) -> set[str]:
    """Tập đường dẫn API có thật, lấy từ OpenAPI spec đã đọc.

    Dùng để mapper chỉ map HTTP khi đường dẫn **được xác minh**. Không có spec
    thì trả về rỗng, và mapper sẽ không map HTTP nào cả.

    Hồi quy 2026-09-21: hàm này từng đọc `meta["endpoints"]`, nhưng các endpoint
    nằm ở `meta["sources"]["openapi"]["endpoints"]`. Hệ quả: **luôn** trả về rỗng,
    nên mapper từ chối mọi đường dẫn API có thật trong spec — kể cả
    `GET /api/v1/auth/config` đã được spec xác nhận. Đó là một trong những lý do
    62/65 case không chạy được dù đã có OpenAPI.
    """
    paths: set[str] = set()

    direct = meta.get("endpoints") or []
    from_sources = ((meta.get("sources") or {}).get("openapi") or {}).get("endpoints") or []

    # `meta["endpoints"]` có thể là **số đếm** (nguồn cũ ghi `endpoints: 3`) chứ
    # không phải danh sách. Chỉ nhận khi thật sự là danh sách dict — nếu không sẽ
    # sập với `TypeError` giữa lượt chạy.
    candidates = []
    if isinstance(direct, list):
        candidates += direct
    if isinstance(from_sources, list):
        candidates += from_sources

    for endpoint in candidates:
        if isinstance(endpoint, dict) and (path := endpoint.get("path")):
            paths.add(path)
    return paths


def _paths_from_docs(requirements_path: Path | None) -> list[str]:
    """Gom đường dẫn xuất hiện trong tài liệu để crawl đúng trang cần thiết.

    Tài liệu viết `/login`, `/projects`, `/upload`, `/forbidden`… đó chính là các
    trang mà testcase UI cần element. Crawl mù chỉ mở `/` rồi bỏ sót.

    Lọc bỏ đường dẫn trông như API (`/api/v1/...`) và file tĩnh — chúng không phải
    trang có element để bấm.
    """
    import re

    if not requirements_path or not requirements_path.is_file():
        return []

    data = yaml.safe_load(requirements_path.read_text(encoding="utf-8")) or {}
    blobs: list[str] = []

    for req in data.get("requirements", []):
        for key in ("statement", "title", "when", "then", "given"):
            if value := req.get(key):
                blobs.append(str(value))
        if api := req.get("api"):
            blobs.extend(str(s) for s in api.get("flow", []))

    per_feature = data.get("flows") or {}
    for payload in ({"": per_feature} if "counts" in per_feature else per_feature).values():
        if not isinstance(payload, dict):
            continue
        for kind in ("flow", "decision", "transition", "error_surface", "scenario"):
            for item in payload.get(kind, []):
                blobs.append(json.dumps(item, ensure_ascii=False))

    found: list[str] = []
    seen: set[str] = set()
    pattern = re.compile(r"(?<![\w:])/([a-z][\w\-/]{2,40})")
    for blob in blobs:
        for match in pattern.finditer(blob):
            path = "/" + match.group(1).rstrip("/.,;:)")
            lower = path.lower()
            if lower.startswith(("/api", "/realms", "/static", "/assets", "/_next")):
                continue
            if path.count("/") > 3:                  # quá sâu cho một trang
                continue
            if path in seen:
                continue
            seen.add(path)
            found.append(path)
    return found[:12]


def _login(cfg: PipelineConfig) -> str | None:
    """Đăng nhập lấy bearer token qua OIDC Resource Owner Password flow."""
    import json
    import urllib.error
    import urllib.parse
    import urllib.request

    issuer = cfg_mod.load_config().oidc_issuer
    if not issuer:
        return None
    url = f"{issuer.rstrip('/')}/protocol/openid-connect/token"
    payload = urllib.parse.urlencode({
        "grant_type": "password",
        "client_id": cfg_mod.load_config().oidc_client_id or "account",
        "username": cfg.username,
        "password": cfg.password,
    }).encode()
    request = urllib.request.Request(
        url, data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(request, timeout=cfg.timeout_seconds) as resp:
            return json.loads(resp.read().decode()).get("access_token")
    except (urllib.error.URLError, json.JSONDecodeError, KeyError):
        return None
