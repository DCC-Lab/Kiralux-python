"""Extrait et decode le descripteur de configuration USB depuis la capture
(reponse au GET_DESCRIPTOR config), pour connaitre interface + endpoints exacts.
"""
import struct, sys

def main(path):
    data = open(path, "rb").read()
    off = 24
    cfg = None
    while off + 16 <= len(data):
        _, _, incl, _ = struct.unpack_from("<IIII", data, off); off += 16
        if off + incl > len(data): break
        p = data[off:off+incl]; off += incl
        if len(p) < 27: continue
        headerLen = struct.unpack_from("<H", p, 0)[0]
        transfer = p[22]; dataLength = struct.unpack_from("<I", p, 23)[0]
        payload = p[headerLen:headerLen+dataLength]
        # Un descripteur de config commence par bLength=9, bDescriptorType=2
        if transfer == 2 and len(payload) >= 9 and payload[1] == 2 and payload[0] == 9:
            total = struct.unpack_from("<H", payload, 2)[0]
            if len(payload) >= total and total > 9:
                cfg = payload[:total]; break
    if not cfg:
        print("descripteur de config non trouve dans la capture"); return
    print(f"# config descriptor {len(cfg)} octets: {cfg.hex()}")
    i = 0
    while i < len(cfg):
        blen = cfg[i]; btype = cfg[i+1]
        if blen == 0: break
        d = cfg[i:i+blen]
        if btype == 2:
            numIf = d[4]
            print(f"CONFIG: wTotalLength={struct.unpack_from('<H',d,2)[0]} bNumInterfaces={numIf} bConfigValue={d[5]}")
        elif btype == 4:
            print(f"  INTERFACE #{d[2]} alt={d[3]} nEndpoints={d[4]} class={d[5]:#x} subclass={d[6]:#x} proto={d[7]:#x}")
        elif btype == 5:
            addr = d[2]; attr = d[3]; mps = struct.unpack_from("<H", d, 4)[0]
            ttype = {0:"CTRL",1:"ISO",2:"BULK",3:"INTR"}[attr & 3]
            tdir = "IN" if (addr & 0x80) else "OUT"
            print(f"    ENDPOINT 0x{addr:02x} {tdir} {ttype} maxpkt={mps} interval={d[6]}")
        elif btype == 0x0b:
            print(f"  IAD firstIf={d[2]} count={d[3]} class={d[4]:#x}")
        else:
            print(f"  desc type={btype:#x} len={blen}: {d.hex()}")
        i += blen

if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else r"C:\Mac\Home\ThorImageRE\captures\cam_session.pcap")
