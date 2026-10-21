# Launches an executable/.cmd on the interactive desktop (session 1) via a scheduled
# task with an interactive token. Works around session 0 isolation
# (prlctl exec runs as SYSTEM in session 0, invisible).
param(
  [Parameter(Mandatory=$true)][string]$Run,
  [string]$User = "DCCLABC0F5\dcclab"
)
$tn = "ThorRELaunch"
schtasks /delete /tn $tn /f 2>$null | Out-Null
# /it = interactive token: window visible on the user's desktop, without password
schtasks /create /tn $tn /tr $Run /sc once /st 00:00 /ru $User /it /f | Out-Null
schtasks /run /tn $tn
Write-Output "launched $Run as $User"
