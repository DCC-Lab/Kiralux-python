Get-CimInstance Win32_Process -Filter "Name='explorer.exe'" | ForEach-Object {
  $o = Invoke-CimMethod -InputObject $_ -MethodName GetOwner
  $si = (Get-Process -Id $_.ProcessId -ErrorAction SilentlyContinue).SessionId
  "explorer PID=$($_.ProcessId) Session=$si User=$($o.Domain)\$($o.User)"
}
