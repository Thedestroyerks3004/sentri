# Runtime configuration

Use [start_app.ps1](start_app.ps1) to launch the app with a reusable PowerShell environment.

Edit these values in the script whenever you need to change credentials:

- `TWILIO_ACCOUNT_SID`
- `TWILIO_AUTH_TOKEN`
- `TWILIO_PHONE_NUMBER`
- `TWILIO_TO_NUMBER`
- `PARKIQ_API_PORT`
- `PARKIQ_API_URL`

If you prefer, you can also run the commands manually in PowerShell:

```powershell
$env:TWILIO_ACCOUNT_SID="your_account_sid"
$env:TWILIO_AUTH_TOKEN="your_auth_token"
$env:TWILIO_PHONE_NUMBER="+15551234567"
$env:TWILIO_TO_NUMBER="+15551234567"
$env:PARKIQ_API_URL="http://127.0.0.1:8000"

"d:\Machine Learning\Gridlock\Parkiq\.venv\Scripts\python.exe" run_api.py
"d:\Machine Learning\Gridlock\Parkiq\.venv\Scripts\python.exe" -m streamlit run app.py
```
