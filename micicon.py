"""Crisp, anti-aliased mic icon (drawn 4x larger, then downscaled). RGBA with real transparency."""
from PIL import Image, ImageDraw, ImageFilter

KEY = (1, 2, 3, 255)   # only used by the fallback colour-key path


def draw_mic(size=64, color="#0B6E99", pulse=None, button=True, key=False):
    """button=True: floating-button look (disc + soft shadow + optional pulse ring), no dark rim.
    button=False: flat disc on transparent background (tray).
    key=True: composite onto the colour-key background (fallback if per-pixel alpha is unavailable)."""
    k = 4
    s = size * k
    u = s / 64.0
    d_img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(d_img)

    def box(x0, y0, x1, y1):
        return (x0 * u, y0 * u, x1 * u, y1 * u)

    if button:
        d.ellipse(box(7, 6, 57, 56), fill=color)
        d.ellipse(box(7.6, 6.6, 56.4, 55.4), outline=(255, 255, 255, 235), width=max(1, int(1.3 * u)))
        if pulse is not None:     # expanding glow ring while dictating
            r = 1 + (1 - pulse) * 3
            a = int(255 * (1 - 0.7 * pulse))
            d.ellipse(box(r, r - 1, 64 - r, 63 - r + 0), outline=(255, 138, 128, a), width=max(1, int(1.8 * u)))
    else:
        d.ellipse(box(2, 2, 62, 62), fill=color)

    w = int(3.2 * u)
    d.rounded_rectangle(box(25.5, 14.5, 38.5, 35.5), radius=6.5 * u, fill="white")          # capsule
    d.arc(box(19.5, 21.5, 44.5, 44.5), start=0, end=180, fill="white", width=w)             # cradle
    d.line(box(32, 44, 32, 50), fill="white", width=w)                                      # stem
    d.line(box(25.5, 50, 38.5, 50), fill="white", width=w)                                  # base
    for x in (25.5, 38.5):
        d.ellipse(box(x - 1.6, 50 - 1.6, x + 1.6, 50 + 1.6), fill="white")

    img = d_img
    if button:    # soft drop shadow so it reads on both light and dark backgrounds
        sh = Image.new("RGBA", (s, s), (0, 0, 0, 0))
        ImageDraw.Draw(sh).ellipse(box(8, 9, 56, 58), fill=(0, 0, 0, 120))
        sh = sh.filter(ImageFilter.GaussianBlur(2.2 * u))
        img = Image.alpha_composite(sh, d_img)

    img = img.resize((size, size), Image.LANCZOS)
    if key:
        bg = Image.new("RGBA", (size, size), KEY)
        img = Image.alpha_composite(bg, img)
    return img
