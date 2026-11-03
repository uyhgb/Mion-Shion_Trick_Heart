"""Self-test for pv_boil.py using a synthetic drawing (no third-party art needed).

Run:  python tools/test_pv_boil.py
"""
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

import pv_boil as pb


def synth() -> np.ndarray:
    im = Image.new("RGBA", (400, 400), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.ellipse((100, 60, 300, 280), fill=(250, 220, 205, 255), outline=(15, 15, 15, 255), width=4)
    d.ellipse((150, 150, 185, 195), fill=(0, 63, 85, 255), outline=(15, 15, 15, 255), width=3)
    d.ellipse((215, 150, 250, 195), fill=(0, 63, 85, 255), outline=(15, 15, 15, 255), width=3)
    d.rectangle((120, 280, 280, 399), fill=(20, 20, 20, 255))          # broad black fill
    for y in range(290, 399, 2):                                         # soft gradient
        d.line((140, y, 260, y), fill=(int(150 + (y - 290) / 2), 40, 60, 255))
    d.ellipse((120, 200, 150, 215), fill=(240, 160, 170, 255))          # blush accent
    return np.array(im)


def main():
    img = synth()
    a1 = pb.make_variants(img, "selftest", ["A", "B"], {}, faces=[[100, 60, 300, 280]])
    a2 = pb.make_variants(img, "selftest", ["A", "B"], {}, faces=[[100, 60, 300, 280]])
    assert all(np.array_equal(a1[k], a2[k]) for k in "AB"), "not deterministic"
    assert not np.array_equal(a1["A"], a1["B"]), "phases identical"
    ink = pb.line_mask(img, pb.DEFAULTS["line"])
    assert not ink[330, 200], "broad black fill must not count as a stroke"
    assert not ink[172, 167], "dark iris must not count as a stroke"
    blush = a1["A"][207, 135, :3].astype(int)
    assert blush[0] > 200 and blush[1] < 200, f"blush turned muddy: {blush}"
    with tempfile.TemporaryDirectory() as t:
        for k, v in a1.items():
            Image.fromarray(v).save(Path(t) / f"{k}.png")
    print("pv_boil self-test OK")


if __name__ == "__main__":
    main()
