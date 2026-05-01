$p = '.env'
if (-not (Test-Path $p)) { Write-Host '.env not found'; exit 0 }
$b = [IO.File]::ReadAllBytes($p)
if ($b -contains 13) {
    Write-Host 'CRLF detected in .env -- converting to LF'
    $t = [Text.Encoding]::UTF8.GetString($b)
    $t = $t.Replace("`r`n", "`n").Replace("`r", "`n")
    [IO.File]::WriteAllText($p, $t, [Text.UTF8Encoding]::new($false))
    Write-Host 'done'
} else {
    Write-Host 'LF only -- good'
}
