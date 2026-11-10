$ErrorActionPreference = "Stop"

$dir = Join-Path $env:LOCALAPPDATA "InstagramReelsChecker"
$tmp = Join-Path $env:TEMP "instaparse-install"
$repo = "https://github.com/elkaofficial1/bot-instaparse/archive/refs/heads/main.zip"

if (-not (Get-Command winget -ErrorAction SilentlyContinue)) { throw "Нужен winget." }

if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
    winget install --id Python.Python.3.13 --exact --scope user --accept-package-agreements --accept-source-agreements
}
if (Test-Path $dir) { throw "Папка уже существует: $dir" }

New-Item -ItemType Directory -Force $tmp | Out-Null
try {
    Invoke-WebRequest $repo -OutFile "$tmp\project.zip"
    Expand-Archive "$tmp\project.zip" -DestinationPath $tmp
    $src = Get-ChildItem $tmp -Directory | Where-Object Name -Like "bot-instaparse-*" | Select-Object -First 1
    if (-not $src) { throw "Архив проекта не найден." }
    Move-Item $src.FullName $dir

    Set-Location $dir
    py -3.13 -m venv .venv
    $python = "$dir\.venv\Scripts\python.exe"
    & $python -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) { throw "Не удалось установить зависимости." }
    & $python -m playwright install chromium
    if ($LASTEXITCODE -ne 0) { throw "Не удалось установить Chromium." }

    New-Item -ItemType Directory -Force xls, results | Out-Null

    $desktop = [Environment]::GetFolderPath("Desktop")
    $link = (New-Object -ComObject WScript.Shell).CreateShortcut("$desktop\Instagram Reels Checker.lnk")
    $link.TargetPath = $python
    $link.Arguments = "launcher.py"
    $link.WorkingDirectory = $dir
    $link.IconLocation = "$python,0"
    $link.Save()

    Write-Host "Установка завершена!" -ForegroundColor Green
}
finally {
    Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue
}
