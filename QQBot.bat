@echo off
setlocal EnableExtensions
rem Use the project-local portable Python.
set "qqbot_python=%~dp0tools\python\python.exe"
if not exist "%qqbot_python%" (
  echo Missing bundled Python runtime: tools\python
  echo Run Install.bat in the project folder first.
  pause
  exit /b 1
)
set "PYTHONDONTWRITEBYTECODE=1"
rem Default: foreground. Use --hidden to run with pythonw.
if /I "%~1"=="--hidden" (
  start "" "%~dp0tools\python\pythonw.exe" -B "%~dp0src\DesktopShell\start.py"
  exit /b 0
)
"%qqbot_python%" -B "%~dp0src\DesktopShell\start.py" %*
set "qqbot_exit=%errorlevel%"
if not "%qqbot_exit%"=="0" pause
exit /b %qqbot_exit%
