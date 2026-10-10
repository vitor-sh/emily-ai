param(
    [string]$InstallDir = (Join-Path $env:LOCALAPPDATA 'Programs\Emily'),
    [string]$GatewayUrl = '',
    [string]$Token = ''
)

$ErrorActionPreference = 'Stop'
$internal = Join-Path $InstallDir '_internal'
$exe = Join-Path $InstallDir 'Emily.exe'
$release = Join-Path $internal 'windows-release.json'
if (!(Test-Path -LiteralPath $exe) -or !(Test-Path -LiteralPath $release)) {
    throw "Não encontrei a instalação da Emily em $InstallDir"
}
$config = Get-Content -LiteralPath $release -Raw -Encoding UTF8 | ConvertFrom-Json
if (!$GatewayUrl) { $GatewayUrl = [string]$config.sync_url }
$GatewayUrl = $GatewayUrl.TrimEnd('/')
if (!$GatewayUrl.StartsWith('https://') -and !$GatewayUrl.StartsWith('http://127.0.0.1')) {
    throw 'Configure o endereço HTTPS do gateway com -GatewayUrl.'
}
if (!$Token) {
    foreach ($envFile in @((Join-Path $InstallDir '.env'), (Join-Path $internal '.env'))) {
        if (!(Test-Path -LiteralPath $envFile)) { continue }
        $linha = Get-Content -LiteralPath $envFile -Encoding UTF8 |
            Where-Object { $_ -match '^\s*EMILY_PONTE_TOKEN\s*=' } | Select-Object -First 1
        if ($linha -match '^\s*EMILY_PONTE_TOKEN\s*=\s*(.*)$') {
            $Token = $Matches[1].Trim().Trim('"').Trim("'")
            if ($Token) { break }
        }
    }
}
if (!$Token) { throw 'Não encontrei EMILY_PONTE_TOKEN. Informe -Token sem compartilhar a chave.' }

$headers = @{ Authorization = "Bearer $Token"; 'ngrok-skip-browser-warning' = 'true' }
$base = "$GatewayUrl/windows/code-update"
$manifest = Invoke-RestMethod -Uri $base -Headers $headers -TimeoutSec 15
if (!$manifest.ok) {
    $motivo = [string]$manifest.erro
    throw "O gateway em $GatewayUrl não entregou o pacote de código ($motivo). Use -GatewayUrl com o endereço ativo do Fedora."
}
if ([string]$manifest.installer -ne [string]$config.version) {
    throw "O pacote exige o instalador $($manifest.installer), mas este PC usa $($config.version)."
}

$temp = Join-Path $env:TEMP ("EmilyCodeBootstrap-" + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $temp | Out-Null
try {
    $archive = Join-Path $temp 'codigo.zip'
    Invoke-WebRequest -Uri "$base/archive" -Headers $headers -OutFile $archive -UseBasicParsing -TimeoutSec 180
    if ((Get-Item -LiteralPath $archive).Length -ne [long]$manifest.size) {
        throw 'O tamanho do download não confere.'
    }
    $hash = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($hash -ne [string]$manifest.sha256) { throw 'O SHA-256 do download não confere.' }
    $extraido = Join-Path $temp 'extraido'
    Expand-Archive -LiteralPath $archive -DestinationPath $extraido
    foreach ($name in @('windows_code_update.py', 'windows_update.py')) {
        $src = Join-Path $extraido $name
        $esperado = [string]$manifest.files.PSObject.Properties[$name].Value
        if (!(Test-Path -LiteralPath $src) -or !$esperado) { throw "Falta $name no pacote." }
        $real = (Get-FileHash -LiteralPath $src -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($real -ne $esperado) { throw "Hash incorreto em $name." }
        $dest = Join-Path $internal $name
        $incoming = "$dest.incoming"
        Copy-Item -LiteralPath $src -Destination $incoming -Force
        if (Test-Path -LiteralPath $dest) {
            [System.IO.File]::Replace($incoming, $dest, "$dest.before-code", $true)
        } else {
            [System.IO.File]::Move($incoming, $dest)
        }
    }
    # O endereço do instalador pode ter ficado antigo. Persistir o endpoint que
    # acabou de entregar um pacote íntegro permite as próximas buscas ao abrir.
    $config.sync_url = $GatewayUrl
    $config.update_url = "$GatewayUrl/windows/update"
    $releaseIncoming = "$release.incoming"
    $json = $config | ConvertTo-Json -Depth 8
    [System.IO.File]::WriteAllText(
        $releaseIncoming, $json, (New-Object System.Text.UTF8Encoding($false)))
    [System.IO.File]::Replace($releaseIncoming, $release, "$release.before-code", $true)
    Write-Host 'Atualização leve ativada. Feche e abra a Emily no Windows: ela baixará o código pelo gateway.'
} finally {
    Remove-Item -LiteralPath $temp -Recurse -Force -ErrorAction SilentlyContinue
}
