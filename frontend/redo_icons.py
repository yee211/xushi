# -*- coding: utf-8 -*-
"""推倒重做：白底图标（单张 PNG，无自适应层）+ 白底开屏。

设计元素全部取自 public/app-icon.png（原始透明底图形），品牌色：
- 图形深蓝 #0E1520（源图自带）
- 点缀金 #C9A063（源图自带）
"""
from PIL import Image, ImageDraw, ImageFont
import os

ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(ROOT)

NAVY = (14, 21, 32, 255)
GOLD = (201, 160, 99, 255)
WHITE = (255, 255, 255, 255)

src = Image.open("public/app-icon.png")
# 阈值裁剪：源图上方有一圈近不可见的低透明度像素，直接 getbbox 会把包围盒撑大
_tight = src.getchannel("A").point(lambda v: 255 if v > 24 else 0).getbbox()
glyph = src.crop(_tight)  # 透明底原始图形（真实边界）
gw, gh = glyph.size
ratio = gw / gh


def on_white(size, glyph_ratio):
    canvas = Image.new("RGBA", (size, size), WHITE)
    g_h = int(size * glyph_ratio)
    g = glyph.resize((int(g_h * ratio), g_h), Image.LANCZOS)
    canvas.alpha_composite(g, ((size - g.width) // 2, (size - g_h) // 2))
    return canvas


def circle(img):
    mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(mask).ellipse((0, 0, img.size[0], img.size[1]), fill=255)
    img.putalpha(mask)
    return img


# ---- 桌面图标：白底单张 PNG（无自适应层，任何 ROM 所见即所得） ----
densities = {"mdpi": 108, "hdpi": 162, "xhdpi": 216, "xxhdpi": 324, "xxxhdpi": 432}
for dpi, size in densities.items():
    d = f"android/app/src/main/res/mipmap-{dpi}"
    on_white(size, 0.88).convert("RGB").save(f"{d}/ic_launcher.png")
    circle(on_white(size, 0.74)).save(f"{d}/ic_launcher_round.png")

# ---- 开屏：白底 + 图形 + “序时” + 金色短横线 ----
S = 512
splash = Image.new("RGBA", (S, S), WHITE)
g_h = int(S * 0.40)
g = glyph.resize((int(g_h * ratio), g_h), Image.LANCZOS)
gx, gy = (S - g.width) // 2, int(S * 0.16)
splash.alpha_composite(g, (gx, gy))
font = None
for fp in (r"C:\Windows\Fonts\msyhbd.ttc", r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\simhei.ttf"):
    if os.path.exists(fp):
        font = ImageFont.truetype(fp, 64)
        break
text = "序时"
if font:
    tb = ImageDraw.Draw(splash).textbbox((0, 0), text, font=font)
    tw, th = tb[2] - tb[0], tb[3] - tb[1]
    tx, ty = (S - tw) // 2 - tb[0], gy + g_h + int(S * 0.055) - tb[1]
    ImageDraw.Draw(splash).text((tx, ty), text, font=font, fill=NAVY)
    dash_y = ty + th + int(S * 0.035)
    ImageDraw.Draw(splash).rounded_rectangle(
        [(S - 72) // 2, dash_y, (S + 72) // 2, dash_y + 8], radius=4, fill=GOLD)
splash.convert("RGB").save("android/app/src/main/res/drawable-nodpi/splash_icon.png")
print("done: icons + splash regenerated")
