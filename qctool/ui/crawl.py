"""Crawl webapp → UI map.

Đây là thứ còn thiếu khiến case sinh từ tài liệu không chạy được. Tài liệu viết
*"Click Sign in with Keycloak"* — nhưng tool không biết nút đó có thật trên trang
hay không, cũng không biết tìm nó bằng gì.

Crawl xong thì có danh sách element **có thật**, và mapper chỉ được phép tham chiếu
những element nằm trong danh sách đó. Không có trong map → không map → case báo
`Blocked` chứ không đoán bừa ra một selector rồi chạy sai.
"""

from __future__ import annotations

import contextlib
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import yaml

# Thẻ HTML coi là phần tử tương tác được
INTERACTIVE = {
    "button": "button",
    "a": "link",
    "input": "input",
    "select": "combobox",
    "textarea": "textbox",
}


@dataclass
class Element:
    id: str
    role: str
    name: str
    tag: str
    input_type: str | None = None
    required: bool = False
    href: str | None = None
    # Test id (`data-testid` và các biến thể). Đây là thứ **bền nhất** để trỏ tới
    # element: đổi giao diện không đổi id, còn nhãn hiển thị thì đổi suốt. Crawl
    # ghi lại để mapper dùng `target: <test_id>` thay vì dò theo chữ.
    test_id: str | None = None
    # Trạng thái lúc crawl — để biết element này vốn bị khoá hay không, thay vì
    # đoán khi sinh case `assert.disabled`.
    disabled: bool = False
    checked: bool = False
    options: list[dict] = field(default_factory=list)

    @property
    def selector(self) -> dict:
        """Selector bền nhất có thể: test id trước, rồi mới tới role + tên."""
        if self.test_id:
            return {"test_id": self.test_id, "role": self.role, "name": self.name}
        return {"role": self.role, "name": self.name}

    def to_dict(self) -> dict:
        out = {"id": self.id, "role": self.role, "name": self.name}
        if self.test_id:
            out["test_id"] = self.test_id
        if self.input_type:
            out["input_type"] = self.input_type
        if self.required:
            out["required"] = True
        if self.disabled:
            out["disabled"] = True
        if self.checked:
            out["checked"] = True
        if self.tag in {"select", "textarea"}:
            out["tag"] = self.tag
        if self.options:
            out["options"] = self.options
        if self.href:
            out["href"] = self.href
        return out


@dataclass
class PageMap:
    url: str
    title: str
    text: list[str] = field(default_factory=list)     # các đoạn chữ nhìn thấy được
    elements: list[Element] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "url": self.url,
            "title": self.title,
            "text": self.text[:60],
            "elements": [e.to_dict() for e in self.elements],
        }


@dataclass
class UIMap:
    base_url: str
    crawled_at: str
    pages: list[PageMap] = field(default_factory=list)

    @property
    def elements(self) -> list[Element]:
        return [e for page in self.pages for e in page.elements]

    def find(self, name: str) -> Element | None:
        """Tìm element gần đúng nhất với `name`.

        Khớp chính xác trước; không có thì khớp không phân biệt hoa thường;
        cuối cùng mới tới khớp một phần. Trả `None` nếu không chắc — để case
        ở trạng thái chưa map còn hơn map sai.

        Hàm này **cố ý lỏng**: câu `Click Sign in with Keycloak` phải khớp được
        nút `Sign in` có thật. Việc chặn map bịa nằm ở phía gọi — nhánh *nhãn trần*
        của mapper không được coi câu điều kiện (`refresh fail no upload`) là một
        cái nút (`Refresh`).
        """
        needle = _norm(name)
        if not needle:
            return None

        for element in self.elements:
            if _norm(element.name) == needle:
                return element
        for element in self.elements:
            if needle in _norm(element.name):
                return element
        # tên trong tài liệu có thể là một phần của nhãn dài hơn
        for element in self.elements:
            if _norm(element.name) and _norm(element.name) in needle:
                return element
        return None

    def to_dict(self) -> dict:
        return {
            "base_url": self.base_url,
            "crawled_at": self.crawled_at,
            "pages": [p.to_dict() for p in self.pages],
        }

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        header = (
            "# Bản đồ element của webapp — sinh tự động, KHÔNG sửa tay.\n"
            "# Sinh lại: uv run qctool crawl <url>\n"
            "#\n"
            "# Mapper chỉ được tham chiếu element có trong file này.\n"
            "# Không có trong đây ⇒ case báo `Blocked`, không đoán selector.\n"
        )
        path.write_text(
            header + yaml.safe_dump(self.to_dict(), allow_unicode=True, sort_keys=False, width=100),
            encoding="utf-8",
        )

    @classmethod
    def load(cls, path: Path) -> "UIMap":
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        pages = []
        for raw in data.get("pages", []):
            pages.append(PageMap(
                url=raw.get("url", ""),
                title=raw.get("title", ""),
                text=list(raw.get("text", [])),
                elements=[Element(
                    id=e["id"], role=e.get("role", "button"), name=e.get("name", ""),
                    tag=e.get("tag", e.get("role", "button")),
                    input_type=e.get("input_type"), required=e.get("required", False),
                    href=e.get("href"), test_id=e.get("test_id"),
                    disabled=e.get("disabled", False), checked=e.get("checked", False),
                    options=list(e.get("options", [])),
                ) for e in raw.get("elements", [])],
            ))
        return cls(base_url=data.get("base_url", ""),
                   crawled_at=data.get("crawled_at", ""), pages=pages)


