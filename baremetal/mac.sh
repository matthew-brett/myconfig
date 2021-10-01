# First - update to latest macOS

# Download Vladstudio wallpapers

# Turn on tap click on trackpad settings
# Mission control:
#   Enable spaces via Mission Control (? still relevant).
#   Disable "Displays have separate spaces".
# Start Mission Control (F3), then add as many desktops as necessary.
#
# Keyboard:
#   Turn off Caps Lock with Modifier Keys
#   Turn on shortcuts for desktops with Keyboard Shortcuts
#   Check "Use keyboard navigation to move focus between controls".
# Accessibilty:
#   Turn on "drag without drag lock" in Pointer Control -> Trackpad options.
# Sharing:
#   Enable ssh via sharing menu

# Open Finder, go to preferences, add home folder and hard disks to sidebar

# To stick with bash
chsh -s /bin/bash
# You will also need the followinng in your .bash_profile
# export BASH_SILENCE_DEPRECATION_WARNING=1
# See: https://support.apple.com/en-gb/HT208050

# Set up a Mac from bare OS install
my_user="my_user"

# Make some useful directories
cd
mkdir -p .ssh usr/bin dev_trees tmp

# Set up ssh
scp ${my_user}@tom.bic.berkeley.edu:.ssh/id_rsa* .ssh
ssh-add
scp ${my_user}@tom.bic.berkeley.edu:.ssh/config .ssh

# Check that xcode command line tools are installed
xcode-select --install

# Install homebrew
# Run on its own - needs RETURN
/usr/bin/ruby -e "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/master/install)"

# Then
brew update

# Get configuration
# Python 3 is the default now
brew install python hub
# More utilities
brew install macvim bash-completion

cd dev_trees

# The following needs a username and password, so run on its own.
hub clone myconfig

(cd myconfig && ./install)

# Edit mac_bash_profile to taste and copy to ~
# Make sure PYTHON and PIP_EXE set, as in:
# # Default Python
# PYTHON_EXE=python3
# PIP_EXE=pip3

# To get Python, pip binaries linked
source ~/.bash_profile

# Basic Python setup
pip install --user virtualenvwrapper
pip install --user ipython
ipython profile create

# Other setup
brew cask install firefox
brew cask install hammerspoon quicksilver
# Start hammerspoon, enable accessibility, start at login
# Start quicksilver, preferences, start at login, show icon in menu bar
# Add shortcuts.
brew install pandoc pandoc-citeproc
brew tap homebrew/cask-cask
brew install gnupg pinentry-mac
# This one takes ages.
brew install --cask mactex-no-gui

# Misc
ln -s "/System/Library/Automator/Combine PDF Pages.action/Contents/Resources/join.py" ~/usr/bin/pdfconcat

# Needs password
brew cask install virtualbox

brew cask install vagrant
brew cask install docker
# Open, allow docker desktop to initialize.
open -a docker
# Then
docker run -ti --rm debian:stable /bin/bash

# Install:
# https://karabiner-elements.pqrs.org

# Consider
mkdir ~/gists
cd ~/gists
git clone https://gist.github.com/matthew-brett/2ad2081353ad468953da4eca1d9d2112 to_gist
ln -s ~/gists/to_gist/to_gist.sh ~/usr/bin

# UoB printing
# https://universityofbirmingham.service-now.com/itgateway/kb_view.do?sysparm_article=KB13216
brew install gopass gopass-jsonapi
# https://github.com/gopasspw/gopass/blob/master/docs/setup.md#filling-in-passwords-from-browser
gopass clone freshpi:repos/gopass.git
scp -r lockdowns:.gnupg/* ~/.gnupg

# Turn off any annoying keyboard shortcuts in
# Preferences - Keyboard - Text
# Especially - two spaces -> . 
