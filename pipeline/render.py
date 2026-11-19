"""Render the summary card: Jinja2 HTML → Playwright screenshot at 1080×1440."""

from __future__ import annotations

import base64
import glob
import os
from pathlib import Path
from typing import Any

from util import BiliNoteError, mmss

CARD_WIDTH, CARD_HEIGHT = 1080, 1440
TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"


def _data_uri(path: Path) -> str:
    payload = base64.b64encode(Path(path).read_bytes()).decode("ascii")
    return f"data:image/png;base64,{payload}"


def _is_dense(summary: dict[str, Any]) -> bool:
    chapters = summary.get("chapters") or []
    points = sum(len(ch.get("points") or []) for ch in chapters)
    return points >= 13


# 4..12 frames: (columns, row height px). Cells stay at/below the 480p source
# size, so nothing is upscaled; fewer frames simply get bigger cells.
GRID_PLANS: dict[int, tuple[int, int]] = {
    4: (2, 330),
    5: (3, 250),
    6: (2, 290),
    7: (3, 210),
    8: (3, 210),
    9: (3, 200),
    10: (3, 185),
    11: (3, 176),
    12: (3, 166),
}


def grid_plan(frame_count: int, dense: bool = False) -> tuple[int, int]:
    cols, row_h = GRID_PLANS.get(int(frame_count), (3, 166))
    if dense:
        row_h = max(140, row_h - 20)
    return cols, row_h


def build_html(summary: dict[str, Any], frames: list[dict[str, Any]]) -> str:
    from jinja2 import Environment, FileSystemLoader, select_autoescape

    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=select_autoescape(["html"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = env.get_template("card.html")

    chapters = []
    for ch in summary.get("chapters") or []:
        chapters.append(
            {
                "heading": ch.get("heading", ""),
                "points": list(ch.get("points") or []),
                "timestamp_label": mmss(ch.get("timestamp", 0)),
            }
        )

    view_frames = []
    for fr in frames:
        view_frames.append(
            {
                "data_uri": _data_uri(fr["path"]),
                "label": mmss(fr["ts"]),
            }
        )

    dense = _is_dense(summary)
    cols, row_h = grid_plan(len(frames), dense)
    total_points = sum(len(c["points"]) for c in chapters)

    return template.render(
        summary={
            "title": summary.get("title", ""),
            "up_name": summary.get("up_name", ""),
            "chapters": chapters,
        },
        frames=view_frames,
        duration_label=mmss(summary.get("duration", 0)),
        dense=dense,
        grid_cols=cols,
        grid_row_h=row_h,
        sparse=(not dense and len(chapters) <= 3 and total_points <= 6),
    )


def _find_local_chromium() -> str | None:
    """Fallback when `playwright install` state is unknown but a build is cached."""
    patterns = [
        "~/Library/Caches/ms-playwright/chromium-*/chrome-mac*/Chromium.app/Contents/MacOS/Chromium",
        "~/Library/Caches/ms-playwright/chromium_headless_shell-*/chrome-mac*/headless_shell",
        "~/.cache/ms-playwright/chromium-*/chrome-linux/chrome",
        "~/.cache/ms-playwright/chromium_headless_shell-*/chrome-linux/headless_shell",
        "~/AppData/Local/ms-playwright/chromium-*/chrome-win/chrome.exe",
    ]
    found: list[str] = []
    for pattern in patterns:
        found.extend(glob.glob(os.path.expanduser(pattern)))
    if not found:
        return None
    return sorted(found)[-1]


def _launch(p):
    try:
        return p.chromium.launch(args=["--force-color-profile=srgb"])
    except Exception as first:  # noqa: BLE001 - retry with a cached build
        exe = _find_local_chromium()
        if not exe:
            raise BiliNoteError(
                "Playwright 浏览器未安装，无法渲染卡片。",
                hint="在项目目录运行 .venv/bin/playwright install chromium",
            ) from first
        return p.chromium.launch(executable_path=exe, args=["--force-color-profile=srgb"])


def render_card(summary: dict[str, Any], frames: list[dict[str, Any]],
                out_path: Path, logger=None) -> Path:
    """frames: [{"path": Path, "ts": int}, ...]  → writes 1080×1440 PNG."""
    if not 4 <= len(frames) <= 12:
        raise BiliNoteError(f"渲染需要 4~12 张关键帧，实际 {len(frames)} 张。")

    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:  # pragma: no cover
        raise BiliNoteError("缺少 playwright 依赖，请先 pip install -r requirements.txt") from exc

    html = build_html(summary, frames)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = _launch(p)
        try:
            page = browser.new_page(
                viewport={"width": CARD_WIDTH, "height": CARD_HEIGHT},
                device_scale_factor=1,
            )
            page.set_content(html, wait_until="load")
            page.wait_for_function("document.fonts.status === 'loaded'", timeout=10_000)
            page.wait_for_timeout(120)
            page.screenshot(path=str(out_path), full_page=False, type="png")
        finally:
            browser.close()

    size = _verify_png(out_path)
    if logger:
        logger.info("卡片已生成：%s (%d×%d)", out_path, size[0], size[1])
    return out_path


def _verify_png(path: Path) -> tuple[int, int]:
    try:
        from PIL import Image
    except ImportError as exc:  # pragma: no cover
        raise BiliNoteError("缺少 pillow 依赖，无法校验图片尺寸") from exc

    with Image.open(path) as img:
        size = img.size
        if size != (CARD_WIDTH, CARD_HEIGHT):
            raise BiliNoteError(
                f"卡片尺寸异常：{size[0]}×{size[1]}，期望 {CARD_WIDTH}×{CARD_HEIGHT}"
            )
    return size
