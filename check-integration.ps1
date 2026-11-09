& {
    $ErrorActionPreference = 'Stop'
    $qilRoot = (Get-Location).Path
    $qilDocker = 'C:\Users\user\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe'
    $qilPython = Join-Path $qilRoot '.venv\Scripts\python.exe'
    $qilComposeFile = Join-Path $qilRoot 'compose.yaml'
    $qilCompose = @('--context', 'desktop-linux', 'compose', '--project-name', 'qa-interview-lab', '--file', $qilComposeFile)

    foreach ($qilPath in @($qilDocker, $qilPython, $qilComposeFile, (Join-Path $qilRoot 'backend\manage.py'))) {
        if (-not (Test-Path -LiteralPath $qilPath -PathType Leaf)) {
            throw "Не найден файл: $qilPath. Запустите блок из корня QA Interview Lab."
        }
    }

    function Invoke-Qil {
        param([string]$QilProgram, [string[]]$QilArguments)
        & $QilProgram @QilArguments
        if ($LASTEXITCODE -ne 0) {
            throw ('Команда завершилась с кодом {0}: {1}' -f $LASTEXITCODE, $QilProgram)
        }
    }

    function New-QilSecret {
        $qilBytes = New-Object byte[] 48
        $qilRandom = [System.Security.Cryptography.RandomNumberGenerator]::Create()
        try {
            $qilRandom.GetBytes($qilBytes)
            [Convert]::ToBase64String($qilBytes)
        } finally {
            $qilRandom.Dispose()
        }
    }

    # Старый том нельзя подключать с новым случайным паролем.
    $qilVolumes = @(Invoke-Qil $qilDocker @('--context', 'desktop-linux', 'volume', 'ls', '--filter', 'name=qa-interview-lab_postgres_data', '--format', '{{.Name}}'))
    if (($qilVolumes -contains 'qa-interview-lab_postgres_data') -and [string]::IsNullOrWhiteSpace($env:POSTGRES_PASSWORD)) {
        throw 'Том уже существует, но его прежний POSTGRES_PASSWORD в этом PowerShell не задан. Остановлено без изменения тома.'
    }

    if ([string]::IsNullOrWhiteSpace($env:DJANGO_SECRET_KEY)) {
        $env:DJANGO_SECRET_KEY = New-QilSecret
    }
    if ([string]::IsNullOrWhiteSpace($env:POSTGRES_PASSWORD)) {
        $env:POSTGRES_PASSWORD = New-QilSecret
    }
    $env:DJANGO_SETTINGS_MODULE = 'config.settings'
    $env:DJANGO_DEBUG = 'false'
    $env:DJANGO_ALLOWED_HOSTS = '127.0.0.1,localhost'
    $env:POSTGRES_DB = 'qa_interview_lab'
    $env:POSTGRES_TEST_DB = 'test_qa_interview_lab'
    $env:POSTGRES_USER = 'qil'
    $env:POSTGRES_HOST = '127.0.0.1'
    $env:POSTGRES_PORT = '5432'

    Write-Host '1/5: Compose'
    Invoke-Qil $qilDocker ($qilCompose + @('config', '--quiet'))
    $qilServices = @(Invoke-Qil $qilDocker ($qilCompose + @('config', '--services')))
    if ($qilServices.Count -ne 1 -or $qilServices[0] -ne 'postgres') {
        throw 'Ожидался единственный сервис postgres. Запуск остановлен.'
    }
    Write-Host 'Compose config: PASS; services: postgres'

    Write-Host '2/5: PostgreSQL'
    Invoke-Qil $qilDocker ($qilCompose + @('up', '-d', '--no-recreate', '--wait', '--wait-timeout', '120', 'postgres'))

    Write-Host '3/5: Django и миграции'
    Push-Location (Join-Path $qilRoot 'backend')
    try {
        Invoke-Qil $qilPython @('manage.py', 'check', '--database', 'default')
        Invoke-Qil $qilPython @('manage.py', 'migrate')
        Invoke-Qil $qilPython @('manage.py', 'migrate', '--check')
        Invoke-Qil $qilPython @('manage.py', 'makemigrations', '--check', '--dry-run')

        Write-Host '4/5: Полный Pytest, включая DB-тесты'
        Invoke-Qil $qilPython @('-m', 'pytest', '.', '--ds=config.settings', '-q', '--tb=short')
    } finally {
        Pop-Location
    }

    Write-Host '5/5: Реальный HTTP backend'
    $qilProbe = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, 8000)
    try {
        $qilProbe.Start()
    } finally {
        $qilProbe.Stop()
    }

    $qilBackend = $null
    try {
        $qilBackendArguments = @('-B', ('"{0}"' -f (Join-Path $qilRoot 'backend\manage.py')), 'runserver', '127.0.0.1:8000', '--noreload')
        $qilBackend = Start-Process -FilePath $qilPython -ArgumentList $qilBackendArguments -WorkingDirectory $qilRoot -WindowStyle Hidden -PassThru
        $qilHttpOk = $false
        for ($qilAttempt = 0; $qilAttempt -lt 40; $qilAttempt++) {
            $qilBackend.Refresh()
            if ($qilBackend.HasExited) {
                throw ('Backend завершился с кодом {0}.' -f $qilBackend.ExitCode)
            }
            try {
                $qilResponse = Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:8000/' -TimeoutSec 1
                if ($qilResponse.StatusCode -eq 200 -and $qilResponse.Content.Trim() -eq 'QA Interview Lab backend') {
                    $qilHttpOk = $true
                    break
                }
            } catch {
                # Допустим только короткий период ожидания старта сервера.
            }
            Start-Sleep -Milliseconds 250
        }
        if (-not $qilHttpOk) {
            throw 'HTTP-проверка не получила ожидаемый ответ backend.'
        }
        $qilBackend.Refresh()
        if ($qilBackend.HasExited) { throw 'Запущенный backend уже завершился.' }
        Write-Host 'HTTP: PASS — 200, QA Interview Lab backend'
    } finally {
        if ($null -ne $qilBackend) {
            $qilBackend.Refresh()
            if (-not $qilBackend.HasExited) {
                Invoke-Qil (Join-Path $env:SystemRoot 'System32\taskkill.exe') @('/PID', [string]$qilBackend.Id, '/T', '/F')
            }
        }
    }

    Invoke-Qil $qilPython @('-m', 'pip', 'check')
    $qilContainer = @(Invoke-Qil $qilDocker ($qilCompose + @('ps', '--quiet', 'postgres')))
    if ($qilContainer.Count -ne 1) { throw 'Не найден работающий контейнер postgres.' }
    $qilHealth = @(Invoke-Qil $qilDocker @('--context', 'desktop-linux', 'inspect', '--format', '{{.State.Health.Status}}', $qilContainer[0]))
    if ($qilHealth.Count -ne 1 -or $qilHealth[0] -ne 'healthy') { throw 'PostgreSQL не healthy.' }
    Invoke-Qil $qilDocker ($qilCompose + @('ps', 'postgres'))
    Write-Host 'ПРОГОН ЗАВЕРШЁН. PostgreSQL оставлен healthy; проверочный backend остановлен.'
    Write-Host 'Не закрывайте это окно: переменные нужны для следующих этапов; .env не создавался.'
}
