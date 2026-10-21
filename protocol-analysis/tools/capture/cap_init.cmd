@echo off
rem Initializes the NonStandardHWIDs registry key required for USB 3.0 capture
"C:\Program Files\USBPcap\USBPcapCMD.exe" -I
echo INIT_EXIT=%ERRORLEVEL%
