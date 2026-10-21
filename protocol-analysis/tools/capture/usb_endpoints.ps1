# Endpoints + confirmation driver + USBPcap
"=== USBPcap present ? ==="
Get-ChildItem "C:\Program Files\USBPcap","C:\Program Files (x86)\USBPcap" -ErrorAction SilentlyContinue | Select-Object FullName
"--- USBPcapCMD ---"
(Get-ChildItem C:\ -Recurse -Filter USBPcapCMD.exe -ErrorAction SilentlyContinue | Select-Object -First 1).FullName

"`n=== Config/endpoints via Cypress CYUSB (can pyusb read the descriptors?) ==="
& "C:\Program Files\Python313\python.exe" -c @"
import usb.core, usb.util
devs = list(usb.core.find(find_all=True, idVendor=0x1313))
if not devs:
    print('pyusb: no 1313 device visible via libusb backend (normal if bound to CYUSB3)')
for d in devs:
    print('dev', hex(d.idVendor), hex(d.idProduct))
    try:
        for cfg in d:
            for intf in cfg:
                print('  intf', intf.bInterfaceNumber)
                for ep in intf:
                    print('    ep 0x%02x type=%d maxpkt=%d' % (ep.bEndpointAddress, usb.util.endpoint_type(ep.bmAttributes), ep.wMaxPacketSize))
    except Exception as e:
        print('  descr err:', e)
"@ 2>&1
