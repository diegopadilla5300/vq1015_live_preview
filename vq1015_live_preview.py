#!/usr/bin/env python3
"""
VQ1015 PC-camera ("PCC") viewer / grabber.

Live preview and JPEG frame capture. Connect the camera in PCC mode.

Setup:
  python -m pip install -r requirements.txt

Usage:
  python3 vq1015_live_preview.py                 # save 10 frames at 320x240 to ./vq_frames
  python3 vq1015_live_preview.py -n 50 --size 640
  python3 vq1015_live_preview.py --live -n 0     # continuous preview, without saving
"""
import argparse
from array import array
import os
import struct
import sys
import time

try:
    import usb.core
    import usb.util
except ImportError:
    sys.exit("pyusb is missing: pip install pyusb (and install libusb)")

VID, PID = 0x2770, 0x9080
EP_IN = 0x81
SIZES = {160: (0x0A, 160, 120), 320: (0x14, 320, 240), 640: (0x28, 640, 480)}
CMD_START = 0x40
CMD_STOP = 0xA0
SYNC = b"\xff\x00" * 32
HDR_LEN = 16

# JPEG quantization and Huffman tables. DQT0 omits the FFDB marker;
# DHT includes its FFC4 marker.
DQT0 = bytes.fromhex(
    "00840003020202020103020202030303030407040404040409060605070a090b0b0a090a0a0c0d110e0c0c100c0a0a0f"
    "140f1011121313130b0e151615121611121312010405050605060d07070d1b120f121b1b1b1b1b1b1b1b1b1b1b1b1b1b"
    "1b1b1b1b1b1b1b1b1b1b1b1b1b1b1b1b1b1b1b1b1b1b1b1b1b1b1b1b1b1b1b1b1b1b1b1b")
DHT = bytes.fromhex(
    "ffc401a20000010501010101010100000000000000000102030405060708090a0b100002010303020403050504040000"
    "017d01020300041105122131410613516107227114328191a1082342b1c11552d1f02433627282090a161718191a2526"
    "2728292a3435363738393a434445464748494a535455565758595a636465666768696a737475767778797a8384858687"
    "88898a92939495969798999aa2a3a4a5a6a7a8a9aab2b3b4b5b6b7b8b9bac2c3c4c5c6c7c8c9cad2d3d4d5d6d7d8d9da"
    "e1e2e3e4e5e6e7e8e9eaf1f2f3f4f5f6f7f8f9fa0100030101010101010101010000000000000102030405060708090a"
    "0b1100020102040403040705040400010277000102031104052131061241510761711322328108144291a1b1c1092333"
    "52f0156272d10a162434e125f11718191a262728292a35363738393a434445464748494a535455565758595a63646566"
    "6768696a737475767778797a82838485868788898a92939495969798999aa2a3a4a5a6a7a8a9aab2b3b4b5b6b7b8b9ba"
    "c2c3c4c5c6c7c8c9cad2d3d4d5d6d7d8d9dae2e3e4e5e6e7e8e9eaf2f3f4f5f6f7f8f9fa")
SOS = bytes.fromhex("ffda000c03010002110311003f00")


def jpeg_header(w, h, sampling, dqt, dht):
    sof = b"\xff\xc0\x00\x11\x08" + struct.pack(">HH", h, w) + \
          b"\x03\x01" + bytes([sampling]) + b"\x00\x02\x11\x01\x03\x11\x01"
    return b"\xff\xd8\xff\xdb" + dqt + dht + sof + SOS


def huffman_tables(dht):
    """Expand canonical JPEG DHT codes into 16-bit prefix lookup tables."""
    if dht[:2] != b"\xff\xc4" or len(dht) != int.from_bytes(dht[2:4], "big") + 2:
        raise ValueError("Invalid JPEG Huffman segment length")
    tables, pos = {}, 4
    while pos < len(dht):
        if pos + 17 > len(dht):
            raise ValueError("Truncated JPEG Huffman table")
        ident = dht[pos]
        counts = dht[pos + 1:pos + 17]
        pos += 17
        if pos + sum(counts) > len(dht) or ident in tables:
            raise ValueError("Invalid JPEG Huffman table")
        lookup = array("H", [0]) * 65536
        code = 0
        for bits, count in enumerate(counts, 1):
            if code + count > 1 << bits:
                raise ValueError("Oversubscribed JPEG Huffman table")
            width = 1 << (16 - bits)
            for _ in range(count):
                value = (bits << 8) | dht[pos]
                start = code * width
                lookup[start:start + width] = array("H", [value]) * width
                pos += 1
                code += 1
            code <<= 1
        tables[ident] = lookup
    if not all(key in tables for key in (0, 1, 0x10, 0x11)):
        raise ValueError("Missing camera JPEG Huffman tables")
    return tables


