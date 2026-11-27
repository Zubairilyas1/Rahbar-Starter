# Real terminal screenshots for the report appendix (Assignment 03).
# Opens a new PowerShell console, echoes and runs the command there, then captures
# that window from the screen (PrintWindow). Long lines are wrapped to the visible
# width (as a terminal wraps them) so nothing is cropped; it warns if output is
# taller than the window. Example:
#   .\scripts\capture_terminal.ps1 -Command "kubectl get all -n rahbar" -Out docs\evidence\a3\F-get-all.png
param(
    [Parameter(Mandatory)][string]$Command,   # the command, run in a fresh PowerShell console window
    [Parameter(Mandatory)][string]$Out,       # PNG path
    [int]$Cols = 205,                         # fits a 1536 px screen at Consolas 12 px
    [int]$WaitSeconds = 30,
    [int]$FontPx = 12,
    [int]$Wrap = 0,                           # hard-wrap width; 0 = auto from font
    [string]$WorkDir = (Split-Path -Parent $PSScriptRoot)
)
# Opens a real console window, runs the command there (the prompt + command are
# echoed first, like a typed command), waits for it to finish, then captures the
# window from the screen. Writes the number of output rows next to the PNG and
# warns when the output is taller than the window (would be cropped).
Add-Type -AssemblyName System.Drawing
Add-Type @"
using System; using System.Runtime.InteropServices;
public class W {
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h, IntPtr hdc, uint f);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool MoveWindow(IntPtr h, int x, int y, int w, int hh, bool r);
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int L, T, R, B; }
}
"@
if ($Wrap -le 0) { $Wrap = if ($FontPx -le 10) { 160 } elseif ($FontPx -le 11) { 148 } else { 135 } }
$done = Join-Path $env:TEMP ("shot_done_" + [guid]::NewGuid().ToString("N"))
$title = "Windows PowerShell"
$tag = [guid]::NewGuid().ToString("N").Substring(0, 8)
$inner = @"
`$host.UI.RawUI.WindowTitle = 'Windows PowerShell ($tag)'
Add-Type -TypeDefinition 'using System; using System.Runtime.InteropServices;
public class CF { [StructLayout(LayoutKind.Sequential, CharSet=CharSet.Unicode)] public struct FI { public int cbSize; public int n; public short x; public short y; public int fam; public int w; [MarshalAs(UnmanagedType.ByValTStr, SizeConst=32)] public string face; }
[DllImport("kernel32.dll", SetLastError=true)] public static extern IntPtr GetStdHandle(int h);
[DllImport("kernel32.dll", SetLastError=true, CharSet=CharSet.Unicode)] public static extern bool SetCurrentConsoleFontEx(IntPtr h, bool max, ref FI f);
public static void Set(short px) { FI f = new FI(); f.cbSize = Marshal.SizeOf(f); f.x = 0; f.y = px; f.fam = 54; f.w = 400; f.face = "Consolas"; SetCurrentConsoleFontEx(GetStdHandle(-11), false, ref f); } }'
[CF]::Set($FontPx)
Start-Sleep -Milliseconds 1200
`$max = `$host.UI.RawUI.MaxPhysicalWindowSize
`$c = if ($Cols -gt 0) { [Math]::Min($Cols, `$max.Width - 1) } else { `$max.Width - 1 }
try { `$host.UI.RawUI.WindowSize = New-Object Management.Automation.Host.Size(40, 20) } catch {}
try { `$host.UI.RawUI.BufferSize = New-Object Management.Automation.Host.Size(`$c, 3000) } catch {}
foreach (`$rows in ([int](700 / ($FontPx + 2.5)))..20) { try { `$host.UI.RawUI.WindowSize = New-Object Management.Automation.Host.Size(`$c, `$rows); break } catch {} }
`$ww = `$host.UI.RawUI.WindowSize.Width
try { `$host.UI.RawUI.BufferSize = New-Object Management.Automation.Host.Size(`$ww, 3000) } catch {}
Set-Location '$WorkDir'
Clear-Host
`$cmdText = @'
$Command
'@
`$echo = 'PS ' + (Get-Location).Path + '> ' + `$cmdText.Trim()
for (`$i = 0; `$i -lt `$echo.Length; `$i += $Wrap) { Write-Host `$echo.Substring(`$i, [Math]::Min($Wrap, `$echo.Length - `$i)) }
& { $Command } 2>&1 | ForEach-Object { if (`$_ -is [System.Management.Automation.ErrorRecord]) { `$_.Exception.Message } else { `$_ } } | Out-String -Stream -Width 4096 | ForEach-Object { `$l = [string]`$_; if (`$l.Length -eq 0) { '' } else { for (`$i = 0; `$i -lt `$l.Length; `$i += $Wrap) { `$l.Substring(`$i, [Math]::Min($Wrap, `$l.Length - `$i)) } } } | Out-Host
Write-Host ('PS ' + (Get-Location).Path + '> ') -NoNewline
(`$host.UI.RawUI.CursorPosition.Y + 1).ToString() + ' ' + `$host.UI.RawUI.WindowSize.Height | Set-Content '$done'
"@
$enc = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($inner))
Start-Process conhost.exe -ArgumentList "powershell.exe -NoLogo -NoExit -EncodedCommand $enc" | Out-Null
$t = 0
while (-not (Test-Path $done) -and $t -lt $WaitSeconds * 2) { Start-Sleep -Milliseconds 500; $t++ }
Start-Sleep -Milliseconds 1000
$h = [IntPtr]::Zero
foreach ($i in 1..30) {
  $w = Get-Process | Where-Object { $_.MainWindowTitle -like "*($tag)*" } | Select-Object -First 1
  if ($w) { $h = $w.MainWindowHandle; break }
  Start-Sleep -Milliseconds 300
}
if ($h -eq [IntPtr]::Zero) { Write-Error "window not found"; exit 1 }
$r0 = New-Object W+RECT; [W]::GetWindowRect($h, [ref]$r0) | Out-Null
[W]::MoveWindow($h, 0, 0, ($r0.R - $r0.L), ($r0.B - $r0.T), $true) | Out-Null
[W]::SetForegroundWindow($h) | Out-Null
Start-Sleep -Milliseconds 700
$r = New-Object W+RECT; [W]::GetWindowRect($h, [ref]$r) | Out-Null
$bmp = New-Object Drawing.Bitmap ($r.R - $r.L), ($r.B - $r.T)
$g = [Drawing.Graphics]::FromImage($bmp); $hdc = $g.GetHdc()
[W]::PrintWindow($h, $hdc, 2) | Out-Null
$g.ReleaseHdc($hdc); $g.Dispose()
New-Item -ItemType Directory -Force (Split-Path $Out) | Out-Null
$bmp.Save($Out, [Drawing.Imaging.ImageFormat]::Png); $bmp.Dispose()
$info = if (Test-Path $done) { Get-Content $done } else { "unknown (command still running after $WaitSeconds s)" }
Remove-Item $done -ErrorAction SilentlyContinue
Get-Process | Where-Object { $_.MainWindowTitle -like "*($tag)*" } | Stop-Process -Force
$parts = "$info".Split(' ')
if ($parts.Count -eq 2 -and [int]$parts[0] -gt [int]$parts[1]) { "WARNING: output rows $($parts[0]) > window rows $($parts[1]) -> cropped" }
"saved $Out (rows used / window rows: $info)"
