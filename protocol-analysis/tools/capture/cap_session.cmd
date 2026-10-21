@echo off
set U="C:\Program Files\USBPcap\USBPcapCMD.exe"
set OUT=C:\Mac\Home\ThorImageRE\captures\cam_session.pcap
if not exist C:\Mac\Home\ThorImageRE\captures mkdir C:\Mac\Home\ThorImageRE\captures
del /q "%OUT%" 2>nul

rem Capture USBPcap3, camera seule (addr 2), descripteurs injectes, payload tronque a 2048o
start "usbpcap" /b %U% -d \\.\USBPcap3 -o "%OUT%" --devices 2 --inject-descriptors -s 2048
rem laisser le capteur demarrer (~2s)
ping -n 3 127.0.0.1 >nul

rem session camera complete
"C:\Program Files\Python313\python.exe" "C:\Mac\Home\ThorImageRE\tools\tsi_grab_frame.py"

ping -n 2 127.0.0.1 >nul
taskkill /im USBPcapCMD.exe /f >nul 2>&1
echo CAPTURE_DONE
