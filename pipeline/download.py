"""Download the video with yt-dlp and cut keyframes with ffmpeg."""

from __future__ import annotations

import math
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from util import BiliNoteError

VIDEO_URL = "https://www.bilibili.com/video/{bv}"

# Lowest usable quality: 480p is enough for the card thumbnails and keeps the
# download small. Falls back to whatever is available if 480p is missing.
FORMAT_SELECTOR = "bv*[height<=480]+ba/b[height<=480]/bv*+ba/b"
MAX_HEIGHT = 480


@dataclass
class VideoMeta:
    bv: str
    path: Path
    title: str
    up_name: str
    duration: int
    description: str = ""

    @property
    def url(self) -> str:
        return VIDEO_URL.format(bv=self.bv)


def have_ffmpeg() -> bool:
    return shutil.which("ffmpeg") is not None


def _ffmpeg_dir() -> str | None:
    exe = shutil.which("ffmpeg")
    return str(Path(exe).parent) if exe else None


def download(bv: str, work_dir: Path, max_duration_min: int = 30,
             cookie: str = "", user_agent: str = "", logger=None) -> VideoMeta:
    try:
        from yt_dlp import YoutubeDL
        from yt_dlp.utils import DownloadError
    except ImportError as exc:  # pragma: no cover - dependency guard
        raise BiliNoteError("缺少依赖 yt-dlp，请先 pip install -r requirements.txt") from exc

    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    if not have_ffmpeg():
        raise BiliNoteError("未找到 ffmpeg，无法合并音视频/抽帧。",
                            hint="macOS: brew install ffmpeg；或设置 PATH 后重试。")

    headers = {"Referer": "https://www.bilibili.com/"}
    if cookie:
        headers["Cookie"] = cookie
    if user_agent:
        headers["User-Agent"] = user_agent

    opts = {
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "noplaylist": True,
        "retries": 2,
        "socket_timeout": 30,
        "outtmpl": str(work_dir / f"{bv}.%(ext)s"),
        "format": FORMAT_SELECTOR,
        "format_sort": ["res:480"],
        "merge_output_format": "mp4",
        "ffmpeg_location": _ffmpeg_dir(),
        "http_headers": headers,
    }

    try:
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(VIDEO_URL.format(bv=bv), download=True)
    except DownloadError as exc:
        raise BiliNoteError(
            f"视频下载失败：{bv}",
            hint=f"yt-dlp 报错：{str(exc).splitlines()[0] if str(exc) else 'unknown'}",
        ) from exc

    if info.get("_type") == "playlist":
        entries = [e for e in (info.get("entries") or []) if e]
        if not entries:
            raise BiliNoteError(f"视频下载失败：{bv} 没有可用分 P")
        info = entries[0]

    duration = int(info.get("duration") or 0)
    if max_duration_min and duration > max_duration_min * 60:
        raise BiliNoteError(
            f"视频过长（{duration // 60} 分钟 > 上限 {max_duration_min} 分钟），已跳过。"
        )

    downloads = info.get("requested_downloads") or []
    filepath = downloads[0].get("filepath") if downloads else None
    path = Path(filepath) if filepath else Path(info.get("_filename") or "")
    if not path.is_file():
        candidates = sorted(work_dir.glob(f"{bv}.*"), key=lambda p: p.stat().st_size, reverse=True)
        path = candidates[0] if candidates else path
    if not path.is_file():
        raise BiliNoteError(f"视频下载失败：{bv} 未落地文件")

    if logger:
        logger.info("已下载 %s → %s (%.1f MB)", bv, path.name, path.stat().st_size / 1e6)

    return VideoMeta(
        bv=bv,
        path=path,
        title=str(info.get("title") or bv).strip(),
        up_name=str(info.get("uploader") or info.get("channel") or "").strip(),
        duration=duration,
        description=str(info.get("description") or "").strip()[:2000],
    )


def frame_timestamps(duration: int, count: int = 12) -> list[float]:
    """Evenly spread `count` sample points over the video, avoiding the edges."""
    duration = max(1, int(duration or 1))
    count = max(1, int(count))
    return [round((i + 0.5) * duration / count, 2) for i in range(count)]


MIN_FRAMES, MAX_FRAMES = 4, 12
MIN_CHAPTERS, MAX_CHAPTERS = 2, 5


def frame_count_for(duration: int, cap: int = MAX_FRAMES) -> int:
    """clamp(ceil(duration / 10), 4, 12) — a 13s video gets 4 frames, not 12."""
    seconds = max(1, int(duration or 1))
    wanted = math.ceil(seconds / 10)
    return max(MIN_FRAMES, min(wanted, min(max(1, int(cap)), MAX_FRAMES)))


def chapter_count_for(duration: int) -> int:
    """clamp(round(duration / 90) + 1, 2, 5) — 13s → 2, 180s → 3, 360s → 5."""
    seconds = max(1, int(duration or 1))
    wanted = int(round(seconds / 90)) + 1
    return max(MIN_CHAPTERS, min(wanted, MAX_CHAPTERS))


def extract_frame(video_path: Path, ts: float, out_path: Path,
                  max_height: int = MAX_HEIGHT) -> Path:
    """Grab one frame at `ts` seconds. Never upscales: caps height at `max_height`."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-ss", f"{max(0.0, float(ts)):.2f}",
        "-i", str(video_path),
        "-frames:v", "1",
        "-vf", f"scale=-2:min({max_height}\\,ih)",
        "-q:v", "3",
        str(out_path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if proc.returncode != 0 or not out_path.is_file():
        raise BiliNoteError(
            f"抽帧失败（ts={ts}）：{proc.stderr.strip()[:300]}",
        )
    return out_path


def extract_frames(video_path: Path, timestamps: list[float], out_dir: Path,
                   max_height: int = MAX_HEIGHT) -> list[Path]:
    """Cut one PNG per timestamp; pixel size follows the 480p source."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for i, ts in enumerate(timestamps):
        paths.append(
            extract_frame(video_path, ts, out_dir / f"frame_{i:02d}.png", max_height=max_height)
        )
    return paths
