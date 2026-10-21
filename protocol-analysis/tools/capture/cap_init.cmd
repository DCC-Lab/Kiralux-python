@echo off
rem Initialise la cle registre NonStandardHWIDs requise pour capture USB 3.0
"C:\Program Files\USBPcap\USBPcapCMD.exe" -I
echo INIT_EXIT=%ERRORLEVEL%
