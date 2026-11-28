"""Try downloading one URL through each proxy listed in a text file."""

import argparse
import sys
import tempfile
from pathlib import Path
from urllib.parse import quote

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from utils.ytdl import _ytdl_download


def normalize_proxy(value: str) -> str:
    """Accept scheme://host:port, host:port, or host:port:user:password."""
    value = value.strip()
    if "://" in value:
        return value

    fields = value.split(":")
    if len(fields) == 4:
        host, port, username, password = fields
        username = quote(username, safe="")
        password = quote(password, safe="")
        return f"http://{username}:{password}@{host}:{port}"
    if len(fields) == 2:
        return f"http://{value}"
    raise ValueError("expected scheme://host:port, host:port, or host:port:user:password")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", help="Media URL supported by yt-dlp")
    parser.add_argument(
        "--proxy-file",
        type=Path,
        default=REPO_ROOT / "proxies.txt",
        help="One proxy per line (default: proxies.txt in the repository root)",
    )
    args = parser.parse_args()

    entries = [
        line.strip()
        for line in args.proxy_file.read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    if not entries:
        parser.error(f"No proxies found in {args.proxy_file}")

    successes = 0
    for index, entry in enumerate(entries, start=1):
        try:
            proxy = normalize_proxy(entry)
        except ValueError as exc:
            print(f"Proxy {index}: invalid format ({exc})")
            continue

        try:
            with tempfile.TemporaryDirectory(prefix=f"ytdl-proxy-{index}-") as tmp_dir:
                output_template = str(Path(tmp_dir) / "download.%(ext)s")
                info = _ytdl_download(args.url, output_template, proxy=proxy)
                downloaded = any(path.is_file() for path in Path(tmp_dir).iterdir())
                if not downloaded:
                    print(f"Proxy {index}: extraction succeeded, but no file was downloaded")
                    continue
                successes += 1
                print(
                    f"Proxy {index}: OK — {info.get('title', 'unknown title')} "
                    f"({info.get('duration', 'unknown')} seconds)"
                )
        except Exception as exc:
            # Do not print proxy URLs: they may contain usernames/passwords.
            print(f"Proxy {index}: FAILED — {type(exc).__name__}")

    print(f"\nDownload succeeded through {successes} of {len(entries)} proxies.")
    return 0 if successes else 1


if __name__ == "__main__":
    raise SystemExit(main())
