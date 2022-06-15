# Default powershell configuration.
Import-Module PSReadLine
Set-PSReadLineOption -EditMode vi

Set-PSReadLineKeyHandler -Key Ctrl+p -Function PreviousHistory
Set-PSReadLineKeyHandler -Key Ctrl+n -Function NextHistory

Set-PSReadLineOption -ViModeIndicator Cursor
Set-PSReadLineKeyHandler -Key Ctrl+[ -Function ViCommandMode

Set-Alias -Name which -Value get-command
Set-Alias -Name rmrf -Value "rm -r -Force"

# Python user path
try {
$site_dir = python -c 'import os, site; print(os.path.dirname(site.USER_SITE))'
$env:PATH = "$env:PATH;$site_dir\Scripts"
}
catch [System.Management.Automation.CommandNotFoundException]
{echo "No Python on path" }

$env:PATH = "$env:PATH;${HOME}\bin"

# This import is very slow.
# https://github.com/dahlbyk/posh-git
# PowerShellGet\Install-Module posh-git -Scope CurrentUser -Force
# Import-Module posh-git

# https://github.com/Pscx/Pscx
# https://stackoverflow.com/a/30122702
# Import-VisualStudioVars -Architecture amd64
# Install-Module Pscx -Scope CurrentUser -AllowClobber

# Also add this to Terminal settings
#
#        { "command": "nextTab", "keys": "win+shift+]" },
#        { "command": "prevTab", "keys": "win+shift+[" },

#  choco list --local-only
#
## Chocolatey v0.10.15
## chocolatey 0.10.15
## chocolatey-core.extension 1.3.5.1
## chocolatey-windowsupdate.extension 1.0.4
## git 2.33.1
## git.install 2.33.1
## hub 2.14.2
## KB2919355 1.0.20160915
## KB2919442 1.0.20160915
## KB2999226 1.0.20181019
## KB3033929 1.0.5
## KB3035131 1.0.3
## python 3.9.6
## python3 3.9.6
## ripgrep 13.0.0.20210621
## rust 1.55.0
## strawberryperl 5.32.1.1
## unxUtils 1.0.0.0
## unzip 6.0
## vcredist140 14.29.30133
## vcredist2015 14.0.24215.20170201
## vim 8.2.3510
## zip 3.0
## ... rtools
