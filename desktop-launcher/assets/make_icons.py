"""Draws the desktop app's placeholder icon and writes it in each OS's format.

    uv run --no-project --with pillow python desktop-launcher/assets/make_icons.py

A white "c" on the blue rounded square the desktop welcome screen uses
(#0969da), drawn from shapes rather than a font so it comes out the same
anywhere. Writes civex.png (1024 px), civex.ico (Windows) and civex.icns
(macOS) beside this file. Replace civex.png with a real logo and adapt
`draw` when there is one.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
SIZE = 1024
BLUE = (9, 105, 218, 255)
WHITE = (255, 255, 255, 255)


def draw() -> Image.Image:
    # Drawn 4x larger and scaled down, for smooth edges.
    big = SIZE * 4
    image = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    pen = ImageDraw.Draw(image)
    margin = big // 10  # macOS icons leave a margin round the square
    pen.rounded_rectangle(
        (margin, margin, big - margin, big - margin), radius=big // 5, fill=BLUE
    )
    # The "c": a thick ring with its right side cut away.
    centre, outer, thickness = big // 2, big * 0.24, big * 0.085
    box = (centre - outer, centre - outer, centre + outer, centre + outer)
    pen.arc(box, start=45, end=315, fill=WHITE, width=int(thickness))
    return image.resize((SIZE, SIZE), Image.LANCZOS)


def main() -> None:
    icon = draw()
    icon.save(HERE / "civex.png")
    icon.save(
        HERE / "civex.ico",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    icon.save(HERE / "civex.icns")
    print(f"wrote civex.png, civex.ico and civex.icns in {HERE}")


if __name__ == "__main__":
    main()
