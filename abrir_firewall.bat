@echo off
rem ==========================================================================
rem  Clase en Vivo UNACHI - reglas de firewall de Windows (ejecutar UNA vez)
rem  Abre sólo para la subred local (remoteip=localsubnet):
rem    TCP 8080 (páginas web), TCP 8889 (señalización WebRTC),
rem    UDP/TCP 8189 (medios WebRTC)
rem ==========================================================================
chcp 65001 >nul
net session >nul 2>&1
if errorlevel 1 (
  echo Solicitando permisos de administrador...
  powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)

set "N=Clase en Vivo UNACHI"
netsh advfirewall firewall delete rule name="%N% - TCP" >nul 2>&1
netsh advfirewall firewall delete rule name="%N% - UDP" >nul 2>&1
netsh advfirewall firewall add rule name="%N% - TCP" dir=in action=allow protocol=TCP localport=8080,8889,8189 remoteip=localsubnet profile=any
netsh advfirewall firewall add rule name="%N% - UDP" dir=in action=allow protocol=UDP localport=8189 remoteip=localsubnet profile=any

echo.
echo  Reglas creadas. Para eliminarlas mas adelante:
echo    netsh advfirewall firewall delete rule name="%N% - TCP"
echo    netsh advfirewall firewall delete rule name="%N% - UDP"
echo.
echo  IMPORTANTE: si alguna vez pulso "Cancelar" en el aviso del firewall para
echo  python.exe o mediamtx.exe, Windows creo reglas de BLOQUEO que tienen
echo  prioridad. Reviselas en: wf.msc ^> Reglas de entrada.
echo.
pause
