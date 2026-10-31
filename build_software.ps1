$ErrorActionPreference = 'Stop'
$dir = $PSScriptRoot
$htmlPath = Join-Path $dir 'app.html'
$libPath  = Join-Path $dir 'lib\xlsx.full.min.js'

# Chinese output names built from code points to avoid PS5.1 no-BOM mojibake
function U([int[]]$codes){ -join ($codes | ForEach-Object { [char]::ConvertFromUtf32($_) })
}
$htmlName = (U @(0x6D17,0x8863,0x673A,0x6570,0x636E,0x5206,0x6790,0x8F6F,0x4EF6)) + '.html'
$batName  = (U @(0x542F,0x52A8,0x6D17,0x8863,0x673A,0x5206,0x6790,0x5DE5,0x5177)) + '.bat'
$outPath  = Join-Path $dir $htmlName
$batPath  = Join-Path $dir $batName

$html = [System.IO.File]::ReadAllText($htmlPath, (New-Object System.Text.UTF8Encoding($false)))
$lib  = [System.IO.File]::ReadAllText($libPath,  (New-Object System.Text.UTF8Encoding($false)))

# neutralise any </script> inside the library so inline embedding stays valid
$libSafe = $lib -replace '</script>', '<\/script>'
$tag = '<script src="lib/xlsx.full.min.js"></script>'
if ($html.IndexOf($tag) -lt 0) { throw 'library script tag not found' }
$merged = $html.Replace($tag, "<script>`n" + $libSafe + "`n</script>")

[System.IO.File]::WriteAllText($outPath, $merged, (New-Object System.Text.UTF8Encoding($false)))
Write-Host ("PACKED: {0} ({1} KB)" -f $outPath, [Math]::Round((Get-Item $outPath).Length/1KB,1))

# launcher bat in GBK so cmd resolves the Chinese html name
$bat = "@echo off`r`nstart `"`" `"%~dp0" + $htmlName + "`"`r`n"
[System.IO.File]::WriteAllText($batPath, $bat, [System.Text.Encoding]::GetEncoding(936))
Write-Host ("BAT: {0}" -f $batPath)
