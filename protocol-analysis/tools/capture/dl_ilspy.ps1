$ErrorActionPreference = "Stop"
$ver = "8.2.0.7535"
$dir = "C:\ilspy"
New-Item -ItemType Directory -Force -Path $dir | Out-Null
$nupkg = "$dir\ilspycmd.$ver.nupkg"
$zip   = "$dir\ilspycmd.$ver.zip"
$url = "https://api.nuget.org/v3-flatcontainer/ilspycmd/$ver/ilspycmd.$ver.nupkg"
"downloading $url"
Invoke-WebRequest -Uri $url -OutFile $nupkg -UseBasicParsing
Copy-Item $nupkg $zip -Force
$ex = "$dir\extracted"
if (Test-Path $ex) { Remove-Item $ex -Recurse -Force }
Expand-Archive -Path $zip -DestinationPath $ex -Force
"=== TFM folders under tools ==="
Get-ChildItem "$ex\tools" -Directory | Select-Object -ExpandProperty Name
"=== ilspycmd.dll locations ==="
Get-ChildItem $ex -Recurse -Filter ilspycmd.dll | Select-Object -ExpandProperty FullName