class ScanReader:
    """Read unstuffed baseline JPEG codes without reconstructing pixels."""

    def __init__(self, payload):
        self.data = payload + b"\x00\x00"
        self.limit = len(payload) * 8
        self.pos = 0

    def symbol(self, lookup):
        pos = self.pos
        if pos >= self.limit:
            raise ValueError("Truncated camera JPEG scan")
        i, offset = pos >> 3, pos & 7
        data = self.data
        prefix = ((data[i] << 16 | data[i + 1] << 8 | data[i + 2]) >> (8 - offset)) & 0xFFFF
        entry = lookup[prefix]
        if not entry:
            raise ValueError("Invalid camera JPEG Huffman code")
        self.skip(entry >> 8)
        return entry & 0xFF

    def skip(self, count):
        self.pos += count
        if self.pos > self.limit:
            raise ValueError("Truncated camera JPEG coefficient")


class Wrapper:
    """Wraps the camera's unstuffed 4:2:2 entropy data in a JPEG file."""

    def __init__(self, w, h, dqt, dht):
        self.w, self.h, self.dqt, self.dht = w, h, dqt, dht
        tables = huffman_tables(dht)
        # Each 16x8 MCU in 4:2:2 contains two Y blocks and one Cb/Cr block.
        self.blocks = ((tables[0], tables[0x10]),) * 2 + ((tables[1], tables[0x11]),) * 2
        self.mcus = ((w + 15) // 16) * ((h + 7) // 8)
        self.header = jpeg_header(w, h, 0x21, dqt, dht)

    def image_scan(self, payload):
        reader = ScanReader(payload)
        for _ in range(self.mcus):
            for dc, ac in self.blocks:
                category = reader.symbol(dc)
                if category > 11:
                    raise ValueError("Invalid baseline JPEG DC category")
                reader.skip(category)
                coefficient = 1
                while coefficient < 64:
                    symbol = reader.symbol(ac)
                    run, size = symbol >> 4, symbol & 15
                    if size == 0:
                        if run == 0:
                            break  # End of this 8x8 block.
                        if run != 15:
                            raise ValueError("Invalid baseline JPEG AC code")
                        coefficient += 16
                        if coefficient > 64:
                            raise ValueError("JPEG zero run exceeds block")
                    else:
                        coefficient += run
                        if size > 10 or coefficient >= 64:
                            raise ValueError("Invalid baseline JPEG AC coefficient")
                        reader.skip(size)
                        coefficient += 1
        end = (reader.pos + 7) // 8
        scan = bytearray(payload[:end])
        if reader.pos & 7:
            # JPEG requires unused bits in the final byte to be ones.
            scan[-1] |= (1 << (8 - (reader.pos & 7))) - 1
        return bytes(scan)

    def wrap(self, payload):
        body = self.image_scan(payload).replace(b"\xff", b"\xff\x00") + b"\xff\xd9"
        return self.header + body


class FrameParser:
    """Reassembles sync + header + payload from the bulk-IN byte stream."""

    def __init__(self):
        self.buf = bytearray()

    def feed(self, data):
        self.buf += data
        frames = []
        while True:
            i = self.buf.find(SYNC)
            if i < 0:
                del self.buf[:max(0, len(self.buf) - len(SYNC))]
                return frames
            if i:
                del self.buf[:i]
            if len(self.buf) < len(SYNC) + HDR_LEN:
                return frames
            hdr = bytes(self.buf[len(SYNC):len(SYNC) + HDR_LEN])
            n = hdr[0] | hdr[1] << 8 | hdr[2] << 16
            if n == 0 or n > 4 << 20:
                del self.buf[:2]          # not a real frame start, resync
                continue
            start = len(SYNC) + HDR_LEN
            if len(self.buf) < start + n:
                return frames
            frames.append((hdr, bytes(self.buf[start:start + n])))
            del self.buf[:start + n]


def describe(hdr):
    n = hdr[0] | hdr[1] << 8 | hdr[2] << 16
    return (f"len={n} exp={hdr[3]} luma={hdr[4]} RGB=({hdr[5]},{hdr[6]},{hdr[8]}) "
            f"gain={hdr[9]} wb=({hdr[10]},{hdr[11]},{hdr[12]}) sensor={hdr[13]}")


def open_camera():
    try:
        import libusb_package
        backend = libusb_package.get_libusb1_backend()
    except ImportError:
        backend = None
    dev = usb.core.find(idVendor=VID, idProduct=PID, backend=backend)
    if dev is None:
        other = usb.core.find(idVendor=VID, idProduct=0x915D, backend=backend)
        if other is not None:
            sys.exit("Camera is in mass-storage mode (USb). Unplug, hold SHUTTER, plug in again for PCC.")
        sys.exit("No camera at 2770:9080. Is it plugged in and showing PCC?")
    try:
        if dev.is_kernel_driver_active(0):
            dev.detach_kernel_driver(0)
    except (NotImplementedError, usb.core.USBError):
        pass
    try:
        dev.set_configuration()
    except usb.core.USBError as e:
        print(f"set_configuration: {e} (continuing)")
    usb.util.claim_interface(dev, 0)
    return dev


def vendor(dev, low, high=0):
    dev.ctrl_transfer(0x40, 0, (high << 8) | low, 0, None, timeout=5000)


def preview_open(cv2):
    """Pump window events and stop when the user closes it or presses Q/Esc."""
    if cv2.waitKey(1) & 0xFF in (27, ord("q"), ord("Q")):
        return False
    try:
        return cv2.getWindowProperty("VQ1015", cv2.WND_PROP_VISIBLE) >= 1
    except cv2.error:
        return False


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[1],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-n", "--frames", type=int, default=10, help="frames to save (0 = until Ctrl-C)")
    ap.add_argument("--size", type=int, choices=sorted(SIZES), default=320)
    ap.add_argument("-o", "--out", default="vq_frames")
    ap.add_argument("--live", action="store_true", help="show a live window (opencv-python)")
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args()

    code, w, h = SIZES[a.size]
    wrapper = Wrapper(w, h, DQT0, DHT)
    parser = FrameParser()
    saving = not a.live or a.frames != 0
    if saving:
        os.makedirs(a.out, exist_ok=True)

    cv2 = np = None
    if a.live:
        try:
            import cv2
            import numpy as np
        except ImportError:
            sys.exit("--live needs: pip install opencv-python numpy")

    dev = open_camera()
    got, idle, t0 = 0, 0, time.time()
    try:
        if a.live:
            cv2.namedWindow("VQ1015", cv2.WINDOW_NORMAL)
            cv2.resizeWindow("VQ1015", w * 2, h * 2)
        vendor(dev, CMD_START, code)
        print(f"streaming {w}x{h}, " +
              ("Q/Esc or close the preview to stop" if a.live else "Ctrl-C to stop"))
        while a.frames == 0 or got < a.frames:
            if a.live and not preview_open(cv2):
                break
            try:
                data = bytes(dev.read(EP_IN, 64 * 1024, timeout=2000))
                idle = 0
            except usb.core.USBTimeoutError:
                idle += 1
                if idle == 3:
                    print("no data for 6 s; try another --size or replug in PCC mode")
                continue
            for hdr, payload in parser.feed(data):
                got += 1
                jpg = wrapper.wrap(payload)
                stem = os.path.join(a.out, f"frame_{got:05d}")
                if a.live:
                    img = cv2.imdecode(np.frombuffer(jpg, np.uint8), cv2.IMREAD_COLOR)
                    if img is not None:
                        cv2.imshow("VQ1015", img)
                        if not preview_open(cv2):
                            raise KeyboardInterrupt
                    if a.frames:
                        open(stem + ".jpg", "wb").write(jpg)
                else:
                    open(stem + ".jpg", "wb").write(jpg)
                if a.verbose or got == 1:
                    print(f"frame {got}: {describe(hdr)}")
                if a.frames and got >= a.frames:
                    break
    except KeyboardInterrupt:
        pass
    finally:
        try:
            vendor(dev, CMD_STOP)
        except usb.core.USBError:
            pass
        usb.util.release_interface(dev, 0)
        usb.util.dispose_resources(dev)
        if a.live:
            cv2.destroyAllWindows()
    dt = time.time() - t0
    print(f"{got} frames in {dt:.1f} s ({got / dt if dt else 0:.1f} fps), " +
          (f"saved in {a.out}/" if saving else "preview only; no files saved"))


if __name__ == "__main__":
    main()
