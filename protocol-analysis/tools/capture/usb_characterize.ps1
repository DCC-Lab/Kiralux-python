# Phase 1: characterization of the USB camera device (ThorLabs VID = 1313)
"=== PnP USB devices ThorLabs / camera ==="
Get-PnpDevice -PresentOnly | Where-Object {
  $_.InstanceId -match "VID_1313" -or $_.FriendlyName -match "Thor|Kiralux|Zelux|CS505|Scientific|Camera"
} | ForEach-Object {
  $svc = (Get-PnpDeviceProperty -InstanceId $_.InstanceId -KeyName 'DEVPKEY_Device_Service' -ErrorAction SilentlyContinue).Data
  "{0,-10} {1,-45} svc={2}" -f $_.Status, $_.InstanceId, $svc
}

"`n=== Hardware IDs (VID/PID) ==="
Get-PnpDevice -PresentOnly | Where-Object { $_.InstanceId -match "VID_1313" } | ForEach-Object {
  $hw = (Get-PnpDeviceProperty -InstanceId $_.InstanceId -KeyName 'DEVPKEY_Device_HardwareIds' -ErrorAction SilentlyContinue).Data
  "$($_.InstanceId)`n   HWID: $hw"
}

"`n=== Potential firmware files in Bin (img/bin/fw/spi/fx3) ==="
Get-ChildItem "C:\Program Files\Thorlabs\ThorImageCAM\Bin" -Recurse -Include *.img,*.bin,*.fw,*.spi,*.rbf,*.fx3,*.cyacd -ErrorAction SilentlyContinue |
  Select-Object FullName, Length

"`n=== pyusb / libusb available? ==="
& "C:\Program Files\Python313\python.exe" -c "import usb.core, usb.backend; print('pyusb OK', usb.__version__ if hasattr(usb,'__version__') else '')" 2>&1
