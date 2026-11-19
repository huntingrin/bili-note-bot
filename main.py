#!/usr/bin/env python3
"""bilibili_note — poll @-mentions, summarise the video, send back one image card.

Delivery defaults to `ego` (drive the locally logged-in Bilibili session, no
cookies needed). Default behaviour is DRY RUN: nothing is sent without --send.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent


def _bootstrap() -> None:
    """Re-exec into the project venv when the interpreter lacks the deps.

    Keeps `python3 main.py --selftest` working with the system python while the
    real dependencies live in ./.venv.
    """
    required = ("requests", "jinja2", "PIL", "playwright", "yt_dlp")

    def _have(name: str) -> bool:
        try:
            return importlib.util.find_spec(name) is not None
        except (ImportError, ModuleNotFoundError):
            return False

    if all(_have(m) for m in required):
        return
    venv_py = PROJECT_ROOT / ".venv" / "bin" / "python"
    if venv_py.is_file():
        try:
            if Path(sys.executable).resolve() != venv_py.resolve():
                os.execv(str(venv_py), [str(venv_py), *sys.argv])
        except OSError:
            pass
    sys.stderr.write(
        "缺少依赖：请先创建虚拟环境并安装依赖\n"
        "  python3 -m venv .venv && .venv/bin/pip install -r requirements.txt\n"
    )
    raise SystemExit(2)


_bootstrap()

sys.path.insert(0, str(PROJECT_ROOT))

import logging  # noqa: E402

import requests  # noqa: E402

from bili import ego  # noqa: E402
from bili.at import AtItem, extract_bv
from bili.at import fetch_at as api_fetch_at  # noqa: E402
from bili.auth import Auth  # noqa: E402
from bili.send import CODE_NEEDS_MANUAL, get_dev_id, send_image, send_text  # noqa: E402
from bili.upload import upload_image  # noqa: E402
from bili.wbi import WbiSigner  # noqa: E402
from config import Settings, load_settings  # noqa: E402
from pipeline import download as dl  # noqa: E402
from pipeline import render as rd  # noqa: E402
from pipeline import summarize as sm  # noqa: E402
from storage import STATUS_CARDED, STATUS_DRYRUN, STATUS_FAILED, STATUS_SENT, Store  # noqa: E402
from util import (  # noqa: E402
    AuthError,
    BiliNoteError,
    ConfigError,
    mmss,
    retry_call,
    setup_logging,
)

EXIT_OK, EXIT_ERROR, EXIT_USAGE, EXIT_CONFIG = 0, 1, 2, 3

log = logging.getLogger("bili_note")


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _normalize_bv(value: str) -> str:
    bv = extract_bv(value)
    if not bv:
        raise ConfigError(f"无法从参数中识别 BV 号：{value}", hint="示例：--bv BV1xx411c7mD")
    return bv


def _session(settings: Settings) -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": settings.user_agent})
    return session


def _auth(settings: Settings) -> Auth:
    return Auth.from_settings(settings)


def _print_config_problems(problems: list[tuple[str, str]], command: str) -> int:
    print(f"\n无法执行 `{command}`，配置不完整：\n", file=sys.stderr)
    for item, hint in problems:
        print(f"  ✗ {item}", file=sys.stderr)
        if hint:
            print(f"    → {hint}", file=sys.stderr)
    print(
        "\n请复制 .env.example 为 .env 并按提示填写后重试。"
        "\n提示：`python3 main.py --selftest` 不需要任何凭据，"
        "`--browser-check` 只需要本机 ego lite 已登录 B 站。\n",
        file=sys.stderr,
    )
    return EXIT_CONFIG


def _card_for(settings: Settings, store: Store, bv: str, mid: int | None = None,
              uname: str = "") -> Path:
    """Download → sample 12 frames → summarise → render. One model run per BV."""
    existing = store.get_video(bv)
    if existing and existing["card_path"] and Path(existing["card_path"]).is_file():
        log.info("BV %s 已有卡片，跳过下载与模型调用：%s", bv, existing["card_path"])
        return Path(existing["card_path"])

    attempts = settings.max_retries + 1
    work_dir = settings.work_dir / bv
    work_dir.mkdir(parents=True, exist_ok=True)

    store.upsert_video(bv, mid=mid, uname=uname or None, status="downloading")

    meta = retry_call(
        lambda: dl.download(bv, work_dir, settings.max_duration_min,
                            cookie=_auth(settings).cookie_header if not settings.use_ego else "",
                            user_agent=settings.user_agent, logger=log),
        attempts=attempts, logger=log, label=f"下载 {bv}",
    )
    store.upsert_video(bv, title=meta.title, up_name=meta.up_name, duration=meta.duration,
                       status="frames")

    frame_total = dl.frame_count_for(meta.duration, settings.frame_count)
    chapter_total = dl.chapter_count_for(meta.duration)
    log.info("duration=%ds → frames=%d chapters=%d", meta.duration, frame_total, chapter_total)
    sampled = dl.frame_timestamps(meta.duration, frame_total)
    frame_paths = retry_call(
        lambda: dl.extract_frames(meta.path, sampled, work_dir / "frames",
                                  max_height=settings.max_height),
        attempts=attempts, logger=log, label=f"抽帧 {bv}",
    )
    frames = [
        {"path": path, "ts": int(ts), "label": mmss(ts)}
        for path, ts in zip(frame_paths, sampled)
    ]
    log.info("已抽取 %d 帧（480p，均匀分布）", len(frames))

    summary = retry_call(
        lambda: sm.summarize(settings, frames, meta.duration, meta.title, meta.up_name,
                             logger=log),
        attempts=attempts, logger=log, label=f"总结 {bv}",
    )
    (work_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    card = retry_call(
        lambda: rd.render_card(summary, frames, settings.out_dir / f"{bv}.png", logger=log),
        attempts=attempts, logger=log, label=f"渲染 {bv}",
    )
    log.info("frames=%d chapters=%d", len(frames), len(summary["chapters"]))
    store.upsert_video(bv, card_path=str(card), status=STATUS_CARDED,
                       title=summary["title"], up_name=summary["up_name"],
                       duration=summary["duration"])
    return card


def _message_text(bv: str, uname: str, title: str, duration: int) -> str:
    head = f"@{uname} " if uname else ""
    return (
        f"{head}你 @ 我的视频我看完了，总结在这张图里 👇\n"
        f"《{title}》 {mmss(duration)}\n"
        f"https://www.bilibili.com/video/{bv}"
    )


def _quota_exceeded(settings: Settings, store: Store) -> bool:
    used = store.sent_today()
    if settings.daily_limit and used >= settings.daily_limit:
        log.warning("今日已达发送上限 %d/%d，只记录不发送。", used, settings.daily_limit)
        return True
    return False


def _deliver(settings: Settings, store: Store, bv: str, mid: int, uname: str,
             card: Path, send: bool, expect_uname: str | None = None,
             allow_resend: bool = False) -> int:
    """Send (or print) the card: ego browser by default, cookie API as fallback."""
    row = store.get_video(bv)
    if row and row["status"] == STATUS_SENT and not allow_resend:
        log.warning("BV %s 已发送过（status=sent），跳过，避免重复发图。", bv)
        print(f"BV {bv} 已发送过，本次跳过（要强制重发请加 --force）。")
        return EXIT_OK
    title = row["title"] if row else bv
    duration = int(row["duration"] or 0) if row else 0
    text = _message_text(bv, uname, title, duration)
    had_contact = store.has_contact(mid)
    mode = "ego" if settings.use_ego else "api"

    if not send:
        print("\n[dry-run] 将要发送私信（未真实发送）：")
        print(f"  通道：{mode}（DELIVERY 控制；ego = 本机已登录浏览器）")
        print(f"  收件人：@{uname} (mid={mid})" if mid else "  收件人：未知（缺少 mid）")
        print("  ---- 图片（主消息）----")
        print(f"  {card}")
        if settings.use_ego:
            print("  ego 模式下选图即发送：B 站对未关注/未回复的人只放行 1 条。")
            print("  以下文字仅作参考（ego 只发图片）：")
            for line in text.splitlines():
                print(f"  > {line}")
        elif had_contact:
            print("  ---- 补充文字（已有会话时追加）----")
            for line in text.splitlines():
                print(f"  {line}")
        else:
            print("  首次私信只发图片：B 站限制未关注/未回复时最多 1 条（21047）。")
            print("  以下文字将在对方回复后随下一次推送发出：")
            for line in text.splitlines():
                print(f"  > {line}")
        print("  加 --send 才会真正发送。\n")
        store.set_status(bv, STATUS_DRYRUN)
        return EXIT_OK

    if not mid:
        raise ConfigError(f"BV {bv} 缺少接收人 mid，无法发送")
    if _quota_exceeded(settings, store):
        store.set_status(bv, STATUS_CARDED, error="daily_limit_reached")
        return EXIT_OK

    if settings.use_ego:
        if expect_uname:
            peer = ego.peer_uname(mid, settings=settings)
            print(f"收件人预检：mid={mid}，会话页 uname=「{peer}」，期望「{expect_uname}」")
            if peer != expect_uname:
                print("✗ 昵称不一致，已中止发送（未选择图片）。", file=sys.stderr)
                store.add_failure(bv, mid, "ego_peer_mismatch",
                                  f"peer={peer!r} expected={expect_uname!r}")
                store.set_status(bv, STATUS_FAILED, error="peer_uname_mismatch")
                return EXIT_ERROR
            print("  ✓ 昵称一致，继续发送")
        try:
            info = ego.send_dm(mid, card, settings=settings, expect_uname=expect_uname)
            print(f"已发送；会话页确认收件人：mid={mid} uname={info.get('header')}")
        except BiliNoteError as exc:
            store.add_failure(bv, mid, "ego_send", exc.message)
            store.upsert_video(bv, error=exc.message[:300])
            store.set_status(bv, STATUS_FAILED)
            log.error("ego 发送失败：%s", exc.message)
            if exc.hint:
                log.error("  → %s", exc.hint)
            print(
                "\n⚠️  需人工处理：私信未确认送达。"
                "\n   若浏览器提示「对方主动回复或关注你前，最多发送 1 条消息」，"
                f"请在评论区回复他：https://www.bilibili.com/video/{bv}\n",
                file=sys.stderr,
            )
            return EXIT_ERROR
        total = store.incr_sent_today()
        store.touch_contact(mid)
        store.set_status(bv, STATUS_SENT)
        log.info("已通过 ego 发送给 @%s (mid=%s)，今日第 %d 条", uname, mid, total)
        return EXIT_OK

    # ----- legacy cookie + wbi API path -----
    auth = _auth(settings)
    auth.require_sender()
    signer = WbiSigner(_session(settings))
    dev_id = get_dev_id(settings.data_dir / "dev_id")

    image = retry_call(lambda: upload_image(auth, card), attempts=settings.max_retries + 1,
                       logger=log, label="上传图床")

    # Image first: strangers only get one message, so it must be the deliverable.
    result = send_image(auth, signer, mid, image, dev_id)

    if result.ok:
        total = store.incr_sent_today()
        store.touch_contact(mid)
        store.set_status(bv, STATUS_SENT)
        log.info("已发送给 @%s (mid=%s)，今日第 %d 条", uname, mid, total)
        if had_contact:
            follow = send_text(auth, signer, mid, text, dev_id)
            if not follow.ok:
                log.warning("补充文字未发出（code=%s，图片已送达，可忽略）", follow.code)
        return EXIT_OK

    store.add_failure(bv, mid, "send_msg", f"{result.code}: {result.message}", result.code)
    store.upsert_video(bv, error=f"send_code={result.code}")
    store.set_status(bv, STATUS_FAILED)
    log.error("发送失败：code=%s message=%s", result.code, result.message)
    if result.needs_manual or result.code in (CODE_NEEDS_MANUAL, 25003):
        print(
            "\n⚠️  需人工在评论区回复："
            f"{result.hint or '对方未关注/未回复，B 站限制私信。'}\n"
            f"   视频：https://www.bilibili.com/video/{bv}\n",
            file=sys.stderr,
        )
    return EXIT_ERROR


def _items_via_ego(settings: Settings, limit: int = 20) -> list[AtItem]:
    rows = ego.fetch_at(settings=settings, limit=limit)
    if settings.bot_uname:
        try:
            replies = ego.fetch_reply(settings=settings, bot_uname=settings.bot_uname,
                                      limit=limit)
        except BiliNoteError as exc:
            log.warning("读取「回复我的」失败，继续只用 @ 通道：%s", exc.message)
            replies = []
    else:
        log.warning("BOT_UNAME 未配置：跳过「回复我的」通道（自己视频下的 @ 会漏掉）。")
        replies = []

    items: list[AtItem] = []
    for row in rows:
        bv = extract_bv(row.get("bv"), row.get("title"))
        items.append(
            AtItem(
                item_id=f"ego-at-{row.get('mid')}-{bv or 'nobv'}-{row.get('time') or ''}",
                bv=bv,
                mid=int(row.get("mid") or 0),
                uname=str(row.get("uname") or ""),
                title=str(row.get("title") or ""),
                at_time=0,
                raw_uri=str(row.get("time") or ""),
            )
        )
    for row in replies:
        bv = extract_bv(row.get("bvid"), row.get("uri"), row.get("title"))
        items.append(
            AtItem(
                item_id=f"ego-reply-{row.get('mid')}-{bv or row.get('aid') or 'nobv'}",
                bv=bv,
                mid=int(row.get("mid") or 0),
                uname=str(row.get("uname") or ""),
                title=str(row.get("title") or "") or str(row.get("comment") or ""),
                at_time=int(row.get("time") or 0),
                raw_uri=str(row.get("comment") or ""),
            )
        )

    # One request per (BV, sender): the same @ can show up in both feeds.
    deduped: list[AtItem] = []
    seen: set[tuple[str, int]] = set()
    for item in items:
        key = (item.bv or f"nobv-{item.item_id}", item.mid)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _fetch_items(settings: Settings) -> list[AtItem]:
    if settings.use_ego:
        return _items_via_ego(settings)
    auth = _auth(settings)
    auth.require_cookie()
    return api_fetch_at(auth, _session(settings))


# --------------------------------------------------------------------------- #
# commands
# --------------------------------------------------------------------------- #
def _fixture_frames(out_dir: Path, timestamps: list[int]) -> list[dict]:
    """Synthesise 12 video-still placeholders so selftest needs no sample video."""
    from PIL import Image, ImageDraw, ImageFont

    out_dir.mkdir(parents=True, exist_ok=True)
    palettes = [
        ((22, 26, 34), (58, 72, 94)),
        ((32, 20, 28), (108, 54, 82)),
        ((18, 30, 36), (44, 96, 104)),
        ((34, 26, 18), (120, 88, 44)),
        ((20, 24, 40), (62, 74, 130)),
        ((28, 28, 30), (96, 92, 88)),
    ]
    result: list[dict] = []
    for i, ts in enumerate(timestamps):
        width, height = 854, 480  # 480p, same as the real pipeline
        img = Image.new("RGB", (width, height), palettes[i % len(palettes)][0])
        draw = ImageDraw.Draw(img)
        top, bottom = palettes[i % len(palettes)]
        for y in range(height):
            ratio = y / height
            draw.line(
                [(0, y), (width, y)],
                fill=tuple(int(top[c] + (bottom[c] - top[c]) * ratio) for c in range(3)),
            )
        draw.ellipse([width * 0.62, height * 0.18, width * 0.62 + 170, height * 0.18 + 170],
                     fill=tuple(min(255, c + 26) for c in bottom))
        try:
            font = ImageFont.truetype("/System/Library/Fonts/PingFang.ttc", 34)
        except OSError:
            font = ImageFont.load_default()
        draw.text((24, 20), f"fixture frame #{i + 1}", fill=(235, 238, 244), font=font)

        path = out_dir / f"frame_{i:02d}.png"
        img.save(path, "PNG")
        result.append({"path": path, "ts": int(ts), "label": mmss(ts)})
    return result


def cmd_selftest(settings: Settings) -> int:
    """Render a card from the bundled fixture — no network, no credentials."""
    fixture_path = settings.root / "fixtures" / "sample.json"
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    video = fixture["video"]
    duration = int(video["duration"])

    frame_total = dl.frame_count_for(duration, settings.frame_count)
    sampled = [int(t) for t in dl.frame_timestamps(duration, frame_total)]
    log.info("duration=%ds → frames=%d chapters=%d", duration, frame_total,
             dl.chapter_count_for(duration))
    summary = sm.normalize(fixture["summary"], duration, sampled_ts=sampled,
                           chapters_target=dl.chapter_count_for(duration),
                           fallback_title=video["title"], fallback_up=video["up_name"])
    frames = _fixture_frames(settings.work_dir / "selftest", sampled)

    card = rd.render_card(summary, frames, settings.card_path, logger=log)

    from PIL import Image

    with Image.open(card) as img:
        size = img.size
    print(f"[selftest] fixture: {fixture_path}")
    print(f"[selftest] 卡片已生成: {card}")
    print(f"[selftest] 尺寸: {size[0]}×{size[1]} (期望 1080×1440，{len(frames)} 帧)")
    if size != (rd.CARD_WIDTH, rd.CARD_HEIGHT):
        print("[selftest] 失败：尺寸不符", file=sys.stderr)
        return EXIT_ERROR
    print("[selftest] OK — 渲染链路可用（未联网、未发送）")
    return EXIT_OK


def cmd_browser_check(settings: Settings) -> int:
    """Read-only probe of the logged-in browser. Never sends anything."""
    out_dir = settings.data_dir / "screenshots"
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"打开 {ego.AT_URL} …")
    result = ego.browser_check(settings=settings)

    uid = result.get("uid") or 0
    if result.get("loggedIn"):
        print(f"登录状态: 已登录 (uid={uid or '未知'})")
    else:
        print("登录状态: 未登录 — 请先在 ego lite 浏览器里登录 bilibili.com", file=sys.stderr)

    count = int(result.get("atCount") or 0)
    print(f"@ 通知: {count} 条")
    first = result.get("first")
    if first:
        print(
            "  第一条: @{uname} (mid={mid}) bv={bv} time={time} title={title}".format(
                uname=first.get("uname") or "?",
                mid=first.get("mid") or "?",
                bv=first.get("bv") or "(无)",
                time=first.get("time") or "(无)",
                title=(first.get("title") or "")[:40],
            )
        )
    else:
        print("  第一条: 无（当前没有 @ 通知）")
    print(f"页面: {result.get('href')}")

    if not result.get("loggedIn"):
        return EXIT_CONFIG
    print("\n只读探针完成：未点击发送、未修改任何数据。")
    return EXIT_OK


def cmd_at(settings: Settings) -> int:
    """Only poll the @ feed and print what we see."""
    if not settings.use_ego and not _auth(settings).sessdata:
        return _print_config_problems(
            [("DELIVERY=api 但缺少 SESSDATA",
              "改用 DELIVERY=ego（默认）或填写 SESSDATA")],
            "--at",
        )
    items = _fetch_items(settings)
    if not settings.allow_mids:
        log.warning("ALLOW_MIDS 为空：不限制发送对象（任何人 @ 都会处理），建议尽快填白名单。")
    if not items:
        print("没有新的 @ 通知。")
        return EXIT_OK
    print(f"共 {len(items)} 条 @ 通知（通道：{'ego' if settings.use_ego else 'api'}）：")
    for it in items:
        whitelisted = not settings.allow_mids or it.mid in settings.allow_mids
        print(
            f"  [{ '✓' if whitelisted else ' ' }] mid={it.mid} @{it.uname} "
            f"bv={it.bv or '(无 BV，跳过)'} title={it.title[:40]}"
        )
    if settings.allow_mids:
        print(f"\n白名单 ALLOW_MIDS={settings.allow_mids}（未打勾的将被忽略）")
    return EXIT_OK


def cmd_bv(settings: Settings, bv_arg: str, send: bool, to_mid: int | None = None,
           expect_uname: str | None = None, allow_resend: bool = False) -> int:
    """Only run the generation pipeline for one BV (no notification polling)."""
    bv = _normalize_bv(bv_arg)
    store = Store(settings.db_path)

    problems: list[tuple[str, str]] = []
    if not settings.llm_api_key:
        problems.append(("缺少 LLM_API_KEY（无法做多模态总结）",
                         f"在 .env 中填写 LLM_API_KEY（当前 LLM_BASE_URL={settings.llm_base_url}）"))
    if not dl.have_ffmpeg():
        problems.append(("未找到 ffmpeg（无法抽帧/合并）", "macOS: brew install ffmpeg"))
    if not settings.use_ego:
        missing = [n for n, v in (("SESSDATA", settings.sessdata),
                                  ("BILI_JCT", settings.bili_jct),
                                  ("DEDEUSERID", settings.dedeuserid)) if not v]
        if missing and send:
            problems.append((f"DELIVERY=api 但缺少 {'/'.join(missing)}",
                             "发送需要完整 cookie 与 csrf；或改用默认的 DELIVERY=ego"))
    # Preflight runs before any cache lookup: a cached card must never hide a
    # missing key / ffmpeg / cookie problem.
    if problems:
        return _print_config_problems(problems, f"--bv {bv}")

    card = _card_for(settings, store, bv)
    row = store.get_video(bv)
    mid = int(to_mid or (row["mid"] if row and row["mid"] else 0))
    uname = expect_uname or (row["uname"] if row and row["uname"] else "") or ""
    return _deliver(settings, store, bv, mid, uname, card, send,
                    expect_uname=expect_uname, allow_resend=allow_resend)


def run_cycle(settings: Settings, send: bool) -> int:
    """Poll @ feed once and process every allowed, unseen BV."""
    if not settings.use_ego and not _auth(settings).sessdata:
        return _print_config_problems(
            [("DELIVERY=api 但缺少 SESSDATA",
              "改用默认的 DELIVERY=ego（需要 ego lite 已登录 B 站）或填写 SESSDATA")],
            "轮询",
        )

    store = Store(settings.db_path)
    if not settings.allow_mids:
        log.warning("ALLOW_MIDS 为空：不限制发送对象（任何人 @ 都会处理），建议尽快填白名单。")
    items = _fetch_items(settings)
    log.info("收到 %d 条 @ 通知（通道：%s）", len(items), "ego" if settings.use_ego else "api")
    if not items:
        return EXIT_OK

    processed = 0
    for item in items:
        if not item.bv:
            log.info("通知 %s 不含 BV 号，跳过（可能是专栏/动态）", item.item_id)
            store.mark_at_item(item.item_id, None, item.mid)
            continue
        if store.seen_at_item(item.item_id):
            log.debug("通知 %s 已处理过", item.item_id)
            continue
        if settings.allow_mids and item.mid not in settings.allow_mids:
            log.warning("忽略 mid=%s @%s（不在 ALLOW_MIDS 白名单内）", item.mid, item.uname)
            store.mark_at_item(item.item_id, item.bv, item.mid)
            continue
        if send and _quota_exceeded(settings, store):
            store.mark_at_item(item.item_id, item.bv, item.mid)
            continue

        try:
            card = _card_for(settings, store, item.bv, mid=item.mid, uname=item.uname)
            _deliver(settings, store, item.bv, item.mid, item.uname, card, send)
            store.mark_at_item(item.item_id, item.bv, item.mid)
            processed += 1
        except BiliNoteError as exc:
            store.add_failure(item.bv, item.mid, "pipeline", exc.message)
            store.set_status(item.bv, STATUS_FAILED, error=exc.message[:500])
            store.mark_at_item(item.item_id, item.bv, item.mid)
            log.error("处理 %s 失败：%s", item.bv, exc.message)
            if exc.hint:
                log.error("  → %s", exc.hint)
        except Exception as exc:  # noqa: BLE001 - keep the loop alive
            store.add_failure(item.bv, item.mid, "pipeline", repr(exc))
            log.exception("处理 %s 时出现未预期错误", item.bv)

    log.info("本轮处理 %d 个视频", processed)
    return EXIT_OK


def cmd_loop(settings: Settings, send: bool, interval: int) -> int:
    log.info("开始轮询，间隔 %d 秒（通道 %s，dry-run=%s）",
             interval, "ego" if settings.use_ego else "api", not send)
    while True:
        try:
            run_cycle(settings, send)
        except KeyboardInterrupt:
            log.info("收到中断，退出轮询")
            return EXIT_OK
        except BiliNoteError as exc:
            log.error("轮询失败：%s", exc.message)
            if exc.hint:
                log.error("  → %s", exc.hint)
        except Exception as exc:  # noqa: BLE001
            log.exception("轮询出现未预期错误：%s", exc)
        try:
            time.sleep(interval)
        except KeyboardInterrupt:
            log.info("收到中断，退出轮询")
            return EXIT_OK


# --------------------------------------------------------------------------- #
# entry
# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bilibili-note",
        description="轮询 B 站 @ 通知 → 下载 480p → 多模态总结 → 发回 1080×1440 图文卡片",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  python3 main.py --browser-check     # 只读探针：登录态 + @ 条数（不发送）\n"
            "  python3 main.py --selftest          # 用内置 fixture 出图，不需要凭据\n"
            "  python3 main.py --at                # 只拉 @ 通知\n"
            "  python3 main.py --bv BV1xx          # 只跑单个视频的生成流程\n"
            "  python3 main.py --bv BV1xx --send   # 生成并通过 ego 发送\n"
            "  python3 main.py --send              # 轮询一次并发送\n"
            "  python3 main.py --loop --send       # 常驻轮询\n"
        ),
    )
    parser.add_argument("--browser-check", action="store_true",
                        help="只读探针：打开消息页打印登录态与 @ 条数（绝不发送）")
    parser.add_argument("--selftest", action="store_true", help="用内置 fixture 渲染卡片（离线）")
    parser.add_argument("--at", action="store_true", help="只拉取 @ 通知并打印")
    parser.add_argument("--bv", metavar="BV1xx", help="只处理指定视频（生成卡片）")
    parser.add_argument("--send", action="store_true",
                        help="真实发送私信（默认 dry-run，只打印）")
    parser.add_argument("--dry-run", action="store_true",
                        help="只打印将要发送的内容（默认行为，显式写明便于确认）")
    parser.add_argument("--loop", action="store_true", help="常驻轮询")
    parser.add_argument("--interval", type=int, default=None, help="轮询间隔秒数")
    parser.add_argument("--to", type=int, metavar="MID",
                        help="指定收件人 mid（与 --bv 搭配，默认取通知里的发送者）")
    parser.add_argument("--expect-uname", metavar="NAME",
                        help="发送前校验会话页昵称，不一致则中止（不发图）")
    parser.add_argument("--force", action="store_true", help="忽略 SQLite 缓存重新生成")
    parser.add_argument("--verbose", action="store_true", help="输出调试日志与堆栈")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    send = bool(args.send and not args.dry_run)
    settings = load_settings()
    settings.ensure_dirs()
    setup_logging(settings.logs_dir, verbose=args.verbose)

    try:
        if args.browser_check:
            return cmd_browser_check(settings)
        if args.selftest:
            return cmd_selftest(settings)
        if args.at:
            return cmd_at(settings)
        if args.bv:
            bv = _normalize_bv(args.bv)
            if args.force:
                Store(settings.db_path).upsert_video(bv, card_path="", status="new")
                settings.out_dir.mkdir(parents=True, exist_ok=True)
            return cmd_bv(settings, args.bv, send=send, to_mid=args.to,
                          expect_uname=args.expect_uname, allow_resend=args.force)
        if args.loop:
            return cmd_loop(settings, send, args.interval or settings.poll_interval)
        return run_cycle(settings, send)
    except AuthError as exc:
        print(f"\n✗ {exc.message}", file=sys.stderr)
        if exc.hint:
            print(f"  → {exc.hint}", file=sys.stderr)
        print(file=sys.stderr)
        return EXIT_CONFIG
    except ConfigError as exc:
        print(f"\n✗ {exc.message}", file=sys.stderr)
        if exc.hint:
            print(f"  → {exc.hint}", file=sys.stderr)
        print(file=sys.stderr)
        return EXIT_CONFIG
    except BiliNoteError as exc:
        print(f"\n✗ {exc.message}", file=sys.stderr)
        if exc.hint:
            print(f"  → {exc.hint}", file=sys.stderr)
        print(file=sys.stderr)
        if args.verbose:
            raise
        return EXIT_ERROR
    except KeyboardInterrupt:
        print("\n已中断。", file=sys.stderr)
        return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
