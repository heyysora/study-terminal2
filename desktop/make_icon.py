"""Draws the app icon (the signal-meter mark from the UI) as a multi-size .ico. Run once; the result is committed."""
from pathlib import Path

from PIL import Image, ImageDraw

INK, BRASS, UP = (15, 20, 27, 255), (224, 164, 58, 255), (63, 182, 139, 255)


def draw(size: int) -> Image.Image:
    s = 256
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([8, 8, s - 8, s - 8], 44, fill=INK)
    # five meter bars rising left to right; the first four lit
    for k in range(5):
        x0 = 44 + k * 36
        h = 40 + k * 32
        d.rounded_rectangle([x0, 212 - h, x0 + 24, 212], 5, fill=BRASS if k < 4 else (60, 70, 84, 255))
    d.ellipse([40, 40, 74, 74], fill=UP)
    return img.resize((size, size), Image.LANCZOS)


if __name__ == "__main__":
    out = Path(__file__).parent / "assets"
    out.mkdir(exist_ok=True)
    big = draw(256)
    big.save(out / "study-terminal.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    big.save(out / "study-terminal.png")
    print("wrote", out)
