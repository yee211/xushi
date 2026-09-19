import os

from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_IMAGE = r"C:/Users/1/.gemini/antigravity/brain/4c87f46a-49aa-432c-bba8-d37f2dac9e55/.user_uploaded/media_1789051182312.png"
RES_DIR = os.path.join(ROOT, "frontend", "android", "app", "src", "main", "res")
PUB_DIR = os.path.join(ROOT, "frontend", "public")

def create_icons():
    print(f"Loading source image: {SRC_IMAGE}")
    src = Image.open(SRC_IMAGE).convert("RGBA")
    w, h = src.size

    # The user uploaded image has the icon centered at roughly (511, 276)
    cx, cy = 511, 276
    half = 198
    crop = src.crop((cx - half, cy - half, cx + half, cy + half))

    # Base master 512x512 icon
    master_512 = crop.resize((512, 512), Image.Resampling.LANCZOS)

    # 1. Master rounded icon (squircle radius ~ 110 at 512px)
    scale = 4
    mask_rounded_hi = Image.new("L", (512 * scale, 512 * scale), 0)
    draw_r = ImageDraw.Draw(mask_rounded_hi)
    draw_r.rounded_rectangle([0, 0, 512 * scale, 512 * scale], radius=110 * scale, fill=255)
    mask_rounded = mask_rounded_hi.resize((512, 512), Image.Resampling.LANCZOS)

    icon_rounded = master_512.copy()
    icon_rounded.putalpha(mask_rounded)

    # 2. Master circular icon (for round launcher)
    mask_circle_hi = Image.new("L", (512 * scale, 512 * scale), 0)
    draw_c = ImageDraw.Draw(mask_circle_hi)
    draw_c.ellipse([0, 0, 512 * scale, 512 * scale], fill=255)
    mask_circle = mask_circle_hi.resize((512, 512), Image.Resampling.LANCZOS)

    icon_circle = master_512.copy()
    icon_circle.putalpha(mask_circle)

    # 3. Master adaptive foreground (108x108 spec: safe zone is centered 72x72, i.e. 66.6% scale)
    fg_canvas = Image.new("RGBA", (512, 512), (0, 0, 0, 0))
    # resize rounded icon to 370x370 (~72%) and center
    inner_size = 370
    inner_icon = icon_rounded.resize((inner_size, inner_size), Image.Resampling.LANCZOS)
    offset = (512 - inner_size) // 2
    fg_canvas.paste(inner_icon, (offset, offset), inner_icon)

    # Save to Web / PWA public directory
    os.makedirs(PUB_DIR, exist_ok=True)
    master_512.convert("RGB").save(os.path.join(PUB_DIR, "xushi-icon.jpg"), quality=95)
    icon_rounded.save(os.path.join(PUB_DIR, "pwa-512x512.png"))
    icon_rounded.save(os.path.join(PUB_DIR, "pwa-maskable-512x512.png"))

    icon_rounded.resize((192, 192), Image.Resampling.LANCZOS).save(os.path.join(PUB_DIR, "pwa-192x192.png"))
    icon_rounded.resize((192, 192), Image.Resampling.LANCZOS).save(os.path.join(PUB_DIR, "pwa-maskable-192x192.png"))
    icon_rounded.resize((180, 180), Image.Resampling.LANCZOS).save(os.path.join(PUB_DIR, "apple-touch-icon.png"))
    icon_rounded.resize((180, 180), Image.Resampling.LANCZOS).save(os.path.join(PUB_DIR, "apple-touch-icon-precomposed.png"))
    icon_rounded.resize((64, 64), Image.Resampling.LANCZOS).save(os.path.join(PUB_DIR, "favicon.png"))
    icon_rounded.resize((32, 32), Image.Resampling.LANCZOS).save(os.path.join(PUB_DIR, "favicon.ico"))
    print("Web/PWA icons updated.")

    # Android mipmap densities:
    densities = {
        "mipmap-mdpi": (48, 108),
        "mipmap-hdpi": (72, 162),
        "mipmap-xhdpi": (96, 216),
        "mipmap-xxhdpi": (144, 324),
        "mipmap-xxxhdpi": (192, 432),
    }

    for folder, (icon_sz, fg_sz) in densities.items():
        folder_path = os.path.join(RES_DIR, folder)
        os.makedirs(folder_path, exist_ok=True)

        # ic_launcher.png (squircle)
        icon_rounded.resize((icon_sz, icon_sz), Image.Resampling.LANCZOS).save(os.path.join(folder_path, "ic_launcher.png"))
        # ic_launcher_round.png (circle)
        icon_circle.resize((icon_sz, icon_sz), Image.Resampling.LANCZOS).save(os.path.join(folder_path, "ic_launcher_round.png"))
        # ic_launcher_foreground.png (adaptive)
        fg_canvas.resize((fg_sz, fg_sz), Image.Resampling.LANCZOS).save(os.path.join(folder_path, "ic_launcher_foreground.png"))
        print(f"Updated {folder}: icon={icon_sz}px, fg={fg_sz}px")

    # Update ic_launcher_background.xml
    bg_xml_path = os.path.join(RES_DIR, "values", "ic_launcher_background.xml")
    with open(bg_xml_path, "w", encoding="utf-8") as f:
        f.write("""<?xml version="1.0" encoding="utf-8"?>
<resources>
    <color name="ic_launcher_background">#1c2432</color>
</resources>
""")
    print("Updated ic_launcher_background.xml to #1c2432.")

if __name__ == "__main__":
    create_icons()
