# Run this once from PowerShell to set your runtime config and launch the app.
# Change the values below whenever needed; the same script will reuse them.

$projectPath = "D:\Machine Learning\Gridlock\Parkiq"
$pythonExe   = "$projectPath\.venv\Scripts\python.exe"

$env:TWILIO_ACCOUNT_SID  = "your_account_sid"
$env:TWILIO_AUTH_TOKEN   = "your_auth_token"
$env:TWILIO_PHONE_NUMBER = "your_twilio_number"
$env:TWILIO_TO_NUMBER    = "your_mobile_number"
$env:PARKIQ_API_PORT     = "8000"
$env:PARKIQ_API_URL      = "http://127.0.0.1:8000"

# Optional per-officer overrides (set only if you want specific recipients)
# $env:OFFICER_PHONE_FKUSR00218 = "+15551234567"

Write-Host "Starting ParkIQ API and UI with the configured environment..."

Start-Process -FilePath $pythonExe -ArgumentList "run_api.py" -WorkingDirectory $projectPath -WindowStyle Normal
Start-Process -FilePath $pythonExe -ArgumentList "-m streamlit run app.py" -WorkingDirectory $projectPath -WindowStyle Normal

Write-Host "API/UI launched."
Write-Host "To change credentials later, edit the values at the top of this script and rerun it."
