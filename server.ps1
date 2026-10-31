$root = $PSScriptRoot
$listener = New-Object System.Net.HttpListener
$listener.Prefixes.Add("http://localhost:8765/")
$listener.Start()
Write-Host "Serving $root at http://localhost:8765/"
while ($listener.IsListening) {
  try {
    $ctx = $listener.GetContext()
    $raw = ($ctx.Request.RawUrl -replace '\?.*$','').TrimStart('/')
    $url = [System.Uri]::UnescapeDataString($raw)
    if ($url -eq '') { $url = 'app.html' }
    $file = Join-Path $root ($url -replace '/','\')
    if (Test-Path -LiteralPath $file -PathType Leaf) {
      $bytes = [System.IO.File]::ReadAllBytes($file)
      $ext = [System.IO.Path]::GetExtension($file).ToLower()
      $mime = switch ($ext) {
        '.html' { 'text/html; charset=utf-8' }
        '.js'   { 'application/javascript; charset=utf-8' }
        '.json' { 'application/json; charset=utf-8' }
        default { 'application/octet-stream' }
      }
      $ctx.Response.ContentType = $mime
      $ctx.Response.Headers.Add('Cache-Control','no-store')
      $ctx.Response.ContentLength64 = $bytes.Length
      $ctx.Response.OutputStream.Write($bytes,0,$bytes.Length)
    } else {
      $ctx.Response.StatusCode = 404
    }
    $ctx.Response.OutputStream.Close()
    $ctx.Response.Close()
  } catch {
    Write-Host $_.Exception.Message
  }
}
