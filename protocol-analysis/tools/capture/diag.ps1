"=== pythonw.exe present? ==="
Test-Path "C:\Program Files\Python313\pythonw.exe"
"=== task last result ==="
schtasks /query /tn ThorRELaunch /fo LIST /v | Select-String "Result|Status|Run As|Last Run"
"=== run script directly (pythonw) and capture via a log ==="
$log = "C:\Mac\Home\ThorImageRE\tools\run.log"
& "C:\Program Files\Python313\pythonw.exe" "C:\Mac\Home\ThorImageRE\tools\show_image.py" --seconds 2 *> $log
"exit=$LASTEXITCODE"
"--- log ---"
if (Test-Path $log) { Get-Content $log }
