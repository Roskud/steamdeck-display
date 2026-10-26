import os
from PIL import Image, ImageDraw

def create_deckdisplay_icon(output_ico_path="windows-host/icon.ico", output_png_path="windows-host/icon.png"):
    size = 256
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # 1. Background monitor body (dark sleek rounded rectangle)
    # Outer glow / accent border
    margin = 12
    draw.rounded_rectangle(
        [margin - 2, margin - 2, size - margin + 2, size - margin + 2],
        radius=36,
        fill=(10, 15, 24, 255),
        outline=(26, 159, 255, 255),
        width=4
    )

    # Internal screen bezel
    screen_left = margin + 18
    screen_top = margin + 22
    screen_right = size - margin - 18
    screen_bottom = size - margin - 38
    draw.rounded_rectangle(
        [screen_left, screen_top, screen_right, screen_bottom],
        radius=18,
        fill=(18, 26, 38, 255),
        outline=(0, 210, 255, 180),
        width=2
    )

    # Screen display content: gradient / tech grid
    inner_l = screen_left + 8
    inner_t = screen_top + 8
    inner_r = screen_right - 8
    inner_b = screen_bottom - 8
    draw.rounded_rectangle(
        [inner_l, inner_t, inner_r, inner_b],
        radius=10,
        fill=(13, 20, 32, 255)
    )

    # Controller accents on the screen:
    # Left D-Pad (cross) in vibrant cyan
    cx_pad = inner_l + 32
    cy_pad = (inner_t + inner_b) // 2
    pad_w = 8
    pad_len = 18
    # Vertical bar
    draw.rounded_rectangle([cx_pad - pad_w//2, cy_pad - pad_len, cx_pad + pad_w//2, cy_pad + pad_len], radius=3, fill=(0, 210, 255, 255))
    # Horizontal bar
    draw.rounded_rectangle([cx_pad - pad_len, cy_pad - pad_w//2, cx_pad + pad_len, cy_pad + pad_w//2], radius=3, fill=(0, 210, 255, 255))

    # Right Action Buttons (4 dots: Y, B, A, X) in Steam colors
    cx_btn = inner_r - 32
    cy_btn = (inner_t + inner_b) // 2
    btn_r = 5
    d = 14
    # Top (Yellowish)
    draw.ellipse([cx_btn - btn_r, cy_btn - d - btn_r, cx_btn + btn_r, cy_btn - d + btn_r], fill=(255, 215, 0, 255))
    # Right (Red)
    draw.ellipse([cx_btn + d - btn_r, cy_btn - btn_r, cx_btn + d + btn_r, cy_btn + btn_r], fill=(255, 75, 75, 255))
    # Bottom (Green)
    draw.ellipse([cx_btn - btn_r, cy_btn + d - btn_r, cx_btn + btn_r, cy_btn + d + btn_r], fill=(0, 230, 118, 255))
    # Left (Blue)
    draw.ellipse([cx_btn - d - btn_r, cy_btn - btn_r, cx_btn - d + btn_r, cy_btn + btn_r], fill=(30, 144, 255, 255))

    # Center: Fast Video Stream Beams / Lightning / Monitor Display Symbol
    center_x = (inner_l + inner_r) // 2
    center_y = (inner_t + inner_b) // 2

    # Draw Wi-Fi / Stream Arcs / Lightning Symbol
    # Glowing Play / Fast-forward arrow
    points = [
        (center_x - 16, center_y - 20),
        (center_x + 16, center_y),
        (center_x - 16, center_y + 20)
    ]
    draw.polygon(points, fill=(0, 220, 255, 240))
    # Outline play arrow
    draw.line(points + [points[0]], fill=(255, 255, 255, 255), width=2)

    # Monitor Stand Base at bottom
    base_top = screen_bottom + 6
    base_bottom = size - margin - 8
    base_left = size // 2 - 28
    base_right = size // 2 + 28
    # Stem
    draw.rectangle([size//2 - 6, base_top, size//2 + 6, base_bottom - 4], fill=(70, 85, 105, 255))
    # Foot
    draw.rounded_rectangle([base_left, base_bottom - 6, base_right, base_bottom], radius=3, fill=(100, 120, 145, 255))

    # Save PNG
    os.makedirs(os.path.dirname(output_png_path), exist_ok=True)
    img.save(output_png_path, format="PNG")
    print(f"Saved PNG to {output_png_path}")

    # Save ICO with multiple standard Windows sizes
    sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    img.save(output_ico_path, format="ICO", sizes=sizes)
    print(f"Saved multi-res ICO to {output_ico_path}")

if __name__ == "__main__":
    create_deckdisplay_icon()
