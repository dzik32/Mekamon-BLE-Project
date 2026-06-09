"""Generate assets/icon.ico (a little quadruped-robot glyph). Run: python tools/make_icon.py"""
import os

from PIL import Image, ImageDraw

S = 1024
img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(img)

navy = (28, 28, 38, 255)
blue = (42, 130, 218, 255)
cyan = (90, 220, 255, 255)
steel = (120, 140, 170, 255)
white = (245, 245, 255, 255)

# rounded-square background
d.rounded_rectangle([40, 40, S - 40, S - 40], radius=180, fill=navy)

# four legs
for cx in (366, 470, 554, 658):
    d.rounded_rectangle([cx - 30, 590, cx + 30, 780], radius=24, fill=steel)

# body
d.rounded_rectangle([300, 250, 724, 620], radius=90, fill=blue)

# eyes
d.ellipse([372, 360, 468, 456], fill=white)
d.ellipse([556, 360, 652, 456], fill=white)
d.ellipse([404, 392, 452, 440], fill=navy)
d.ellipse([588, 392, 636, 440], fill=navy)

# antenna
d.line([512, 250, 512, 165], fill=cyan, width=22)
d.ellipse([484, 120, 540, 176], fill=cyan)

out_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets")
os.makedirs(out_dir, exist_ok=True)
path = os.path.join(out_dir, "icon.ico")
img = img.resize((256, 256), Image.LANCZOS)
img.save(path, sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print("wrote", path)
