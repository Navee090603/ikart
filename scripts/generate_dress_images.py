#!/usr/bin/env python
"""Generate 48 isolated fashion product photos (12 dress styles x 4 views).

Uses Pollinations.ai's free, no-API-key image generation endpoint (Flux
model). For each dress style, the same random seed is reused across all
4 views so the model renders the same garment from different angles
instead of 4 unrelated dresses.

Usage:
    python scripts/generate_dress_images.py
    python scripts/generate_dress_images.py --styles sundress,wrap-dress
    python scripts/generate_dress_images.py --width 1024 --height 1536

Output:
    scripts/output/dress_images/<style-slug>/<01-front|02-three-quarter|03-side|04-back>.jpg
"""
import argparse
import sys
import time
import urllib.parse
from pathlib import Path

import requests

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "output" / "dress_images"

BACKGROUND_LIGHTING = (
    "empty garment floating in air, ghost mannequin invisible mannequin "
    "product photography effect, completely empty dress with no person, "
    "no human, no model, no face, no skin, no hair, no body, no mannequin "
    "visible, dress shown as if worn by an invisible person, "
    "solid sophisticated dark chocolate-brown textured studio background "
    "filling the entire frame, warm vintage studio lighting, subtle "
    "realistic soft shadows, highly detailed fabric texture, elegant "
    "old-money fashion editorial aesthetic, premium clothing catalog "
    "photography, photorealistic, clean centered composition, consistent "
    "camera height and scale, no accessories, no handbags, no shoes, "
    "no jewelry, no watermark, no logo, no text"
)

VIEWS = [
    ("01-front", "front view, garment facing camera directly, symmetrical framing"),
    ("02-three-quarter", "3/4 angle view, garment rotated roughly 45 degrees from camera"),
    ("03-side", "side profile view, garment rotated 90 degrees showing silhouette"),
    ("04-back", "back view, garment facing away from camera, showing back design details"),
]

DRESS_STYLES = {
    "sundress": (
        "A flowy cotton sundress in soft buttercream yellow with a fitted "
        "smocked bodice, thin adjustable spaghetti straps, and a wide "
        "gathered A-line skirt falling to mid-calf length"
    ),
    "slip-dress": (
        "A silky bias-cut slip dress in champagne beige satin, cowl neckline, "
        "thin delicate straps, mid-thigh length, minimalist 1990s silhouette "
        "with subtle sheen"
    ),
    "wrap-dress": (
        "A wrap dress in deep burgundy jersey knit, V-neckline crossing at "
        "the front, fabric-tie belt at the waist, three-quarter sleeves, "
        "knee-length flared skirt"
    ),
    "shirt-dress": (
        "A tailored shirt dress in crisp white cotton poplin, collared "
        "button-front closure, long sleeves with buttoned cuffs, fitted "
        "waist with a thin belt, midi length"
    ),
    "babydoll-dress": (
        "A babydoll dress in dusty rose chiffon, high empire waistline with "
        "a delicate ribbon, loose flowing skirt, short puffed sleeves, "
        "mini length"
    ),
    "tiered-dress": (
        "A tiered ruffle dress in muted terracotta cotton voile, three "
        "cascading ruffled tiers from waist to hem, square neckline, "
        "short flutter sleeves, midi length"
    ),
    "tea-dress": (
        "A vintage-inspired tea dress in soft sage green floral-textured "
        "crepe, fitted bodice with a gathered waist seam, knee-length "
        "flared skirt, short cap sleeves, round neckline"
    ),
    "mini-dress": (
        "A fitted mini dress in classic camel-tan ribbed knit, sleeveless "
        "with a high round neckline, straight bodycon silhouette skimming "
        "the body, hem hitting mid-thigh"
    ),
    "slip-maxi-dress": (
        "A floor-length slip maxi dress in deep emerald green satin, "
        "adjustable spaghetti straps, cowl neckline, sleek bias-cut "
        "silhouette flowing to the ankle"
    ),
    "a-line-dress": (
        "An A-line dress in warm mustard wool-blend twill, boat neckline, "
        "long fitted sleeves, seamed waist flowing into a gently flared "
        "A-line skirt, knee length"
    ),
    "cut-out-dress": (
        "A fitted cut-out dress in rich chocolate-brown stretch jersey, "
        "sleeveless with a single geometric cut-out at the waist and "
        "ribbed trim, bodycon silhouette, midi length"
    ),
    "halter-dress": (
        "A halter neck dress in ivory cream silky satin, fitted halter "
        "bodice tying at the back of the neck, open back, gently flared "
        "skirt falling to mid-calf"
    ),
}

POLLINATIONS_URL = "https://image.pollinations.ai/prompt/{prompt}"


def build_prompt(description: str, view_desc: str) -> str:
    return f"{description}, {view_desc}, {BACKGROUND_LIGHTING}"


def generate_image(prompt: str, seed: int, width: int, height: int, dest: Path, retries: int = 3) -> None:
    encoded = urllib.parse.quote(prompt)
    url = POLLINATIONS_URL.format(prompt=encoded)
    params = {
        "width": width,
        "height": height,
        "seed": seed,
        "nologo": "true",
        "nofeed": "true",
        "private": "true",
        "model": "flux",
    }
    last_error = None
    for attempt in range(1, retries + 1):
        try:
            resp = requests.get(url, params=params, timeout=120)
            resp.raise_for_status()
            dest.write_bytes(resp.content)
            return
        except requests.RequestException as exc:
            last_error = exc
            print(f"  attempt {attempt}/{retries} failed: {exc}", file=sys.stderr)
            time.sleep(3)
    raise RuntimeError(f"Failed to generate {dest}: {last_error}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--styles",
        help="Comma-separated subset of style slugs to generate (default: all 12)",
        default=None,
    )
    parser.add_argument("--width", type=int, default=1024)
    parser.add_argument("--height", type=int, default=1536)
    parser.add_argument(
        "--seed-base",
        type=int,
        default=42,
        help="Base seed; each style gets seed_base + index so it stays consistent across views",
    )
    args = parser.parse_args()

    selected = list(DRESS_STYLES.items())
    if args.styles:
        wanted = {s.strip() for s in args.styles.split(",")}
        selected = [(k, v) for k, v in DRESS_STYLES.items() if k in wanted]
        if not selected:
            print(f"No matching styles found for: {args.styles}", file=sys.stderr)
            sys.exit(1)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    total = len(selected) * len(VIEWS)
    done = 0
    for idx, (slug, description) in enumerate(selected):
        seed = args.seed_base + idx
        style_dir = OUTPUT_DIR / slug
        style_dir.mkdir(parents=True, exist_ok=True)
        print(f"\n=== {slug} (seed={seed}) ===")
        for view_slug, view_desc in VIEWS:
            done += 1
            dest = style_dir / f"{view_slug}.jpg"
            prompt = build_prompt(description, view_desc)
            print(f"[{done}/{total}] {view_slug} -> {dest}")
            generate_image(prompt, seed, args.width, args.height, dest)
            time.sleep(1)

    print(f"\nDone. Images saved under {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
