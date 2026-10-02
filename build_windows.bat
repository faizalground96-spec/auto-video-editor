@echo off
REM build_windows.bat — Build Auto Video Editor di Windows (Tahap 10).
REM Semua keluaran dicatat ke build.log. Tahan terhadap folder berspasi.
REM JALANKAN DARI CMD yang sudah terbuka (bukan double-click) agar
REM pesan galat tidak hilang saat jendela tertutup.
setlocal EnableDelayedExpansion

set "ROOT=%~dp0"
set "LOG=%ROOT%build.log"
set "VENV=%ROOT%.venv-win"
set "BIN=%ROOT%bin"

echo === Build dimulai: %DATE% %TIME% === > "%LOG%"
call :log "ROOT=%ROOT%"

REM --- 1. cek Python -------------------------------------------------------
call :log "--- Cek Python ---"
py -3.11 --version >nul 2>&1
if not errorlevel 1 (
    set "PY=py -3.11"
    call :log "Python: py -3.11"
) else (
    py -3.12 --version >nul 2>&1
    if not errorlevel 1 (
        set "PY=py -3.12"
        call :log "Python: py -3.12"
    ) else (
        python --version >nul 2>&1
        if not errorlevel 1 (
            set "PY=python"
            call :log "Python: python (fallback)"
        ) else (
            call :log "GALAT: Python 3.11 atau 3.12 tidak ditemukan. Pasang dari python.org."
            goto :fail
        )
    )
)

REM --- 2. venv + requirements ----------------------------------------------
call :log "--- venv + pip install ---"
if not exist "%VENV%\Scripts\python.exe" (
    call :log "Membuat venv..."
    %PY% -m venv "%VENV%" >> "%LOG%" 2>&1
    if errorlevel 1 (
        call :log "GALAT: gagal membuat venv. Lihat build.log."
        goto :fail
    )
)
call :log "pip install -r requirements.txt (ini lama, tunggu) ..."
"%VENV%\Scripts\python.exe" -m pip install --upgrade pip >> "%LOG%" 2>&1
"%VENV%\Scripts\python.exe" -m pip install -r "%ROOT%requirements.txt" >> "%LOG%" 2>&1
if errorlevel 1 (
    call :log "GALAT: pip install gagal. Lihat build.log."
    goto :fail
)

REM --- 3. ffmpeg.exe --------------------------------------------------------
call :log "--- ffmpeg ---"
if not exist "%BIN%\ffmpeg.exe" (
    call :log "ffmpeg.exe belum ada, mengunduh & memasang via PowerShell..."
    mkdir "%BIN%" 2>nul
    set "FFURL="
    for /f "usebackq delims=" %%L in ("%ROOT%tools\ffmpeg_win.txt") do (
        set "LINE=%%L"
        if "!LINE:~0,1!" neq "#" if "!LINE!" neq "" (
            if "!FFURL!"=="" ( set "FFURL=!LINE!" )
        )
    )
    call :log "URL: !FFURL!"
    powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%tools\install_ffmpeg.ps1" -Url "!FFURL!" -DestExe "%BIN%\ffmpeg.exe" >> "%LOG%" 2>&1
    if errorlevel 1 (
        call :log "GALAT: pemasangan ffmpeg gagal. Lihat build.log untuk detail."
        call :log "Alternatif manual: unduh dari https://www.gyan.dev/ffmpeg/builds/"
        call :log "lalu letakkan ffmpeg.exe di: %BIN%\ffmpeg.exe"
        goto :fail
    )
    call :log "ffmpeg.exe siap."
) else (
    call :log "ffmpeg.exe sudah ada."
)

REM --- 4. pyinstaller --------------------------------------------------------
call :log "--- pyinstaller (ini lama, tunggu) ---"
REM Pindah ke ROOT dulu agar folder dist/ & build/ selalu di lokasi yang benar,
REM tidak tergantung posisi cmd saat bat dijalankan.
pushd "%ROOT%"
"%VENV%\Scripts\python.exe" -m PyInstaller --version >> "%LOG%" 2>&1
"%VENV%\Scripts\pyinstaller.exe" "%ROOT%build.spec" --noconfirm --distpath "%ROOT%dist" --workpath "%ROOT%build" >> "%LOG%" 2>&1
set "PIERR=0"
if errorlevel 1 set "PIERR=1"
popd
if "%PIERR%"=="1" (
    call :log "GALAT: pyinstaller gagal. Lihat build.log."
    goto :fail
)

REM --- 5. self-test hasil build ----------------------------------------------
call :log "--- self-test ---"
set "CLIEXE=%ROOT%dist\AutoVideoEditor\AutoVideoEditorCLI.exe"
if not exist "%CLIEXE%" (
    call :log "GALAT: %CLIEXE% tidak ada."
    goto :fail
)
"%CLIEXE%" --self-test >> "%LOG%" 2>&1
set "ST=0"
if errorlevel 1 set "ST=1"
findstr /c:"[OK]" /c:"[GAGAL]" /c:"SELF-TEST" "%LOG%"
if %ST% neq 0 (
    call :log "PERINGATAN: self-test GAGAL — build bermasalah. Lihat build.log."
    goto :fail
)

call :log ""
call :log "BUILD SELESAI: dist\AutoVideoEditor\"
echo.
echo Selesai. Tekan Enter untuk tutup.
set /p "DUMMY="
exit /b 0

:fail
echo.
echo Build GAGAL. Lihat build.log untuk detail.
echo Tekan Enter untuk tutup.
set /p "DUMMY="
exit /b 1

:log
echo %~1 >> "%LOG%"
echo %~1
goto :eof