def _norm(text: str) -> str:
    text = re.sub(r"[^\w\s]", " ", (text or "").lower())
    return re.sub(r"\s+", " ", text).strip()


# Từ đệm tài liệu hay thêm quanh tên phần tử.
#
# Hai loại: **động từ hành động** ("**Click** Sign in") và **loại phần tử**
# ("Sign in **button**"). Cả hai đều không mang thông tin về việc tìm element —
# bỏ đi mà chuỗi còn rỗng nghĩa là phần thừa không nói lên điều gì.
FILLER_WORDS = frozenset({
    # động từ
    "click", "bam", "nhan", "chon", "vao", "len", "clicking", "tap", "press",
    "open", "mo", "di", "toi", "truy", "cap",
    # loại phần tử
    "button", "nut", "link", "lien", "tab", "field", "o", "input",
    "checkbox", "radio", "select", "dropdown", "menu", "icon", "image", "the",
})


def _only_filler_words(text: str) -> bool:
    """Chuỗi này chỉ còn toàn từ đệm (hoặc rỗng)?"""
    return all(word in FILLER_WORDS for word in text.split())


def _slug(text: str, fallback: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", (text or "").lower()).strip("_")
    return slug[:40] or fallback


def crawl(base_url: str, extra_paths: list[str] | None = None,
          timeout_ms: int = 30000, wait_ms: int = 2000,
          on_progress=None, storage_state: Path | None = None,
          anonymous_paths: list[str] | None = None,
          follow_links: bool = True,
          max_pages: int = 15) -> UIMap:
    """Mở webapp bằng trình duyệt thật, ghi lại element tương tác được.

    Chờ trang **render xong** chứ không chỉ tải xong HTML. Với SPA (React/Vue),
    `domcontentloaded` bắn trước khi JS chạy — lúc đó DOM còn rỗng và crawl ra
    0 element dù trang thật có đủ nút. Nên phải chờ tới khi thấy element đầu tiên.

    **Hai pha, và thứ tự quan trọng.** Pha 1 chạy KHÔNG có phiên đăng nhập, để
    thấy được màn hình `/login` cùng nút "Sign in with Keycloak". Pha 2 nạp
    `storage_state` rồi mới crawl phần sau đăng nhập.

    Trước đây chỉ có pha 2: tool đăng nhập trước rồi crawl `/`, nên bị đá thẳng
    vào dashboard và **không bao giờ thấy màn hình login**. Hệ quả là mọi case
    luồng đăng nhập đều không map được, vì element `Sign in with Keycloak` không
    tồn tại trong `ui-map.yaml`.
    """
    from playwright.sync_api import sync_playwright

    notify = on_progress or (lambda _m: None)
    base = base_url.rstrip("/")
    ui = UIMap(base_url=base, crawled_at=datetime.now().strftime("%Y-%m-%d %H:%M"))
    seen_urls: set[str] = set()

    anon = anonymous_paths if anonymous_paths is not None else ["/", "/login"]
    private = extra_paths or ["/"]

    with sync_playwright() as pw:
        browser = pw.chromium.launch()

        # ── Pha 1: chưa đăng nhập ───────────────────────────────────────────
        notify("Pha 1 — crawl khi CHƯA đăng nhập (để thấy màn hình login)")
        context = browser.new_context(
            viewport={"width": 1440, "height": 900}, ignore_https_errors=True,
        )
        context.set_default_timeout(timeout_ms)
        page = context.new_page()
        try:
            _crawl_paths(page, ui, base, anon, timeout_ms, wait_ms, notify, seen_urls)
            if follow_links:
                _follow(page, ui, base, timeout_ms, wait_ms, notify, seen_urls,
                        budget=max_pages - len(ui.pages))
        finally:
            context.close()

        # ── Pha 2: sau đăng nhập ────────────────────────────────────────────
        if storage_state and storage_state.is_file():
            notify("Pha 2 — crawl SAU khi đăng nhập")
            # URL identity is scoped to the browser session. An anonymous visit
            # may have redirected to login; it cannot stand in for the same
            # requested route with trusted authenticated storage state.
            seen_urls = set()
            context = browser.new_context(
                viewport={"width": 1440, "height": 900}, ignore_https_errors=True,
                storage_state=str(storage_state),
            )
            context.set_default_timeout(timeout_ms)
            page = context.new_page()
            try:
                _crawl_paths(page, ui, base, private, timeout_ms, wait_ms, notify,
                             seen_urls)
                if follow_links:
                    _follow(page, ui, base, timeout_ms, wait_ms, notify, seen_urls,
                            budget=max_pages - len(ui.pages))
            finally:
                context.close()

        browser.close()
    return ui


def _crawl_paths(page, ui: UIMap, base: str, paths: list[str], timeout_ms: int,
                 wait_ms: int, notify, seen_urls: set[str]) -> None:
    for path in paths:
        url = base + ("" if path in ("/", "") else path)
        if url in seen_urls:
            continue
        seen_urls.add(url)
        notify(f"  mở {url}")
        snapshot = _snapshot(page, url, timeout_ms, wait_ms, notify)
        if snapshot is not None:
            ui.pages.append(snapshot)
            notify(f"    → {len(snapshot.elements)} element, {len(snapshot.text)} đoạn chữ")


def _follow(page, ui: UIMap, base: str, timeout_ms: int, wait_ms: int,
            notify, seen_urls: set[str], budget: int) -> None:
    """Dò tiếp link nội bộ tìm được trên các trang vừa crawl.

    Giới hạn bằng `budget`: crawl lan man tốn thời gian mà không thêm nhiều giá
    trị. Chỉ lấy link cùng tên miền và cùng đường dẫn gốc với `base`.
    """
    if budget <= 0:
        return
    host = urlparse(base).netloc
    queue: list[str] = []
    for page_map in ui.pages:
        for element in page_map.elements:
            if element.role != "link" or not element.href:
                continue
            href = element.href
            if href.startswith("/"):
                href = base + href
            parsed = urlparse(href)
            if parsed.netloc != host or not parsed.path:
                continue
            if href in seen_urls or "#" in href:
                continue
            queue.append(href)

    taken = 0
    for href in dict.fromkeys(queue):           # giữ thứ tự, bỏ trùng
        if taken >= budget:
            break
        if href in seen_urls:
            continue
        seen_urls.add(href)
        notify(f"  dò link {href}")
        snapshot = _snapshot(page, href, timeout_ms, wait_ms, notify, quiet=True)
        if snapshot is not None:
            ui.pages.append(snapshot)
            taken += 1
            notify(f"    → {len(snapshot.elements)} element")


def _snapshot(page, url: str, timeout_ms: int, wait_ms: int, notify,
              quiet: bool = False) -> PageMap | None:
    """Mở một URL và ghi lại element + chữ nhìn thấy được."""
    try:
        page.goto(url, timeout=timeout_ms, wait_until="load")
    except Exception as exc:                        # noqa: BLE001
        if not quiet:
            notify(f"    ⚠ không mở được: {type(exc).__name__}: {str(exc)[:70]}")
        return None

    if not _wait_for_render(page, max_wait_ms=max(wait_ms, 8000)) and not quiet:
        notify("    ⚠ trang tải được nhưng không thấy element nào render "
               "(trang trắng, hoặc cần đăng nhập)")

    elements: list[Element] = []
    seen: set[tuple[str, str]] = set()
    for tag, role in INTERACTIVE.items():
        for handle in page.locator(tag).all():
            try:
                name = _element_name(handle)
                test_id = _test_id(handle)
                # Element có test id mà không có chữ hiển thị (nút icon chẳng hạn)
                # vẫn phải vào map — nếu không thì mapper không thấy nó tồn tại và
                # case sẽ bị đánh dấu chưa map một cách vô cớ.
                if not name and not test_id:
                    continue
                input_type = handle.get_attribute("type") if tag == "input" else None
                key = (role, _norm(name or test_id or ""))
                if key in seen:
                    continue
                seen.add(key)
                elements.append(Element(
                    id=_slug(name or test_id or "", f"{role}_{len(elements)}"),
                    role=role,
                    name=name or test_id or "",
                    tag=tag,
                    input_type=input_type,
                    required=_has_attr(handle, "required"),
                    href=handle.get_attribute("href") if tag == "a" else None,
                    test_id=test_id,
                    disabled=_is_disabled(handle),
                    checked=_is_checked(handle),
                ))
            except Exception:                       # noqa: BLE001 — DOM đổi khi đang đọc
                continue

    text: list[str] = []
    try:
        for handle in page.locator("h1, h2, h3, label, p").all()[:40]:
            chunk = (handle.inner_text() or "").strip()
            if 2 < len(chunk) < 160:
                text.append(chunk)
    except Exception:                               # noqa: BLE001
        pass

    return PageMap(url=page.url, title=page.title(), text=text, elements=elements)


def _wait_for_render(page, max_wait_ms: int = 12000) -> bool:
    """Chờ tới khi trang thật sự có element tương tác. Trả False nếu hết thời gian.

    Với SPA, thứ tự là: HTML về → JS chạy → gọi API lấy phiên (`/auth/me`) →
    mới render menu. Chờ mỗi DOM là không đủ. Nên chờ **mạng lắng xuống** trước,
    rồi mới dò element. Không có bước chờ mạng thì lúc được lúc không, tuỳ tốc độ
    mạng lúc đó — đúng kiểu flake khó tìm.
    """
    with contextlib.suppress(Exception):
        page.wait_for_load_state("networkidle", timeout=min(max_wait_ms, 7000))

    waited = 0
    step = 400
    while waited < max_wait_ms:
        try:
            for tag in INTERACTIVE:
                if page.locator(tag).count() > 0:
                    return True
        except Exception:                               # noqa: BLE001
            pass
        page.wait_for_timeout(step)
        waited += step
    return False


def _element_name(handle) -> str:
    """Tên hiển thị của element — thứ người dùng đọc thấy và tài liệu hay nhắc tới."""
    for getter in (
        lambda: handle.inner_text(),
        lambda: handle.get_attribute("aria-label"),
        lambda: handle.get_attribute("placeholder"),
        lambda: handle.get_attribute("name"),
        lambda: handle.get_attribute("value"),
        lambda: handle.get_attribute("title"),
    ):
        try:
            value = (getter() or "").strip()
            if value:
                return re.sub(r"\s+", " ", value)[:80]
        except Exception:                               # noqa: BLE001
            continue
    return ""


TEST_ID_ATTRS = ("data-testid", "data-test-id", "data-test", "data-cy", "data-qa")


def _test_id(handle) -> str | None:
    """Test id do dev đặt — dùng nó để trỏ tới element là bền nhất."""
    for attr in TEST_ID_ATTRS:
        try:
            value = (handle.get_attribute(attr) or "").strip()
            if value:
                return value[:80]
        except Exception:                               # noqa: BLE001
            continue
    return None


def _has_attr(handle, name: str) -> bool:
    try:
        return handle.get_attribute(name) is not None
    except Exception:                                   # noqa: BLE001
        return False


def _is_disabled(handle) -> bool:
    try:
        if handle.get_attribute("disabled") is not None:
            return True
        return (handle.get_attribute("aria-disabled") or "").lower() == "true"
    except Exception:                                   # noqa: BLE001
        return False


def _is_checked(handle) -> bool:
    try:
        return handle.is_checked()
    except Exception:                                   # noqa: BLE001
        return False
