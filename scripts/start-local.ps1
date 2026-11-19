param([switch]$Commands, [switch]$NoBuild, [switch]$PrepareOnly, [int]$FrontendPort = 8080, [int]$ApiPort = 8002, [int]$ChatPort = 8003)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
function Read-DotEnv([string]$Path) {
    $values = @{}
    foreach ($line in Get-Content -LiteralPath $Path) {
        if ($line -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$') {
            $values[$Matches[1]] = $Matches[2].Trim().Trim('"').Trim("'")
        }
    }
    return $values
}
Push-Location $projectRoot
try {
    if (!(Test-Path -LiteralPath '.env')) { throw 'Configure insper-eats/.env com POSTGRES_USER, POSTGRES_PASSWORD e POSTGRES_DB.' }
    if (!(Test-Path -LiteralPath 'chat-service/.env')) { Copy-Item -LiteralPath 'chat-service/.env.example' -Destination 'chat-service/.env'; Write-Host 'Arquivo chat-service/.env criado. Preencha a chave Gemini para usar IA.' }
    $dbValues = Read-DotEnv '.env'
    foreach ($field in @('POSTGRES_USER', 'POSTGRES_PASSWORD', 'POSTGRES_DB')) {
        if (!$dbValues[$field]) { throw "Preencha $field no arquivo insper-eats/.env." }
    }
    $dbUser = [Uri]::EscapeDataString($dbValues['POSTGRES_USER'])
    $dbPassword = [Uri]::EscapeDataString($dbValues['POSTGRES_PASSWORD'])
    $dbName = [Uri]::EscapeDataString($dbValues['POSTGRES_DB'])
    $provider = if ($Commands) { 'commands' } else { 'gemini' }
    $lines = @("APP_DATABASE_URL=postgresql+psycopg://${dbUser}:${dbPassword}@db:5432/${dbName}", "FRONTEND_PORT=$FrontendPort", "API_PORT=$ApiPort", "CHAT_PORT=$ChatPort", "AI_PROVIDER=$provider", 'COOKIE_SECURE=false')
    [IO.File]::WriteAllText((Join-Path $projectRoot '.env.docker'), ($lines -join "`n") + "`n", [Text.UTF8Encoding]::new($false))
    if ($PrepareOnly) {
        & docker compose --env-file .env --env-file .env.docker -f compose.yaml -f compose.app.yaml config --quiet
        if ($LASTEXITCODE -ne 0) { throw 'A configuração Docker não passou na validação.' }
        Write-Host 'Configuração local preparada e validada. Nenhum serviço foi iniciado.'
        return
    }
    $composeArgs = @('compose', '--env-file', '.env', '--env-file', '.env.docker', '-f', 'compose.yaml', '-f', 'compose.app.yaml', 'up', '-d', '--wait', '--wait-timeout', '240')
    if (!$NoBuild) { $composeArgs += '--build' }
    & docker @composeArgs
    if ($LASTEXITCODE -ne 0) { throw 'O Docker não concluiu a inicialização. Verifique Docker Desktop, portas e os logs dos serviços.' }
    Write-Host "Insper Eats disponível em http://localhost:$FrontendPort"
    Write-Host "Modo: $provider. Os pedidos confirmados são registrados no banco local existente."
} finally { Pop-Location }
