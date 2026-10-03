#requires -Version 7.0
<#
Run offline unittest discovery with temporary files inside this workspace.
Only the child test process receives TEMP/TMP; the caller's environment stays intact.
#>
[CmdletBinding()]
param(
    [ValidateNotNullOrEmpty()]
    [string]$Pattern = 'test*.py'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$repositoryRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$pythonExecutable = Join-Path $repositoryRoot '.venv\Scripts\python.exe'
$temporaryRoot = Join-Path $repositoryRoot '.test-tmp'
$runDirectory = $null
$testProcess = $null
$resultCode = 1

try {
    if (-not (Test-Path -LiteralPath $pythonExecutable -PathType Leaf)) {
        throw 'The project .venv Python interpreter is required; no fallback interpreter is used.'
    }
    if (Test-Path -LiteralPath $temporaryRoot) {
        $temporaryItem = Get-Item -LiteralPath $temporaryRoot -Force
        if (-not $temporaryItem.PSIsContainer -or
            ($temporaryItem.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
            throw 'The test temporary root must be a regular workspace directory.'
        }
    } else {
        $null = New-Item -ItemType Directory -Path $temporaryRoot
    }
    $runDirectory = Join-Path $temporaryRoot ('run-' + [Guid]::NewGuid().ToString('N'))
    $null = New-Item -ItemType Directory -Path $runDirectory

    $startInfo = [Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName = $pythonExecutable
    $startInfo.WorkingDirectory = $repositoryRoot
    $startInfo.UseShellExecute = $false
    foreach ($argument in @('-B', '-m', 'unittest', 'discover', '-s', 'tests', '-p', $Pattern, '-v')) {
        $startInfo.ArgumentList.Add($argument)
    }
    $startInfo.Environment['TEMP'] = $runDirectory
    $startInfo.Environment['TMP'] = $runDirectory
    $startInfo.Environment['TMPDIR'] = $runDirectory
    $testProcess = [Diagnostics.Process]::Start($startInfo)
    $testProcess.WaitForExit()
    $resultCode = $testProcess.ExitCode
} catch {
    [Console]::Error.WriteLine('Local test runner failed: ' + $_.Exception.Message)
} finally {
    if ($null -ne $testProcess) { $testProcess.Dispose() }
    if ($null -ne $runDirectory -and (Test-Path -LiteralPath $runDirectory)) {
        try {
            # Verify the absolute deletion target and its parent before recursive cleanup.
            $resolvedRoot = (Get-Item -LiteralPath $temporaryRoot -Force).FullName
            $runItem = Get-Item -LiteralPath $runDirectory -Force
            $resolvedRun = $runItem.FullName
            $expectedRoot = [IO.Path]::GetFullPath($temporaryRoot)
            if (-not $resolvedRoot.Equals($expectedRoot, [StringComparison]::OrdinalIgnoreCase) -or
                -not $resolvedRun.StartsWith($expectedRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase) -or
                ($runItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -or
                ((Get-Item -LiteralPath $temporaryRoot -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)) {
                throw 'Refusing cleanup outside the regular workspace test temporary root.'
            }
            Remove-Item -LiteralPath $resolvedRun -Recurse -Force
        } catch {
            [Console]::Error.WriteLine('Test temporary directory cleanup failed: ' + $_.Exception.Message)
            if ($resultCode -eq 0) { $resultCode = 1 }
        }
    }
}
exit $resultCode
