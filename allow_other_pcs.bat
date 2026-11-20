@echo off
REM Lets other office PCs open the Wayfair Catalog on this PC (port 8001).
net session >nul 2>&1
if errorlevel 1 (
  echo Asking Windows for permission...
  powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)
netsh advfirewall firewall delete rule name="Wayfair Catalog" >nul 2>&1
netsh advfirewall firewall add rule name="Wayfair Catalog" dir=in action=allow protocol=TCP localport=8001 profile=any
if errorlevel 1 (
  echo Something went wrong. Take a screenshot of this window and send it.
) else (
  echo.
  echo Done. Other office PCs can now open the app on this PC.
)
echo.
pause
