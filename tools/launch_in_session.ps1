# Lance un executable/.cmd sur le bureau interactif (session 1) via une tache
# planifiee a token interactif. Contourne l'isolement de session 0
# (prlctl exec s'execute en tant que SYSTEM dans la session 0, invisible).
param(
  [Parameter(Mandatory=$true)][string]$Run,
  [string]$User = "DCCLABC0F5\dcclab"
)
$tn = "ThorRELaunch"
schtasks /delete /tn $tn /f 2>$null | Out-Null
# /it = interactive token: fenetre visible sur le bureau de l'utilisateur, sans mot de passe
schtasks /create /tn $tn /tr $Run /sc once /st 00:00 /ru $User /it /f | Out-Null
schtasks /run /tn $tn
Write-Output "launched $Run as $User"
