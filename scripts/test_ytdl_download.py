"""Manually download a URL to a temporary directory using the app's yt-dlp helper."""

import argparse
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utils.ytdl import _ytdl_download


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", help="Media URL supported by yt-dlp")
    args = parser.parse_args()

    with tempfile.TemporaryDirectory(prefix="ytdl-test-") as tmp_dir:
        output_template = str(Path(tmp_dir) / "download.%(ext)s")
        info = _ytdl_download(args.url, output_template)
        files = [path for path in Path(tmp_dir).iterdir() if path.is_file()]

        print(f"Downloaded to: {files[0] if files else tmp_dir}")
        print(f"Title: {info.get('title', 'unknown')}")
        print(f"Temporary files are removed when this script exits.")


if __name__ == "__main__":
    main()
