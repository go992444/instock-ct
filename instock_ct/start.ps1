Set-Location $PSScriptRoot
$root = Split-Path $PSScriptRoot -Parent
$py = if (Test-Path "$root\.venv\Scripts\python.exe") { "$root\.venv\Scripts\python.exe" } else { "python" }
& $py -m pip show streamlit pandas 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) { & $py -m pip install -r requirements.txt }
Write-Host "Instock CT 실행..."
& $py -m streamlit run app.py
