# update.ps1: one round of Windows Update, run by `vms update` as SYSTEM through a scheduled task
# (the Windows Update API refuses to download or install from an SSH session). It installs every
# software update Windows Update offers (never a move to Windows 11: oem/install.bat holds the VM on
# 22H2) and writes one line to C:\coworker\update.result, which vms update waits for:
#   DONE installed=N failed=N reboot=0|1     or     FAILED <why>
# C:\coworker\update.log keeps what each round found and installed.
$ErrorActionPreference = 'Stop'
$dir = 'C:\coworker'
$log = Join-Path $dir 'update.log'
$result = Join-Path $dir 'update.result'
function Say($text) { Add-Content $log ("{0} {1}" -f (Get-Date -Format s), $text) }
try {
    $session = New-Object -ComObject Microsoft.Update.Session
    $found = $session.CreateUpdateSearcher().Search("IsInstalled=0 and IsHidden=0 and Type='Software'").Updates
    $todo = New-Object -ComObject Microsoft.Update.UpdateColl
    foreach ($u in $found) {
        if ($u.Title -match 'Windows 11') { Say "skipped: $($u.Title)"; continue }
        if (-not $u.EulaAccepted) { $u.AcceptEula() }
        [void]$todo.Add($u)
        Say "found: $($u.Title)"
    }
    if ($todo.Count -eq 0) {
        Say 'nothing to install'
        Set-Content $result 'DONE installed=0 failed=0 reboot=0'
        exit 0
    }
    $downloader = $session.CreateUpdateDownloader(); $downloader.Updates = $todo; [void]$downloader.Download()
    $installer = $session.CreateUpdateInstaller(); $installer.Updates = $todo
    $r = $installer.Install()
    $ok = 0; $bad = 0
    for ($i = 0; $i -lt $todo.Count; $i++) {
        $code = $r.GetUpdateResult($i).ResultCode          # 2 succeeded, 3 succeeded with errors, 4 failed, 5 aborted
        if ($code -eq 2 -or $code -eq 3) { $ok++ } else { $bad++ }
        Say "result ${code}: $($todo.Item($i).Title)"
    }
    Set-Content $result ("DONE installed={0} failed={1} reboot={2}" -f $ok, $bad, [int]$r.RebootRequired)
} catch {
    Say "failed: $($_.Exception.Message)"
    Set-Content $result ("FAILED {0}" -f $_.Exception.Message)
}
