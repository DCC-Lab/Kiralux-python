try {
  $r = Invoke-WebRequest -Uri "https://api.nuget.org/v3/index.json" -UseBasicParsing -TimeoutSec 15
  "HTTP_OK status=$($r.StatusCode)"
} catch {
  "HTTP_FAIL $($_.Exception.Message)"
}
