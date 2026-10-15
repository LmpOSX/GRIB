# Construye Visor GRIB para Windows con PyInstaller y arma los instaladores:
#   dist\Visor_GRIB_<ver>_Windows_x64_Setup.exe   instalador (Inno Setup 6)
#   dist\Visor_GRIB_<ver>_Windows_x64.zip         carpeta portable
# Uso (PowerShell, entorno con requirements.txt instalado):
#   pwsh scripts\build_windows.ps1
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

$ExeName = "VisorGRIB"
$Version = (python -c "from app import __version__; print(__version__)").Trim()
$Base = "Visor_GRIB_${Version}_Windows_x64"
Write-Host "=== Visor GRIB $Version (Windows x64) ==="

Write-Host "=== Generando iconos ==="
python scripts/make_icon.py
if ($LASTEXITCODE -ne 0) { throw "make_icon.py falló" }

Write-Host "=== Limpiando builds anteriores ==="
Remove-Item -Recurse -Force build, dist -ErrorAction SilentlyContinue

Write-Host "=== Construyendo aplicación (PyInstaller) ==="
pyinstaller --noconfirm --clean packaging/visor_grib.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller falló" }
$AppDir = "dist\$ExeName"
if (-not (Test-Path "$AppDir\$ExeName.exe")) { throw "No se generó la aplicación" }

Write-Host "=== Prueba de humo: abrir un GRIB WAFS dentro del paquete ==="
$SmokeDir = Join-Path ([System.IO.Path]::GetTempPath()) ("visorgrib_smoke_" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $SmokeDir | Out-Null
Copy-Item tests\data\WAFS_like_test.grib2 $SmokeDir
$env:VISOR_GRIB_SMOKE = "8"
$env:QT_QPA_PLATFORM = "offscreen"
$p = Start-Process -FilePath "$AppDir\$ExeName.exe" -ArgumentList "`"$SmokeDir\WAFS_like_test.grib2`"" -Wait -PassThru
Remove-Item Env:VISOR_GRIB_SMOKE
Remove-Item Env:QT_QPA_PLATFORM
Remove-Item -Recurse -Force $SmokeDir
if ($p.ExitCode -ne 0) { throw "La prueba de humo falló (código $($p.ExitCode))" }
Write-Host "smoke: ok"

Write-Host "=== zip portable ==="
Compress-Archive -Path "$AppDir\*" -DestinationPath "dist\$Base.zip" -Force

Write-Host "=== Instalador (Inno Setup) ==="
$iscc = Get-Command iscc -ErrorAction SilentlyContinue
if ($iscc) { $iscc = $iscc.Source }
else {
    $cands = @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
               "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe")
    $iscc = $cands | Where-Object { Test-Path $_ } | Select-Object -First 1
}
if (-not $iscc) {
    Write-Warning "No se encontró Inno Setup 6 (ISCC.exe): se omite el Setup.exe. Instalarlo desde https://jrsoftware.org/isdl.php"
} else {
    & $iscc "/DMyAppVersion=$Version" "/DOutputBase=${Base}_Setup" packaging\visor_grib.iss
    if ($LASTEXITCODE -ne 0) { throw "Inno Setup falló" }
}

Write-Host ""
Write-Host "=== Build completado ==="
Get-ChildItem dist\Visor_GRIB_* | ForEach-Object { Write-Host "  $($_.Name)  $([math]::Round($_.Length/1MB,1)) MB" }
