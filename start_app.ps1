# Run this once from PowerShell to set your runtime config and launch the app.
# Change the values below whenever needed; the same script will reuse them.

$projectPath = "D:\Machine Learning\Gridlock\Parkiq"
$pythonExe   = "$projectPath\.venv\Scripts\python.exe"

$env:TWILIO_ACCOUNT_SID  = "your_account_sid"
$env:TWILIO_AUTH_TOKEN   = "your_auth_token"
$env:TWILIO_PHONE_NUMBER = "your_twilio_number"
$env:TWILIO_TO_NUMBER    = "your_mobile_number"
$env:SENTRI_API_PORT     = "8000"
$env:SENTRI_API_URL      = "http://127.0.0.1:8000"

# Optional per-officer overrides (set only if you want specific recipients)
# $env:OFFICER_PHONE_FKUSR00218 = "+15551234567"

Write-Host "Starting SENTRI API and UI with the configured environment..."

$apiProcess = Start-Process -FilePath $pythonExe -ArgumentList "-m backend.run_api" -WorkingDirectory $projectPath -WindowStyle Normal -PassThru

$apiUrl = "$env:SENTRI_API_URL/health"
$deadline = (Get-Date).AddSeconds(45)
$apiReady = $false

while ((Get-Date) -lt $deadline) {
    try {
        $response = Invoke-WebRequest -Uri $apiUrl -Method Get -TimeoutSec 3
        if ($response.StatusCode -eq 200) {
            $apiReady = $true
            break
        }
    }
    catch {
        Start-Sleep -Seconds 1
    }
}

if (-not $apiReady) {
    Write-Warning "API did not become ready within 45 seconds. Starting UI anyway."
}

Start-Process -FilePath $pythonExe -ArgumentList "-m streamlit run frontend/app.py" -WorkingDirectory $projectPath -WindowStyle Normal

Write-Host "API/UI launched."
Write-Host "To change credentials later, edit the values at the top of this script and rerun it."
