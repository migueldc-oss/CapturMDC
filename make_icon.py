"""Generate app.ico (multi-size Windows icon) for the CapturMDC executable."""

from PIL import Image, ImageDraw

ACCENT = (79, 179, 255, 255)
ACCENT_PAUSED = (255, 184, 79, 255)
DARK = (11, 19, 32, 255)


def draw_camera(size: int, paused: bool = False) -> Image.Image:
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    accent = ACCENT_PAUSED if paused else ACCENT
    s = size / 32.0

    body = (4 * s, 10 * s, 28 * s, 26 * s)
    draw.rounded_rectangle(body, radius=4 * s, fill=accent)
    draw.rectangle((8 * s, 6 * s, 16 * s, 11 * s), fill=accent)
    draw.ellipse((12 * s, 13 * s, 22 * s, 23 * s), fill=DARK)
    draw.ellipse((15 * s, 16 * s, 19 * s, 20 * s), fill=accent)

    if paused:
        draw.rectangle((24 * s, 6 * s, 26 * s, 12 * s), fill=(255, 255, 255, 255))
        draw.rectangle((28 * s, 6 * s, 30 * s, 12 * s), fill=(255, 255, 255, 255))

    return image


def main() -> None:
    sizes = [(s, s) for s in (16, 24, 32, 48, 64, 128, 256)]
    base = draw_camera(256)
    base.save("app.ico", format="ICO", sizes=sizes)
    print("wrote app.ico")


if __name__ == "__main__":
    main()
