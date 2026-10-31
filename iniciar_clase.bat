@echo off
rem ==========================================================================
rem  Clase en Vivo UNACHI - arranque para Windows 10/11
rem  Requiere Python 3.8+ (https://www.python.org o: winget install -e --id Python.Python.3.12)
rem  Parametros opcionales: --ip 192.168.1.50  --puerto-web 8081  --sin-navegador
rem ==========================================================================
chcp 65001 >nul
setlocal
cd /d "%~dp0"
title Clase en Vivo UNACHI

set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY (
  where python >nul 2>nul && set "PY=python"
)
if not defined PY goto sinpython
%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)" >nul 2>nul || goto sinpython

echo.
echo  Iniciando Clase en Vivo UNACHI...
echo  (La primera vez se descarga MediaMTX; se necesita Internet solo en ese momento.)
echo  Si Windows pregunta por el firewall, marque "Redes privadas" y pulse "Permitir acceso".
echo.
%PY% servidor_clase.py %*
echo.
pause
exit /b 0

:sinpython
echo.
echo  [ERROR] No se encontro Python 3.8 o superior.
echo  Instalelo con:  winget install -e --id Python.Python.3.12
echo  o desde https://www.python.org/downloads/ (marque "Add python.exe to PATH").
echo.
pause
exit /b 1
