# Crea una tarea en el Programador de tareas de Windows que ejecuta el bot
# automáticamente. Ejecutar este script UNA VEZ, en PowerShell, desde esta
# misma carpeta (o pasando -TaskName/-Hora según se necesite).
#
#   .\task_scheduler_setup.ps1
#   .\task_scheduler_setup.ps1 -Hora "07:30"

param(
    [string]$TaskName = "PeopleSync_RPA_Bot",
    [string]$Hora = "08:00"
)

$Aqui = Split-Path -Parent $MyInvocation.MyCommand.Path
$RunBot = Join-Path $Aqui "run_bot.bat"
if (-not (Test-Path $RunBot)) {
    Write-Error "No se encontró run_bot.bat en $Aqui."
    exit 1
}

# Se ejecuta a través de run_bot.bat (no invocando python.exe directo) porque
# ese script prioriza el intérprete del .venv del proyecto si existe, y solo
# cae al 'python' del PATH si no hay .venv. Apuntar directo al python del PATH
# es frágil: en esta máquina el 'python' global no tiene selenium/pandas
# instalados, así que la tarea "tenía éxito" (exit code 0) sin haber llegado
# siquiera a escribir un log, porque el import fallaba antes de arrancar.
$Accion = New-ScheduledTaskAction -Execute $RunBot -Argument "--headless" -WorkingDirectory $Aqui
$Disparador = New-ScheduledTaskTrigger -Daily -At $Hora
$Configuracion = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopOnIdleEnd

Register-ScheduledTask -TaskName $TaskName -Action $Accion -Trigger $Disparador -Settings $Configuracion `
    -Description "Ejecuta el bot RPA de registro de ingresos PeopleSync (rpa-peoplesync)"

Write-Output "Tarea programada '$TaskName' creada. Se ejecutara todos los dias a las $Hora."
Write-Output "Puedes verla/editarla en el Programador de tareas de Windows, o ejecutarla ahora con:"
Write-Output "  Start-ScheduledTask -TaskName '$TaskName'"
