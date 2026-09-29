"""Export the main-page identity using the bundled Nouveau IBM typeface."""
from pathlib import Path
import base64
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
FONT = HERE.parents[1] / 'anybandui/fonts/Nouveau_IBM.ttf'
W, H = 1280, 400
GREEN, WHITE, BORDER, BG = '#80b892', '#d9e3db', '#495b57', '#07100f'
font = ImageFont.truetype(str(FONT), 160)
markfont = ImageFont.truetype(str(FONT), 168)
svg = []
im = Image.new('RGBA', (W, H))
d = ImageDraw.Draw(im)

def rect(box, color, width=2):
    d.rectangle(box, outline=color, width=width)
    x, y, x2, y2 = box
    svg.append(f'<rect x="{x}" y="{y}" width="{x2-x}" height="{y2-y}" fill="none" stroke="{color}" stroke-width="{width}"/>')

def text(x, baseline, value, face, color):
    d.text((x, baseline), value, font=face, fill=color, anchor='ls')
    svg.append(f'<text x="{x}" y="{baseline}" font-family="NouveauLogo" font-size="{face.size}" fill="{color}">{value}</text>')

for radius in (64, 82, 100, 118):
    rect((190-radius, 180-radius, 190+radius, 180+radius), BORDER)
box = markfont.getbbox('@', anchor='ls')
text(190-(box[0]+box[2])/2, 180-(box[1]+box[3])/2, '@', markfont, GREEN)
box = font.getbbox('AnybandUI', anchor='ls')
baseline = 180-(box[1]+box[3])/2
text(384, baseline, 'Anyband', font, WHITE)
text(384+font.getlength('Anyband'), baseline, 'UI', font, GREEN)
d.line((72, 342, 1208, 342), fill=BORDER, width=2)
d.line((72, 342, 280, 342), fill=GREEN, width=4)
svg.append(f'<path d="M72 342H1208" stroke="{BORDER}" stroke-width="2"/><path d="M72 342H280" stroke="{GREEN}" stroke-width="4"/>')
for x in (1184, 1196, 1208):
    d.line((x, 332, x, 344), fill=GREEN, width=2)
    svg.append(f'<path d="M{x} 332V344" stroke="{GREEN}" stroke-width="2"/>')

im.save(HERE/'anybandui-logo-transparent.png')
background = Image.new('RGBA', im.size, BG)
background.alpha_composite(im)
background.convert('RGB').save(HERE/'anybandui-logo-dark.png')
encoded = base64.b64encode(FONT.read_bytes()).decode()
(HERE/'anybandui-logo.svg').write_text(
    f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" aria-label="AnybandUI">'
    f'<defs><style>@font-face{{font-family:NouveauLogo;src:url(data:font/ttf;base64,{encoded}) format("truetype");}}</style></defs>'
    + ''.join(svg) + '</svg>', encoding='utf-8')
