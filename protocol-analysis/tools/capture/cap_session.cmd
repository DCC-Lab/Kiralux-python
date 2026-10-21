@echo off
set U="C:\Program Files\USBPcap\USBPcapCMD.exe"
set OUT=C:\Mac\Home\ThorImageRE\captures\cam_session.pcap
if not exist C:\Mac\Home\ThorImageRE\captures mkdir C:\Mac\Home\ThorImageRE\captures
del /q "%OUT%" 2>nul

rem Capture USBPcap3, camera only (addr 2), injected descriptors, payload truncated to 2048B
start "usbpcap" /b %U% -d \\.\USBPcap3 -o "%OUT%" --devices 2 --inject-descriptors -s 2048
rem let the sensor start up (~2s)
ping -n 3 127.0.0.1 >nul

rem complete camera session
"C:\Program Files\Python313\python.exe" "C:\Mac\Home\ThorImageRE\tools\tsi_grab_frame.py"

ping -n 2 127.0.0.1 >nul
taskkill /im USBPcapCMD.exe /f >nul 2>&1
echo CAPTURE_DONE
