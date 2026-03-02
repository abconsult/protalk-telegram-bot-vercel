#!/usr/bin/env python3
"""
scripts/generate_templates.py

Standalone script for local preview and development.
Generates the 3 template postcard images and saves them to
assets/templates/ so you can inspect them before deploying.

Usage:
    python scripts/generate_templates.py

Requires Pillow:
    pip install Pillow
"""
import os
import sys

# Allow running from repo root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from bot.config import TEMPLATE_POSTCARDS
from bot.template_generator import generate_template_image

OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "assets", "templates")
os.makedirs(OUT_DIR, exist_ok=True)

for tmpl in TEMPLATE_POSTCARDS:
    tid = tmpl["id"]
    path = os.path.join(OUT_DIR, f"{tid}.jpg")
    data = generate_template_image(tid)
    with open(path, "wb") as f:
        f.write(data)
    print(f"✅  {tid}.jpg  —  {len(data) // 1024} KB  →  {path}")

print("\nDone. Open assets/templates/ to preview the cards.")
