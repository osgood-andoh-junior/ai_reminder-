param([switch]$SkipInstall)
$ErrorActionPreference = 'Stop'
# Some terminal hosts supply both Path and PATH. Windows PowerShell's
# Start-Process cannot copy that environment into its case-insensitive map.
$pathEntries = @([Environment]::GetEnvironmentVariables().Keys | Where-Object { $_ -ieq 'PATH' })
if ($pathEntries.Count -gt 1) {
    $launchPath = ($pathEntries | ForEach-Object { [Environment]::GetEnvironmentVariable($_) }) -join ';'
    foreach ($pathEntry in $pathEntries) { [Environment]::SetEnvironmentVariable($pathEntry, $null, 'Process') }
    [Environment]::SetEnvironmentVariable('Path', $launchPath, 'Process')
}
$projectRoot = Split-Path -Parent $PSScriptRoot
$localPython = Join-Path $projectRoot '.runtime\python\python.exe'
$venvPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (Test-Path -LiteralPath $venvPython) { $runtimePython = $venvPython }
elseif (Test-Path -LiteralPath $localPython) { $runtimePython = $localPython }
else {
    $pythonCommand = Get-Command python -ErrorAction Stop
    & $pythonCommand.Source -m venv (Join-Path $projectRoot '.venv')
    $runtimePython = $venvPython
}
Push-Location $projectRoot
try {
    if (-not $SkipInstall) {
        & $runtimePython -m pip install -r backend\requirements-lock.txt
        if ($LASTEXITCODE -ne 0) { throw 'Backend dependency installation failed' }
        Push-Location frontend
        try { npm.cmd ci; if ($LASTEXITCODE -ne 0) { throw 'Frontend dependency installation failed' } }
        finally { Pop-Location }
    }
    if (-not (Test-Path backend\.env)) { Copy-Item backend\.env.example backend\.env }
    if (-not (Test-Path frontend\.env.local)) { Copy-Item frontend\.env.example frontend\.env.local }
    Push-Location backend
    try { & $runtimePython -m alembic upgrade head; if ($LASTEXITCODE -ne 0) { throw 'Migrations failed' } }
    finally { Pop-Location }
    $jobs = @()
    $jobs += Start-Process -FilePath $runtimePython -ArgumentList '-m','uvicorn','app.main:app','--host','127.0.0.1','--port','8000','--no-access-log' -WorkingDirectory (Join-Path $projectRoot 'backend') -WindowStyle Hidden -PassThru -RedirectStandardOutput 'backend-server.log' -RedirectStandardError 'backend-error.log'
    $jobs += Start-Process -FilePath $runtimePython -ArgumentList '-m','app.worker' -WorkingDirectory (Join-Path $projectRoot 'backend') -WindowStyle Hidden -PassThru -RedirectStandardOutput 'worker.log' -RedirectStandardError 'worker-error.log'
    $nodeCommand = Get-Command node -ErrorAction Stop
    $nextCli = Join-Path $projectRoot 'frontend\node_modules\next\dist\bin\next'
    $jobs += Start-Process -FilePath $nodeCommand.Source -ArgumentList ('"' + $nextCli + '"'),'dev','--hostname','127.0.0.1','--port','3000' -WorkingDirectory (Join-Path $projectRoot 'frontend') -WindowStyle Hidden -PassThru -RedirectStandardOutput 'frontend-server.log' -RedirectStandardError 'frontend-error.log'
    Write-Host 'Tempo is starting at http://localhost:3000. Logs are in the project root.'
    Write-Host 'Press Ctrl+C here to stop these processes.'
    try { while ($true) { Start-Sleep -Seconds 2; foreach ($job in $jobs) { if ($job.HasExited) { throw 'A server exited. Check the log files.' } } } }
    finally { foreach ($job in $jobs) { if (-not $job.HasExited) { Stop-Process -Id $job.Id } } }
}
finally { Pop-Location }
