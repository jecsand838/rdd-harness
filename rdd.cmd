@echo off
python "%~dp0tools\rdd\cli.py" %*
exit /b %errorlevel%
