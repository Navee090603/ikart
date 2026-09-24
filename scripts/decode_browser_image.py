#!/usr/bin/env python
"""Decode a base64 image payload saved by the javascript_tool (browser MCP)
into an actual image file.

The javascript_tool truncates large results to a JSON file on disk of the
form [{"type": "text", "text": "<b64><trailing browser-tool noise>"}, ...].
This strips the trailing noise and writes the decoded bytes to `dest`.

Usage:
    python scripts/decode_browser_image.py <tool_result.json> <dest.jpg>
"""
import base64
import json
import sys


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)

    src_path, dest_path = sys.argv[1], sys.argv[2]
    with open(src_path) as f:
        data = json.load(f)

    text = data[0]["text"].lstrip('"')
    end_marker = '"\n\n(captured'
    idx = text.find(end_marker)
    if idx == -1:
        idx = text.rfind('"')
    b64 = text[:idx]

    img_bytes = base64.b64decode(b64)
    with open(dest_path, "wb") as out:
        out.write(img_bytes)
    print(f"{len(img_bytes)} bytes written to {dest_path}")


if __name__ == "__main__":
    main()
