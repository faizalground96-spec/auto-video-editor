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
    call :log "ffmpeg.exe belum ada, mengunduh..."
    mkdir "%BIN%" 2>nul
    set "FFURL="
    for /f "usebackq delims=" %%L in ("%ROOT%tools\ffmpeg_win.txt") do (
        set "LINE=%%L"
        if "!LINE:~0,1!" neq "#" if "!LINE!" neq "" (
            if "!FFURL!"=="" ( set "FFURL=!LINE!" )
        )
    )
    call :log "URL: !FFURL!"
    powershell -NoProfile -Command "Invoke-WebRequest -Uri '!FFURL!' -OutFile '%ROOT%ffmpeg_dl.zip' -UserAgent 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'" >> "%LOG%" 2>&1
    if errorlevel 1 (
        call :log "GALAT: unduhan ffmpeg gagal."
        call :log "Silakan unduh manual dari https://www.gyan.dev/ffmpeg/builds/"
        call :log "lalu letakkan ffmpeg.exe di: %BIN%\ffmpeg.exe"
        goto :fail
    )
    for %%S in ("%ROOT%ffmpeg_dl.zip") do set "FFSIZE=%%~zS"
    if !FFSIZE! lss 50000000 (
        call :log "GALAT: file unduhan hanya !FFSIZE! byte (harusnya ~100MB+) — kemungkinan halaman error, bukan zip."
        call :log "Hapus ffmpeg_dl.zip dan coba lagi, atau unduh manual dari https://www.gyan.dev/ffmpeg/builds/"
        goto :fail
    )
    powershell -NoProfile -Command "Expand-Archive -Path '%ROOT%ffmpeg_dl.zip' -DestinationPath '%ROOT%ffmpeg_tmp' -Force" >> "%LOG%" 2>&1
    if errorlevel 1 (
        call :log "GALAT: gagal mengekstrak arsip ffmpeg (file rusak/tidak lengkap)."
        call :log "Hapus ffmpeg_dl.zip dan coba lagi."
        goto :fail
    )
    set "FFFOUND="
    for /r "%ROOT%ffmpeg_tmp" %%F in (ffmpeg.exe) do (
        if not defined FFFOUND (
            copy "%%F" "%BIN%\ffmpeg.exe" >> "%LOG%" 2>&1
            set "FFFOUND=1"
        )
    )
    rmdir /s /q "%ROOT%ffmpeg_tmp" 2>nul
    del "%ROOT%ffmpeg_dl.zip" 2>nul
    if not exist "%BIN%\ffmpeg.exe" (
        call :log "GALAT: ffmpeg.exe tak ketemu di arsip."
        goto :fail
    )
    call :log "ffmpeg.exe siap."
) else (
    call :log "ffmpeg.exe sudah ada."
)

REM --- 4. pyinstaller --------------------------------------------------------
call :log "--- pyinstaller (ini lama, tunggu) ---"
"%VENV%\Scripts\python.exe" -m PyInstaller --version >> "%LOG%" 2>&1
"%VENV%\Scripts\pyinstaller.exe" "%ROOT%build.spec" --noconfirm >> "%LOG%" 2>&1
if errorlevel 1 (
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
