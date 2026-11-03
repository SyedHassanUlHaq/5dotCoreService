import os

import yt_dlp


_YTDL_COOKIES_FILE = os.getenv("YTDL_COOKIES_FILE", "")

_YTDL_BASE_OPTS = {
    "quiet": True,
    "no_warnings": False,
    "socket_timeout": 30,
    "retries": 5,
    "fragment_retries": 5,
    "http_headers": {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0.0.0 Safari/537.36"
        ),
    },
    "extractor_args": {
        "youtube": {"player_client": ["android_vr", "web"]},
    },
}

if _YTDL_COOKIES_FILE and os.path.exists(_YTDL_COOKIES_FILE):
    _YTDL_BASE_OPTS["cookiefile"] = _YTDL_COOKIES_FILE


def _ytdl_download(url: str, out_path: str) -> dict:
    """Download url to out_path, return info dict. Raises on failure."""
    opts = {
        **_YTDL_BASE_OPTS,
        "outtmpl": out_path,
        "format": "bestvideo[ext=mp4][height<=1080]+bestaudio[ext=m4a]/bestvideo[ext=mp4]+bestaudio/best[ext=mp4]/best",
        "merge_output_format": "mp4",
        "postprocessors": [{"key": "FFmpegVideoConvertor", "preferedformat": "mp4"}],
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        return ydl.extract_info(url, download=True) or {}