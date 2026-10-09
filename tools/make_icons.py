"""Generate the app icons (PNG) with only the Python standard library."""
import struct, zlib, os

def png(path, n):
    bg, white, yellow = (17, 17, 17), (255, 255, 255), (255, 210, 63)
    bars = [(30, 64, white), (46, 64, yellow), (62, 44, white)]  # (y, width, color) on a 100x100 grid
    rows = []
    for y in range(n):
        gy = y * 100.0 / n
        row = bytearray([0])
        for x in range(n):
            gx = x * 100.0 / n
            c = bg
            for by, bw, col in bars:
                if 18 <= gx < 18 + bw and by <= gy < by + 8:
                    c = col
            row += bytes(c)
        rows.append(bytes(row))
    raw = b"".join(rows)
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    data = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", n, n, 8, 2, 0, 0, 0)) \
        + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")
    with open(path, "wb") as f:
        f.write(data)

root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
for name, size in [("apple-touch-icon.png", 180), ("icon-192.png", 192), ("icon-512.png", 512)]:
    png(os.path.join(root, name), size)
    print("wrote", name)
