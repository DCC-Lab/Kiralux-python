"""Parseur USBPcap autonome (pas de dependance).
Decode les control transfers (surtout vendor) et les transferts bulk d'un
capture USBPcap, pour cartographier le protocole de la camera.

Format: pcap classique, linktype 249 (DLT_USBPCAP).
En-tete paquet USBPCAP_BUFFER_PACKET_HEADER (27 o) + 1 o 'stage' si control.
"""
import struct
import sys

TRANSFER = {0: "ISO", 1: "INTR", 2: "CTRL", 3: "BULK"}
STAGE = {0: "SETUP", 1: "DATA", 2: "STATUS", 3: "COMPLETE"}

def req_type_str(bmRequestType):
    d = "IN" if (bmRequestType & 0x80) else "OUT"
    typ = {0: "STD", 1: "CLASS", 2: "VENDOR", 3: "RSVD"}[(bmRequestType >> 5) & 3]
    rec = {0: "DEV", 1: "INTF", 2: "EP", 3: "OTHER"}[bmRequestType & 0x1F if (bmRequestType & 0x1F) < 4 else 3]
    return f"{d}/{typ}/{rec}"

def main(path):
    with open(path, "rb") as f:
        data = f.read()

    magic = struct.unpack_from("<I", data, 0)[0]
    if magic == 0xa1b2c3d4:
        endian = "<"
    elif magic == 0xd4c3b2a1:
        endian = ">"
    else:
        print("magic inattendu", hex(magic)); return
    linktype = struct.unpack_from(endian + "I", data, 20)[0]
    print(f"# linktype={linktype} (249=USBPCAP)  taille={len(data)}")
    off = 24
    pkt = 0
    ctrl_count = bulk_count = 0
    # Pour recomposer setup+data des control transfers par irpId
    pending = {}
    while off + 16 <= len(data):
        ts_sec, ts_usec, incl, orig = struct.unpack_from(endian + "IIII", data, off)
        off += 16
        if off + incl > len(data):
            break
        p = data[off:off + incl]
        off += incl
        pkt += 1
        if len(p) < 27:
            continue
        headerLen = struct.unpack_from("<H", p, 0)[0]
        irpId = struct.unpack_from("<Q", p, 2)[0]
        status = struct.unpack_from("<I", p, 10)[0]
        function = struct.unpack_from("<H", p, 14)[0]
        info = p[16]
        bus = struct.unpack_from("<H", p, 17)[0]
        device = struct.unpack_from("<H", p, 19)[0]
        endpoint = p[21]
        transfer = p[22]
        dataLength = struct.unpack_from("<I", p, 23)[0]
        payload = p[headerLen:headerLen + dataLength]
        tdir = "IN" if (endpoint & 0x80) else "OUT"
        ep = endpoint & 0x7F

        if transfer == 2:  # control
            stage = p[27] if headerLen >= 28 else 0xFF
            if stage == 0 and len(payload) >= 8:  # SETUP
                bmRequestType, bRequest, wValue, wIndex, wLength = struct.unpack_from("<BBHHH", payload, 0)
                ctrl_count += 1
                print(f"[{pkt}] CTRL SETUP dev={device} {req_type_str(bmRequestType)} "
                      f"bRequest=0x{bRequest:02x} wValue=0x{wValue:04x} wIndex=0x{wIndex:04x} wLength={wLength}")
                pending[irpId] = (bmRequestType, bRequest, wValue, wIndex, wLength)
            elif stage == 1:  # DATA stage
                if payload:
                    hexd = payload[:64].hex()
                    print(f"      DATA dev={device} {tdir} len={len(payload)} : {hexd}"
                          + (" ..." if len(payload) > 64 else ""))
        elif transfer == 3:  # bulk
            if dataLength > 0:
                bulk_count += 1
                # pour les gros transferts (frame), payload tronque par snaplen
                head = payload[:32].hex() if payload else ""
                print(f"[{pkt}] BULK dev={device} ep=0x{endpoint:02x} {tdir} dataLength={dataLength} head={head}")
        elif transfer == 1:  # interrupt
            if dataLength > 0:
                print(f"[{pkt}] INTR dev={device} ep=0x{endpoint:02x} {tdir} len={dataLength} {payload[:16].hex()}")

    print(f"\n# total paquets={pkt} control-setup={ctrl_count} bulk={bulk_count}")

if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else r"C:\Mac\Home\ThorImageRE\captures\cam_session.pcap")
