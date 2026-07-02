from pathlib import Path

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "/Users/pavel.loginov/Documents/GitHub/IncidentRelay/app/static/images/only_logo.png"
OUT_DIR = ROOT / "/Users/pavel.loginov/Documents/GitHub/IncidentRelay/app/static/images/pwa"


ICON_BG = (255, 255, 255, 255)
MASKABLE_BG = (255, 255, 255, 255)

# Удаляем светлый серо-белый checkerboard, но не трогаем цветной логотип.
NEUTRAL_MIN_VALUE = 170
NEUTRAL_DELTA = 18

ICON_LOGO_SCALE = 0.92
MASKABLE_LOGO_SCALE = 0.82
APPLE_LOGO_SCALE = 0.92

RADIUS_RATIO = 0.20


def remove_light_neutral_background(image: Image.Image) -> Image.Image:
    """
    Удаляет белый/серый checkerboard-фон, если он запечён в PNG.
    Цветные части логотипа не трогает.
    """
    image = image.convert("RGBA")
    pixels = image.load()

    width, height = image.size

    for y in range(height):
        for x in range(width):
            r, g, b, a = pixels[x, y]

            if a == 0:
                continue

            max_channel = max(r, g, b)
            min_channel = min(r, g, b)

            is_light = min_channel >= NEUTRAL_MIN_VALUE
            is_neutral = (max_channel - min_channel) <= NEUTRAL_DELTA

            if is_light and is_neutral:
                pixels[x, y] = (255, 255, 255, 0)

    return image


def trim_transparent(image: Image.Image) -> Image.Image:
    image = image.convert("RGBA")
    bbox = image.getbbox()

    if bbox:
        return image.crop(bbox)

    return image


def prepare_logo(source: Path) -> Image.Image:
    logo = Image.open(source).convert("RGBA")
    logo = remove_light_neutral_background(logo)
    logo = trim_transparent(logo)
    return logo


def make_background(size: int, color) -> Image.Image:
    canvas = Image.new("RGBA", (size, size), color)
    return canvas


def resize_to_fit(image: Image.Image, max_size: int) -> Image.Image:
    image = image.copy()
    image.thumbnail((max_size, max_size), Image.LANCZOS)
    return image


def paste_center(canvas: Image.Image, image: Image.Image) -> None:
    x = (canvas.width - image.width) // 2
    y = (canvas.height - image.height) // 2
    canvas.alpha_composite(image, (x, y))


def make_icon(
    source: Path,
    size: int,
    out_path: Path,
    *,
    logo_scale: float,
    background,
) -> None:
    logo = prepare_logo(source)
    logo = resize_to_fit(logo, int(size * logo_scale))

    canvas = make_background(size, background)
    paste_center(canvas, logo)

    # Важно: сохраняем без альфы, чтобы нигде не было checkerboard-прозрачности.
    canvas.convert("RGB").save(out_path)


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    make_icon(
        SOURCE,
        192,
        OUT_DIR / "icon-192.png",
        logo_scale=ICON_LOGO_SCALE,
        background=ICON_BG,
    )

    make_icon(
        SOURCE,
        512,
        OUT_DIR / "icon-512.png",
        logo_scale=ICON_LOGO_SCALE,
        background=ICON_BG,
    )

    make_icon(
        SOURCE,
        192,
        OUT_DIR / "maskable-192.png",
        logo_scale=MASKABLE_LOGO_SCALE,
        background=MASKABLE_BG,
    )

    make_icon(
        SOURCE,
        512,
        OUT_DIR / "maskable-512.png",
        logo_scale=MASKABLE_LOGO_SCALE,
        background=MASKABLE_BG,
    )

    make_icon(
        SOURCE,
        180,
        OUT_DIR / "apple-touch-icon.png",
        logo_scale=APPLE_LOGO_SCALE,
        background=ICON_BG,
    )


if __name__ == "__main__":
    main()
