$ErrorActionPreference = "Stop"
$idx = Invoke-RestMethod "https://api.nuget.org/v3-flatcontainer/ilspycmd/index.json"
# Affiche les dernieres versions disponibles
"=== versions 7.x / 8.x ==="
$idx.versions | Where-Object { $_ -match '^(7|8)\.' -and $_ -notmatch '-' }
