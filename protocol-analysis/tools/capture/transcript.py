"""ASCII transcript of the camera bulk conversation (EP2 OUT / EP82 IN).
Shows the commands and responses in clear, and spots the image transfer.
"""
import struct, sys

def main(path):
    data = open(path, "rb").read()
    endian = "<"
    off = 24
    pkt = 0
    while off + 16 <= len(data):
        _, _, incl, _ = struct.unpack_from(endian + "IIII", data, off); off += 16
        if off + incl > len(data): break
        p = data[off:off+incl]; off += incl; pkt += 1
        if len(p) < 27: continue
        headerLen = struct.unpack_from("<H", p, 0)[0]
        device = struct.unpack_from("<H", p, 19)[0]
        endpoint = p[21]; transfer = p[22]
        dataLength = struct.unpack_from("<I", p, 23)[0]
        payload = p[headerLen:headerLen+dataLength]
        if transfer != 3:  # bulk only
            continue
        tdir = "IN " if (endpoint & 0x80) else "OUT"
        # large transfer = image
        if dataLength > 4096:
            print(f"[{pkt}] <<< IMAGE/DATA {tdir} ep=0x{endpoint:02x} dataLength={dataLength} bytes >>>")
            continue
        txt = payload.split(b"\x00")[0].decode("latin1", "replace").strip()
        arrow = ">>" if tdir == "OUT" else "  <<"
        if txt:
            print(f"[{pkt}] {arrow} {tdir} [{dataLength}] {txt!r}")

if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else r"C:\Mac\Home\ThorImageRE\captures\cam_session.pcap")
