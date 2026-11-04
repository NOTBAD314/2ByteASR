"""Build transparent application icons from the approved square mascot art."""

import argparse
from collections import deque
from pathlib import Path

from PIL import Image, ImageFilter


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "assets" / "2byteasr-icon-source.png"
PNG_OUTPUT = ROOT / "assets" / "2byteasr-icon-transparent.png"
ICO_OUTPUT = ROOT / "assets" / "2byteasr.ico"


def is_edge_background(pixel):
    red, green, blue = pixel
    return max(red, green, blue) <= 8


def connected_background_mask(image):
    width, height = image.size
    pixels = image.load()
    visited = bytearray(width * height)
    queue = deque()

    def enqueue(x, y):
        offset = y * width + x
        if visited[offset] or not is_edge_background(pixels[x, y]):
            return
        visited[offset] = 1
        queue.append((x, y))

    for x in range(width):
        enqueue(x, 0)
        enqueue(x, height - 1)
    for y in range(height):
        enqueue(0, y)
        enqueue(width - 1, y)

    while queue:
        x, y = queue.popleft()
        if x:
            enqueue(x - 1, y)
        if x + 1 < width:
            enqueue(x + 1, y)
        if y:
            enqueue(x, y - 1)
        if y + 1 < height:
            enqueue(x, y + 1)

    alpha = Image.new("L", image.size, 255)
    alpha_pixels = alpha.load()
    for y in range(height):
        row = y * width
        for x in range(width):
            if visited[row + x]:
                alpha_pixels[x, y] = 0
    # Contract one antialiased background pixel, then soften the cut edge.
    return alpha.filter(ImageFilter.MinFilter(3)).filter(ImageFilter.GaussianBlur(0.45))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, help="New approved mascot artwork")
    args = parser.parse_args()

    input_path = args.source.resolve() if args.source else SOURCE
    source = Image.open(input_path).convert("RGB")
    if args.source:
        source.save(SOURCE, format="PNG", optimize=True)
    alpha = connected_background_mask(source)
    rgba = source.convert("RGBA")
    rgba.putalpha(alpha)

    # Keep the complete silhouette with optical safety space. The same master is
    # used in the header and for Windows icon sizes, so no ear or hair is clipped.
    bbox = alpha.getbbox() or (0, 0, rgba.width, rgba.height)
    visible = rgba.crop(bbox)
    side = max(visible.width, visible.height)
    margin = max(1, round(side * 0.055))
    canvas_side = side + margin * 2
    canvas = Image.new("RGBA", (canvas_side, canvas_side), (0, 0, 0, 0))
    canvas.paste(
        visible,
        ((canvas_side - visible.width) // 2, (canvas_side - visible.height) // 2),
        visible,
    )
    rgba = canvas.resize((1200, 1200), Image.Resampling.LANCZOS)
    rgba.save(PNG_OUTPUT, format="PNG", optimize=True)
    rgba.save(
        ICO_OUTPUT,
        format="ICO",
        sizes=[(16, 16), (20, 20), (24, 24), (32, 32), (40, 40), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    print(PNG_OUTPUT)
    print(ICO_OUTPUT)


if __name__ == "__main__":
    main()
