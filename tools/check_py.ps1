Get-Process pythonw -ErrorAction SilentlyContinue | ForEach-Object {
  "pythonw PID=$($_.Id) Session=$($_.SessionId) Title='$($_.MainWindowTitle)'"
}
