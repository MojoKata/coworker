# install-msu.ps1 MSU: installs an update package (.msu) with wusa as SYSTEM, run by vms update
# through a scheduled task, and writes C:\coworker\msu.result: DONE exit=<wusa's exit code> or
# FAILED <why>. 0: installed; 3010: installed, restart needed; 2359302: already installed.
param([string]$Msu)
$result = 'C:\coworker\msu.result'
try {
    $p = Start-Process -FilePath "$env:WINDIR\System32\wusa.exe" -ArgumentList "`"$Msu`" /quiet /norestart" -Wait -PassThru
    Set-Content $result ("DONE exit={0}" -f $p.ExitCode)
} catch {
    Set-Content $result ("FAILED {0}" -f $_.Exception.Message)
}
