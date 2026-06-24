# Meeting record one-click script
# Usage: .\run.ps1 ".\your_meeting.mp4"
# Requires: $env:GEMINI_API_KEY = "your-api-key"

param(
    [Parameter(Mandatory=$true)]
    [string]$VideoPath
)

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvPython = "$ScriptDir\.venv\Scripts\python.exe"

if (-not (Test-Path $VenvPython)) {
    Write-Error "Virtual environment not found."
    exit 1
}

if (-not (Test-Path $VideoPath)) {
    Write-Error "Video file not found: $VideoPath"
    exit 1
}

if (-not $env:GEMINI_API_KEY) {
    Write-Warning "GEMINI_API_KEY not set. Meeting minutes will be skipped."
    Write-Warning "To set: `$env:GEMINI_API_KEY = 'your-api-key'"
}

Write-Host "=== Step 1/2: Transcription ===" -ForegroundColor Cyan
& $VenvPython "$ScriptDir\transcribe.py" $VideoPath
if ($LASTEXITCODE -ne 0) {
    Write-Error "Transcription failed."
    exit 1
}

$TxtPath = [System.IO.Path]::ChangeExtension($VideoPath, ".txt")

if ($env:GEMINI_API_KEY) {
    Write-Host "`n=== Step 2/2: Generate Meeting Minutes ===" -ForegroundColor Cyan
    & $VenvPython "$ScriptDir\generate_minutes.py" $TxtPath
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Failed to generate meeting minutes."
        exit 1
    }
    $MdPath = [System.IO.Path]::ChangeExtension($VideoPath, ".md")
    Write-Host "`nDone! Meeting minutes saved: $MdPath" -ForegroundColor Green
} else {
    Write-Host "`nTranscript saved: $TxtPath" -ForegroundColor Green
    Write-Host "Set GEMINI_API_KEY then run:" -ForegroundColor Yellow
    Write-Host "  & `"$VenvPython`" `"$ScriptDir\generate_minutes.py`" `"$TxtPath`"" -ForegroundColor Yellow
}
