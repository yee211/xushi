# -*- coding: utf-8 -*-
"""从 public/app-icon.png（透明底高清源图）重新生成全套白底图标。"""
from PIL import Image, ImageDraw
import os

ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(ROOT)

src = Image.open("public/app-icon.png")
glyph = src.crop(src.getbbox())  # 透明底图形
gw, gh = glyph.size
ratio = gw / gh  # 宽高比

WHITE = (255, 255, 255, 255)


def compose(size, glyph_ratio, circle=False):
    """白底画布 + 居中图形；circle=True 时裁成圆形（用于 round 图标）。"""
    canvas = Image.new("RGBA", (size, size), WHITE)
    g_h = int(size * glyph_ratio)
    g_w = int(g_h * ratio)
    if g_w > size * 0.9:  # 防止极扁图形溢出
        g_w = int(size * 0.9)
        g_h = int(g_w / ratio)
    g = glyph.resize((g_w, g_h), Image.LANCZOS)
    canvas.alpha_composite(g, ((size - g_w) // 2, (size - g_h) // 2))
    if circle:
        mask = Image.new("L", (size, size), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, size, size), fill=255)
        canvas.putalpha(mask)
    return canvas


def save_rgb(img, path):
    img.convert("RGB").save(path)


# ---- Android legacy 启动图标（白底不透明，尺寸与现有一致） ----
densities = {"mdpi": 108, "hdpi": 162, "xhdpi": 216, "xxhdpi": 324, "xxxhdpi": 432}
for dpi, size in densities.items():
    d = f"android/app/src/main/res/mipmap-{dpi}"
    save_rgb(compose(size, 0.70), f"{d}/ic_launcher.png")
    compose(size, 0.62, circle=True).save(f"{d}/ic_launcher_round.png")

# ---- Web favicon / PWA（白底） ----
save_rgb(compose(256, 0.78), "public/favicon.png")
Image.open("public/favicon.png").save("public/favicon.ico",
                                     sizes=[(16, 16), (32, 32), (48, 48)])
for name, size, gr in [("apple-touch-icon.png", 180, 0.78),
                       ("apple-touch-icon-precomposed.png", 180, 0.78),
                       ("pwa-192x192.png", 192, 0.76),
                       ("pwa-512x512.png", 512, 0.76)]:
    save_rgb(compose(size, gr), f"public/{name}")
for size in (192, 512):
    compose(size, 0.58).save(f"public/pwa-maskable-{size}x{size}.png")

print("done")
