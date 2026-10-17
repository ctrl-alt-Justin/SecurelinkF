@echo off
title SecureLink Mobile Data Cloud Tunnel Gateway
echo =======================================================================
echo   SECURELINK CLOUD TUNNEL GATEWAY (MOBILE DATA / CELLULAR SYNC)
echo =======================================================================
echo.
python "%~dp0start_tunnel.py" %*
pause
