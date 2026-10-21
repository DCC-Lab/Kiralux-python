@echo off
set U="C:\Program Files\USBPcap\USBPcapCMD.exe"
echo ===== USBPcap1 ===== > C:\Mac\Home\ThorImageRE\tools\usbpcap_devs.txt
%U% --extcap-interface \\.\USBPcap1 --extcap-config >> C:\Mac\Home\ThorImageRE\tools\usbpcap_devs.txt 2>&1
echo ===== USBPcap2 ===== >> C:\Mac\Home\ThorImageRE\tools\usbpcap_devs.txt
%U% --extcap-interface \\.\USBPcap2 --extcap-config >> C:\Mac\Home\ThorImageRE\tools\usbpcap_devs.txt 2>&1
echo ===== USBPcap3 ===== >> C:\Mac\Home\ThorImageRE\tools\usbpcap_devs.txt
%U% --extcap-interface \\.\USBPcap3 --extcap-config >> C:\Mac\Home\ThorImageRE\tools\usbpcap_devs.txt 2>&1
echo DONE
