"""Drive the locally logged-in Bilibili session through `ego-browser`.

No cookies, no wbi signing: the browser already holds the login. Every call
ships a small Node ESM script over stdin and reads one JSON line from stdout.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from util import BiliNoteError

AT_URL = "https://message.bilibili.com/#/at"
REPLY_URL = "https://message.bilibili.com/#/reply"
REPLY_API = "https://api.bilibili.com/x/msgfeed/reply?platform=web&build=0&mobi_app=web"
DM_URL = "https://message.bilibili.com/#/whisper/mid{mid}"
DEFAULT_TIMEOUT = 180

_prelude = """
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const emit = (obj) => console.log(JSON.stringify(obj));
"""

# Runs inside the page: scrape the @ feed cards into plain rows.
_EXTRACT_AT = r"""
(arg) => {
  const limit = (arg && arg.limit) || 20;
  const bvRe = /(BV[0-9A-Za-z]{10})/;
  const userRe = /space\.bilibili\.com\/(\d+)/;
  const clean = (s) => (s || "").replace(/\s+/g, " ").trim();

  const root = document.querySelector('[class*="message-content"]') || document.body;
  const ownMid = (() => {
    const a = Array.from(document.querySelectorAll('a[href*="space.bilibili.com/"]'))
      .map((el) => (el.getAttribute('href') || '').match(userRe))
      .find(Boolean);
    return a ? parseInt(a[1], 10) : 0;
  })();

  let cards = Array.from(root.querySelectorAll('.interaction-item'));
  let fallback = false;
  if (!cards.length) {
    // Only trust containers that hold both a BV link and a user link.
    fallback = true;
    cards = Array.from(root.querySelectorAll('li, [class*="item"], [class*="card"]'))
      .filter((n) => bvRe.test(n.innerHTML || '') && n.querySelector('a[href*="space.bilibili.com/"]'));
  }

  const rows = [];
  const seen = new Set();
  for (const card of cards) {
    const text = clean(card.innerText);
    const html = card.innerHTML || '';
    if (!text && !html) continue;

    const userLinks = Array.from(card.querySelectorAll('a[href]'))
      .map((a) => ({ el: a, m: (a.getAttribute('href') || '').match(userRe) }))
      .filter((x) => x.m);
    const pick = userLinks.find((x) => parseInt(x.m[1], 10) !== ownMid) || userLinks[0];
    if (!pick) continue;

    const mid = parseInt(pick.m[1], 10);
    if (fallback && mid === ownMid) continue;      // nav / self links are not @ cards
    const bv = (html.match(bvRe) || text.match(bvRe) || [null])[0];
    if (fallback && !bv) continue;

    const unameEl = card.querySelector('[class*="uname"], [class*="user-name"], [class*="nickname"]');
    const uname = clean((unameEl && unameEl.innerText) || (pick.el && pick.el.innerText)) || `mid${mid}`;

    const videoA = Array.from(card.querySelectorAll('a[href]'))
      .find((a) => /\/video\//.test(a.getAttribute('href') || ''));
    const titleEl = card.querySelector('[class*="title"], [class*="video-title"]');
    const msgEl = card.querySelector('[class*="msg"], [class*="content"]');
    let title = clean(videoA && videoA.innerText);
    if (!title) title = clean(titleEl && titleEl.innerText);
    if (!title) title = clean(msgEl && msgEl.innerText);
    if (!title) title = text;

    const timeEl = card.querySelector('[class*="time"]');
    const time = clean(timeEl && timeEl.innerText);

    const key = `${mid}|${bv || ''}|${time}`;
    if (seen.has(key)) continue;
    seen.add(key);

    rows.push({ mid, uname: uname.slice(0, 60), bv: bv || null, title: title.slice(0, 120), time });
    if (rows.length >= limit) break;
  }

  const emptyMarker = Array.from(root.querySelectorAll('[class*="empty"], [class*="no-data"]'))
    .some((n) => /没有|暂无|空/.test(n.innerText || ''));
  return { ownMid, count: rows.length, empty: rows.length === 0 && emptyMarker, items: rows, href: location.href };
}
"""

# Runs inside the page: is this browser logged into Bilibili?
_EXTRACT_LOGIN = r"""
() => {
  const userRe = /space\.bilibili\.com\/(\d+)/;
  const headerLinks = Array.from(document.querySelectorAll('a[href*="space.bilibili.com/"]'));
  let uid = 0;
  for (const a of headerLinks) {
    const m = (a.getAttribute('href') || '').match(userRe);
    if (m && /avatar|header|nav/i.test(a.className || '') ) { uid = parseInt(m[1], 10); break; }
  }
  if (!uid && headerLinks.length) {
    const m = (headerLinks[0].getAttribute('href') || '').match(userRe);
    if (m) uid = parseInt(m[1], 10);
  }
  const sidebar = document.querySelectorAll('[class*="message-sidebar__item"]').length;
  const loginForm = document.querySelectorAll('input[type="password"], [class*="login-panel"]').length;
  return { uid, sidebar, loginForm, loggedIn: !!(uid || sidebar >= 3) && !loginForm,
           href: location.href, title: document.title };
}
"""


def ego_bin(settings=None) -> str:
    if settings is not None and getattr(settings, "ego_bin", ""):
        return settings.ego_bin
    if os.environ.get("EGO_BIN"):
        return os.environ["EGO_BIN"]
    found = shutil.which("ego-browser")
    if found:
        return found
    fallback = Path.home() / ".local" / "bin" / "ego-browser"
    if fallback.is_file():
        return str(fallback)
    raise BiliNoteError(
        "未找到 ego-browser，无法驱动本机浏览器。",
        hint="安装 ego lite（提供 ego-browser 命令），或在 .env 里用 EGO_BIN 指定绝对路径。",
    )


def parse_output(stdout: str, stderr: str = "") -> dict[str, Any]:
    """ego prints our JSON line to its console stream; tolerate extra chatter."""
    for blob in (stdout, stderr, stdout + "\n" + stderr):
        for line in reversed([ln.strip() for ln in (blob or "").splitlines() if ln.strip()]):
            if not (line.startswith("{") and line.endswith("}")):
                continue
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue
    raise BiliNoteError(
        "ego 脚本没有返回 JSON 结果。",
        hint=f"原始输出片段：{((stdout or '') + ' ' + (stderr or '')).strip()[:300] or '(空)'}",
    )


def run_script(js: str, settings=None, timeout: int = DEFAULT_TIMEOUT) -> dict[str, Any]:
    cmd = [ego_bin(settings), "nodejs"]
    try:
        proc = subprocess.run(
            cmd,
            input=js,
            text=True,
            capture_output=True,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise BiliNoteError(f"无法执行 ego-browser：{exc}") from exc
    except subprocess.TimeoutExpired as exc:
        raise BiliNoteError(
            f"ego 脚本超时（{timeout}s）。",
            hint="检查浏览器是否卡住或需要人工登录；重试一次通常即可。",
        ) from exc

    if proc.returncode != 0:
        # A late script error must not discard an already-emitted verdict
        # (e.g. the image was sent, then a follow-up read failed).
        try:
            result = parse_output(proc.stdout, proc.stderr)
            result["script_exit"] = proc.returncode
            result["stderr_tail"] = (proc.stderr or "").strip()[-300:]
            return result
        except BiliNoteError:
            pass
        detail = (proc.stderr or proc.stdout or "").strip().splitlines()
        raise BiliNoteError(
            "ego 脚本执行失败。",
            hint=(detail[-1][:300] if detail else f"exit code {proc.returncode}"),
        )
    return parse_output(proc.stdout, proc.stderr)


def _space(name: str) -> str:
    return json.dumps(name, ensure_ascii=False)


def _finish_js() -> str:
    return "await task.finish({ keep: [] });"


def browser_check(settings=None, timeout: int = DEFAULT_TIMEOUT) -> dict[str, Any]:
    """Read-only probe: login state + how many @ notifications are visible."""
    name = f"bili-note check {int(time.time())}"
    js = f"""
const task = await taskSpace({_space(name)});
const page = task.page("p1");
await page.goto({json.dumps(AT_URL)}, {{ waitUntil: "domcontentloaded" }});
await page.waitForTimeout(3500);

const login = await page.evaluate({_EXTRACT_LOGIN});
let at = {{ count: 0, items: [], empty: false }};
if (login.loggedIn) {{
  for (let i = 0; i < 8; i++) {{
    at = await page.evaluate({_EXTRACT_AT}, {{ limit: 20 }});
    if (at.count > 0 || at.empty) break;
    await page.waitForTimeout(1000);
  }}
}}
emit({{ loggedIn: login.loggedIn, uid: login.uid, sidebar: login.sidebar,
        atCount: at.count, first: (at.items && at.items[0]) || null,
        empty: !!at.empty, href: login.href }});
{_finish_js()}
"""
    return run_script(_prelude + js, settings=settings, timeout=timeout)


def fetch_at(settings=None, limit: int = 20, timeout: int = DEFAULT_TIMEOUT) -> list[dict[str, Any]]:
    """Return @-notification rows: mid / uname / bv / title / time."""
    name = f"bili-note at {int(time.time())}"
    js = f"""
const task = await taskSpace({_space(name)});
const page = task.page("p1");
await page.goto({json.dumps(AT_URL)}, {{ waitUntil: "domcontentloaded" }});
await page.waitForTimeout(3500);

const login = await page.evaluate({_EXTRACT_LOGIN});
if (!login.loggedIn) {{
  emit({{ error: "not_logged_in", href: login.href }});
}} else {{
  let data = {{ count: 0, items: [], empty: false }};
  for (let i = 0; i < 10; i++) {{
    data = await page.evaluate({_EXTRACT_AT}, {{ limit: {int(limit)} }});
    if (data.count > 0 || data.empty) break;
    await page.waitForTimeout(1000);
  }}
  emit({{ ok: true, count: data.count, items: data.items, href: data.href }});
}}
{_finish_js()}
"""
    result = run_script(_prelude + js, settings=settings, timeout=timeout)
    if result.get("error") == "not_logged_in":
        raise BiliNoteError(
            "ego 浏览器里没有登录 B 站。",
            hint="先在 ego lite 的浏览器窗口里登录 bilibili.com，再重跑 --browser-check。",
        )
    return list(result.get("items") or [])


def fetch_reply(settings=None, bot_uname: str = "", limit: int = 20,
                timeout: int = DEFAULT_TIMEOUT) -> list[dict[str, Any]]:
    """Read `x/msgfeed/reply` and keep only comments that @-mention the bot.

    On Bilibili, being @-ed in a comment under *your own* video lands in the
    reply channel, not the @ channel, and the card DOM carries no BV. The JSON
    does: item.uri has the bvid (fallback: view?aid=<subject_id>).
    """
    if not bot_uname:
        return []
    name = f"bili-note reply {int(time.time())}"
    js = f"""
const task = await taskSpace({_space(name)});
const page = task.page("p1");
await page.goto({json.dumps(REPLY_URL)}, {{ waitUntil: "domcontentloaded" }});
await page.waitForTimeout(3000);

const BOT = {json.dumps(bot_uname)};
const resp = await page.fetch({json.dumps(REPLY_API)}, {{ credentials: "include" }});
let body = resp.body;
if (typeof body === "string") body = JSON.parse(body);
if (!body || body.code !== 0) {{
  emit({{ error: "api", code: body && body.code }});
}} else {{
  const items = (body.data && body.data.items) || [];
  const rows = [];
  for (const it of items) {{
    const item = it.item || {{}};
    const user = it.user || {{}};
    const text = String(item.source_content || "");
    const ats = (item.at_details || []).map((a) => String(a.nickname || a.uname || ""));
    const mentioned = text.toLowerCase().includes("@" + BOT.toLowerCase()) ||
      ats.some((n) => n.toLowerCase() === BOT.toLowerCase());
    if (!mentioned) continue;

    const uri = String(item.uri || item.native_uri || "");
    const m = uri.match(/(BV[0-9A-Za-z]{{10}})/);
    let bvid = m ? m[1] : null;
    const aid = item.subject_id || null;
    if (!bvid && aid) {{
      try {{
        const vr = await page.fetch("https://api.bilibili.com/x/web-interface/view?aid=" + aid, {{ credentials: "include" }});
        let vb = vr.body; if (typeof vb === "string") vb = JSON.parse(vb);
        bvid = (vb && vb.data && vb.data.bvid) || null;
      }} catch (e) {{}}
    }}
    rows.push({{ mid: user.mid, uname: user.nickname || "", time: it.reply_time || 0,
                aid, bvid, title: String(item.title || ""), comment: text, uri }});
    if (rows.length >= {int(limit)}) break;
  }}
  emit({{ ok: true, count: rows.length, items: rows }});
}}
{_finish_js()}
"""
    result = run_script(_prelude + js, settings=settings, timeout=timeout)
    if result.get("error") == "api":
        raise BiliNoteError(
            f"读取「回复我的」失败：code={result.get('code')}",
            hint="cookie 可能失效；在 ego lite 浏览器里重新登录 B 站。",
        )
    return list(result.get("items") or [])


def peer_uname(mid: int, settings=None, timeout: int = DEFAULT_TIMEOUT) -> str:
    """Read-only: open the conversation and return the peer's display name."""
    if not mid:
        raise BiliNoteError("缺少 mid，无法读取会话昵称。")
    name = f"bili-note peer {int(mid)} {int(time.time())}"
    js = f"""
const task = await taskSpace({_space(name)});
const page = task.page("p1");
await page.goto({json.dumps(DM_URL.format(mid=int(mid)))}, {{ waitUntil: "domcontentloaded" }});
await page.waitForSelector("div.brt-editor", {{ state: "visible", timeout: 30000 }});
await page.waitForTimeout(1200);
const header = await page.evaluate(() => {{
  const el = document.querySelector("[class*='ContactName']");
  return el ? (el.innerText || "").trim() : "";
}});
emit({{ ok: true, header }});
{_finish_js()}
"""
    result = run_script(_prelude + js, settings=settings, timeout=timeout)
    return str(result.get("header") or "")


def send_dm(mid: int, image_path: Path, settings=None, expect_uname: str | None = None,
            timeout: int = DEFAULT_TIMEOUT) -> dict[str, Any]:
    """Send one image DM to `mid`.

    Bilibili's web IM uploads and sends an image as soon as the file is chosen,
    so picking the file *is* the send action; we verify a new picture bubble.
    With `expect_uname`, the conversation header is checked *before* the file is
    chosen and the send aborts on mismatch.
    """
    image_path = Path(image_path).resolve()
    if not image_path.is_file():
        raise BiliNoteError(f"待发送图片不存在：{image_path}")
    if not mid:
        raise BiliNoteError("缺少接收人 mid，无法发送私信。")

    url = DM_URL.format(mid=int(mid))
    name = f"bili-note dm {int(mid)} {int(time.time())}"
    expected = json.dumps(expect_uname or "")
    js = f"""
const task = await taskSpace({_space(name)});
const page = task.page("p1");
await page.goto({json.dumps(url)}, {{ waitUntil: "domcontentloaded" }});
await page.waitForSelector("div.brt-editor", {{ state: "visible", timeout: 30000 }});
await page.waitForTimeout(1500);

const readHeader = () => page.evaluate(() => {{
  const el = document.querySelector("[class*='ContactName']");
  return el ? (el.innerText || "").trim() : "";
}});
const countPictures = () => page.evaluate(() =>
  document.querySelectorAll("[class*='Msg__Content'][data-content-type='picture']").length);

const headerBefore = await readHeader();
const expected = {expected};
let before = 0, after = 0, tip = "", error = "";

if (expected && headerBefore !== expected) {{
  emit({{ ok: false, aborted: "uname_mismatch", header: headerBefore, expected }});
}} else {{
  try {{
    before = await countPictures();
    const chooserPromise = page.waitForFileChooser({{ timeout: 15000 }});
    await page.click("loc=css:[class*='MessageSendBox__ToolBtn'] i.sic-BDC-image_line");
    const chooser = await chooserPromise;
    await chooser.setFiles([{json.dumps(str(image_path))}]);

    const deadline = Date.now() + 45000;
    while (Date.now() < deadline) {{
      await page.waitForTimeout(1000);
      after = await countPictures();
      if (after > before) break;
    }}
    tip = await page.evaluate(() => {{
      const nodes = Array.from(document.querySelectorAll("[class*='MsgTip'], [class*='Msg__Content'][data-content-type='tip']"));
      return nodes.length ? (nodes[nodes.length - 1].innerText || "").trim() : "";
    }});
  }} catch (e) {{
    error = String(e).slice(0, 300);
    try {{ after = await countPictures(); }} catch (e2) {{}}
  }}
  // `after > before` is the only success signal: the image bubble appeared.
  emit({{ ok: after > before, before, after, header: headerBefore, tip, error, url: location.href }});
}}
await task.finish({{ keep: [] }});
"""
    result = run_script(_prelude + js, settings=settings, timeout=timeout)
    if result.get("aborted") == "uname_mismatch":
        raise BiliNoteError(
            f"收件人校验失败：会话页显示「{result.get('header')}」，期望「{result.get('expected')}」",
            hint="已中止发送，未选择任何图片。请核对 --to 的 mid。",
        )
    if not result.get("ok"):
        raise BiliNoteError(
            "ego 发送图片消息未确认成功。",
            hint=f"会话：{result.get('header') or mid}；页面提示：{result.get('tip') or '(无)'}",
        )
    return result
