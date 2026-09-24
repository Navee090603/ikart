#!/usr/bin/env python
"""Upload a product's images to Cloudinary and print a CSV-ready `images` cell.

Usage:
    python scripts/upload_product_images.py <product-slug> <image1> <image2> ...

Reads Cloudinary credentials from the project's .env (via django-environ,
same as the Django app), uploads each image under products/<product-slug>/,
and prints the resulting secure URLs joined with "|" -- paste that
straight into the CSV's `images` column.
"""
import sys
from pathlib import Path

import environ
import cloudinary
import cloudinary.uploader

BASE_DIR = Path(__file__).resolve().parent.parent
env = environ.Env()
environ.Env.read_env(BASE_DIR / ".env")

cloudinary.config(
    cloud_name=env("CLOUDINARY_CLOUD_NAME"),
    api_key=env("CLOUDINARY_API_KEY"),
    api_secret=env("CLOUDINARY_API_SECRET"),
)


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)

    slug = sys.argv[1]
    image_paths = sys.argv[2:]
    urls = []

    for path in image_paths:
        result = cloudinary.uploader.upload(path, folder=f"products/{slug}")
        urls.append(result["secure_url"])
        print(f"Uploaded {path} -> {result['secure_url']}", file=sys.stderr)

    print("\nCSV images cell:")
    print("|".join(urls))


if __name__ == "__main__":
    main()
