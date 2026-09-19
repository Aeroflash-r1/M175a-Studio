# OCR screenshots — interop recipe with step tracking
param([string[]]$Paths)

Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime]
$null = [Windows.Media.Ocr.OcrEngine, Windows.Media.Ocr, ContentType = WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics.Imaging, ContentType = WindowsRuntime]

$asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() |
    Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
                   $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]

function Await($WinRtTask, $ResultType, $step) {
    $asTask = $asTaskGeneric.MakeGenericMethod($ResultType)
    $netTask = $asTask.Invoke($null, @($WinRtTask))
    try { $netTask.Wait(-1) | Out-Null }
    catch { throw "step=$step : $($_.Exception.InnerException.InnerException.Message)" }
    $netTask.Result
}

foreach ($p in $Paths) {
    $bp = $p -replace '/', '\'
    Write-Output "===== $(Split-Path $bp -Leaf) ====="
    try {
        $file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($bp)) ([Windows.Storage.StorageFile]) "GetFile"
        $stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream]) "Open"
        $decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder]) "Decode"
        $bitmap = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap]) "Bitmap"
        $ocr = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
        if (-not $ocr) { Write-Output "NO OCR ENGINE"; continue }
        $result = Await ($ocr.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult]) "Recognize"
        Write-Output $result.Text
    } catch {
        Write-Output "OCR ERROR: $_"
    }
}
