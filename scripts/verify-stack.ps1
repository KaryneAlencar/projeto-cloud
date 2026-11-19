param([switch]$NoBuild)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location $projectRoot
try {
    $argsList = @('compose', '-p', 'insper-eats-verification', '-f', 'compose.verify.yaml', 'up', '-d', '--wait', '--wait-timeout', '300')
    if (!$NoBuild) { $argsList += '--build' }
    & docker @argsList
    if ($LASTEXITCODE -ne 0) { throw 'O ambiente de verificação não iniciou.' }
    & '.\chat-service\.venv\Scripts\python.exe' '.\scripts\verify_stack.py'
    if ($LASTEXITCODE -ne 0) { throw 'A verificação encontrou uma falha.' }
    Write-Host 'Relatório: insper-eats/work/verification.json. Ambiente disponível na porta 18080.'
} finally { Pop-Location }
