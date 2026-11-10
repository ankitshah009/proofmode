"""Render the fictional suspicious email used by the built-in example.

The organisation, sender and domains are invented. The screenshot carries the sender
line and the five body claims the example checks against the official facts.
Run with: uv run --with pillow python scripts/make_sample.py
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "src" / "proofmode" / "static" / "sample.png"
WIDTH, HEIGHT = 1200, 800

SENDER_NAME = "Tidewater Cloud Billing"
SENDER_ADDRESS = "<billing@tidewater-accounts.co>"
SUBJECT = "Action required: your credits expire today"
BODY_LINES = (
    "Your API credits expire in 24 hours.",
    "Pay a $49 reactivation fee to keep your account.",
    "We accept gift cards for faster processing.",
)
LINK_LINE = "Verify now at tidewater-accounts.co"
CLOSING_LINE = "Support is available 24/7."

PAGE = (255, 255, 255)
CHROME = (246, 248, 252)
RULE = (224, 227, 232)
INK = (32, 33, 36)
MUTED = (95, 99, 104)
FAINT = (154, 160, 166)
LINK = (26, 115, 232)
AVATAR = (0, 121, 107)
WARN_BG = (254, 247, 224)
WARN_INK = (120, 84, 0)

_REGULAR = ("Arial.ttf", "Helvetica.ttc", "DejaVuSans.ttf", "LiberationSans-Regular.ttf")
_BOLD = ("Arial Bold.ttf", "Helvetica.ttc", "DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf")


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Load a system sans-serif by file name, falling back to Pillow's default."""
    for name in _BOLD if bold else _REGULAR:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def _toolbar(draw: ImageDraw.ImageDraw) -> None:
    draw.rectangle((0, 0, WIDTH, 64), fill=CHROME)
    draw.line((0, 64, WIDTH, 64), fill=RULE, width=1)
    # Back arrow.
    draw.line((40, 32, 60, 32), fill=MUTED, width=3)
    draw.line((40, 32, 49, 23), fill=MUTED, width=3)
    draw.line((40, 32, 49, 41), fill=MUTED, width=3)
    draw.text((84, 20), "Inbox", font=font(20), fill=MUTED)
    right = WIDTH - 72
    action_font = font(18)
    for label in ("Delete", "Report spam", "Archive"):
        right -= draw.textlength(label, font=action_font)
        draw.text((right, 21), label, font=action_font, fill=MUTED)
        right -= 36


def _header(draw: ImageDraw.ImageDraw) -> None:
    draw.text((72, 100), SUBJECT, font=font(34), fill=INK)

    draw.ellipse((72, 176, 128, 232), fill=AVATAR)
    initial_font = font(28, bold=True)
    initial_width = draw.textlength("T", font=initial_font)
    draw.text((100 - initial_width / 2, 188), "T", font=initial_font, fill=PAGE)

    name_font = font(21, bold=True)
    draw.text((148, 178), SENDER_NAME, font=name_font, fill=INK)
    name_width = draw.textlength(SENDER_NAME, font=name_font)
    draw.text((148 + name_width + 10, 180), SENDER_ADDRESS, font=font(19), fill=MUTED)
    draw.text((148, 208), "to me", font=font(18), fill=MUTED)

    date_text = "Mon 9 Nov, 08:14"
    date_font = font(18)
    date_left = WIDTH - 72 - draw.textlength(date_text, font=date_font)
    draw.text((date_left, 180), date_text, font=date_font, fill=MUTED)

    draw.rounded_rectangle((72, 260, WIDTH - 72, 308), radius=8, fill=WARN_BG)
    draw.text(
        (92, 273),
        "This sender is not in your contacts.",
        font=font(18),
        fill=WARN_INK,
    )


def render(extra_lines: tuple[str, ...] = ()) -> Image.Image:
    """Draw the email screenshot. extra_lines are appended as small print at the end."""
    image = Image.new("RGB", (WIDTH, HEIGHT), PAGE)
    draw = ImageDraw.Draw(image)
    _toolbar(draw)
    _header(draw)

    body_font = font(24)
    y = 350
    for line in BODY_LINES:
        draw.text((72, y), line, font=body_font, fill=INK)
        y += 52

    draw.text((72, y), LINK_LINE, font=body_font, fill=LINK)
    link_width = draw.textlength(LINK_LINE, font=body_font)
    draw.line((72, y + 30, 72 + link_width, y + 30), fill=LINK, width=2)
    y += 52

    draw.text((72, y), CLOSING_LINE, font=body_font, fill=INK)
    y += 60

    small_font = font(17)
    for line in extra_lines:
        draw.text((72, y), line, font=small_font, fill=FAINT)
        y += 28

    draw.line((72, 700, WIDTH - 72, 700), fill=RULE, width=1)
    for index, label in enumerate(("Reply", "Forward")):
        left = 72 + index * 150
        draw.rounded_rectangle((left, 724, left + 130, 768), radius=22, outline=RULE, width=2)
        label_font = font(18)
        label_width = draw.textlength(label, font=label_font)
        draw.text((left + 65 - label_width / 2, 735), label, font=label_font, fill=MUTED)
    return image


def save(image: Image.Image, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    image.save(out, format="PNG", optimize=True)
    print(f"wrote {out.relative_to(ROOT)} ({out.stat().st_size} bytes)")


def main() -> None:
    save(render(), OUT)


if __name__ == "__main__":
    main()
