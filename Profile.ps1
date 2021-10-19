# Default powershell configuration.
Import-Module PSReadLine
Set-PSReadLineOption -EditMode vi

Set-PSReadLineKeyHandler -Key Ctrl+p -Function PreviousHistory
Set-PSReadLineKeyHandler -Key Ctrl+n -Function NextHistory
Set-PSReadLineKeyHandler -Key Ctrl+c -Function Copy
Set-PSReadLineKeyHandler -Key Ctrl+v -Function Paste

Set-PSReadLineOption -ViModeIndicator Cursor
Set-PSReadLineKeyHandler -Key Ctrl+[ -Function ViCommandMode
