@echo off
title SecureLink AI Campus Sentinel
cd /d "%~dp0securelinkdb\build\windows\x64\runner\Release"
echo =======================================================================
echo   STARTING SECURELINK DESKTOP DASHBOARD ^& CENTRAL SYSTEM AI ENGINE
echo =======================================================================
echo.
start securelinkdb.exe
exit
