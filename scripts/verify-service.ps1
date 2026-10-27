param([string]$BaseUrl="http://127.0.0.1:8101")
$ErrorActionPreference="Stop"
Write-Host "== OpsCenter verification =="
Invoke-RestMethod "$BaseUrl/live"
Invoke-RestMethod "$BaseUrl/ready"
Invoke-RestMethod "$BaseUrl/health"
Invoke-RestMethod "$BaseUrl/version"
Write-Host "SERVICE HEALTHY"
