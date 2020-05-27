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
# Accessibilty:
#   Turn on drag with drag lock in trackpad.
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
cd dev_trees

# The following needs a username and password, so run on its own.
hub clone myconfig

(cd myconfig && ./install)

# More utilities
brew install macvim bash-completion

# Set up configuration
cat >> ~/.bash_profile << EOF
# brew install bash-completion
[[ -r "/usr/local/etc/profile.d/bash_completion.sh" ]] && \
    . "/usr/local/etc/profile.d/bash_completion.sh"

# Default Python
PYTHON_EXE=python3
PIP_EXE=pip3

# Source personal definitions
if [ -f ~/.bash_personal ]; then
    . ~/.bash_personal
fi
EOF

# To get Python, pip binaries linked
source ~/.bash_profile

#
pip install --user virtualenvwrapper

# Other setup
brew cask install firefox
brew cask install hammerspoon quicksilver
# Start hammerspoon, enable accessibility, start at login
# Start quicksilver, enable shortcuts
brew install pandoc pandoc-citeproc
brew tap homebrew/cask-cask
brew cask install mactex
brew install cabal-install
brew install gnupg
brew install pinentry-mac
scp -r ${my_user}@tom.bic.berkeley.edu:.gnupg .
cat >> ~/.gnupg/gpg-agent.conf << EOF
pinentry-program /usr/local/bin/pinentry-curses
EOF

# Misc
ln -s "/System/Library/Automator/Combine PDF Pages.action/Contents/Resources/join.py" ~/usr/bin/pdfconcat
# Needs password
brew cask install virtualbox

brew cask install vagrant
brew cask install docker
brew install docker-machine
docker-machine create default
docker-machine create --driver virtualbox --virtualbox-memory 8096 default

pip install --user ipython
ipython profile create
# https://stackoverflow.com/questions/10394302/how-do-i-use-vi-keys-in-ipython-under-nix#38329940
# The below should be covered by dotbot myconfig
# cat >> ~/.ipython/profile_default/ipython_config.py << EOF
# c.TerminalInteractiveShell.editing_mode = 'vi'
# EOF
# # to copy, link, e.g
# mkdir -p .ipython .jupyter
# ln -s ~/dev_trees/myconfig/others/.jupyter/jupyter_notebook_config.sh ~/.jupyter
# ln -s ~/dev_trees/myconfig/others/.jupyter/jupyter_console_config.sh ~/.jupyter
# ln -s ~/dev_trees/myconfig/others/.jupyter/custom ~/.jupyter

# Consider
mkdir ~/gists
cd ~/gists
git clone https://gist.github.com/matthew-brett/2ad2081353ad468953da4eca1d9d2112 to_gist
ln -s ~/gists/to_gist/to_gist.sh ~/usr/bin

# Printing
# https://universityofbirmingham.service-now.com/itgateway/kb_view.do?sysparm_article=KB13216
