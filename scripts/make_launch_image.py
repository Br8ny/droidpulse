#!/usr/bin/env python3
"""Render the launch/social-preview card from the generated leaderboard."""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
W, H = 1200, 630


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = (
        ["C:/Windows/Fonts/segoeuib.ttf", "C:/Windows/Fonts/segoeui.ttf"]
        if bold else ["C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/segoeuib.ttf"]
    ) + ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
         "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]
    for path in candidates:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def main() -> None:
    payload = json.loads((ROOT / "data" / "apps.json").read_text(encoding="utf-8"))
    apps = payload["apps"][:5]

    image = Image.new("RGB", (W, H))
    draw = ImageDraw.Draw(image)
    for y in range(H):
        t = y / H
        color = (int(13 + 12 * t), int(15 + 10 * t), int(28 + 30 * t))
        draw.line((0, y, W, y), fill=color)

    accent, mint, white, muted = (124, 92, 255), (0, 212, 177), (238, 241, 247), (154, 163, 181)

    draw.rounded_rectangle((54, 46, 156, 78), radius=16, fill=accent)
    draw.text((70, 50), "DP", font=font(20, True), fill=white)

    draw.text((54, 100), "droid", font=font(66, True), fill=white)
    draw.text((212, 100), "pulse", font=font(66, True), fill=accent)
    draw.text((56, 184), "Trending open-source Android apps, ranked by momentum.",
              font=font(25), fill=muted)

    draw.text((56, 248), "TOP 5 RIGHT NOW", font=font(18, True), fill=mint)

    y = 286
    for rank, app in enumerate(apps, 1):
        name = app["name"] if len(app["name"]) <= 32 else app["name"][:31] + "…"
        draw.rounded_rectangle((54, y, 1146, y + 52), radius=12,
                               fill=(28, 32, 44), outline=(52, 58, 78), width=1)
        draw.text((70, y + 12), f"{rank:02d}", font=font(20, True), fill=accent)
        draw.text((112, y + 12), name, font=font(22, True), fill=white)
        draw.text((660, y + 14), app["category"], font=font(16), fill=muted)
        draw.text((880, y + 14), f"{app['stars']:,} stars", font=font(18), fill=white)
        draw.text((1070, y + 14), f"{app['score']}", font=font(17, True), fill=mint)
        y += 60

    draw.text((56, 600), "br8ny.github.io/droidpulse   •   one click to the official release",
              font=font(18), fill=muted)

    out = ROOT / "docs" / "launch.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    image.save(out)
    print(f"Wrote {out} ({W}x{H})")


if __name__ == "__main__":
    main()
