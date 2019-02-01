# Set up a Mac from bare OS install

# Make some useful directories
cd
mkdir -p .ssh usr/bin dev_trees tmp

# Set up ssh
scp mb312@tom.bic.berkeley.edu:.ssh/id_rsa* .ssh
ssh-add
scp mb312@tom.bic.berkeley.edu:.ssh/config .ssh

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

(cd myconfig && make dotfiles)
hub clone myvim
(cd myvim && git submodule update --init --recursive && make links)

# More utilities
brew install vim && brew install macvim

# Bash completion
brew install bash-completion

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
brew install pandoc
brew install pandoc-citeproc
brew tap caskroom/cask
brew cask install mactex
brew install cabal
brew install gnupg
brew install pinentry-mac
scp -r mb312@tom.bic.berkeley.edu:.gnupg .

# Misc
ln -s "/System/Library/Automator/Combine PDF Pages.action/Contents/Resources/join.py" ~/usr/bin/pdfconcat
# Needs password
brew cask install virtualbox

brew cask install vagrant
brew cask install docker
brew install docker-machine
docker-machine create default
docker-machine create --driver virtualbox --virtualbox-memory 8096 default

# Enable spaces via Mission Control
# Turn off Caps Lock with Keyboard Settings Modifier Keys
# Turn on shortcuts for desktops with Keyboard Shortcuts
# Turn on tap click on trackpad settings
# Turn on drag / drop trackpad from Accessibilty
# Usual dance to install Vladstudio wallpapers
# Enable ssh via sharing menu
# Finder preferences, add home folder and hard disks to sidebar

pip install --user ipython
# https://stackoverflow.com/questions/10394302/how-do-i-use-vi-keys-in-ipython-under-nix#38329940
ipython profile create
cat >> ~/.ipython/profile_default/ipython_config.py << EOF
c.TerminalInteractiveShell.editing_mode = 'vi'
EOF

# Look in ~/dev_trees/myconfig/others for other settings
# to copy, link, e.g
mkdir -p .ipython .jupyter
ln -s ~/dev_trees/myconfig/others/.jupyter/jupyter_notebook_config.sh ~/.jupyter
ln -s ~/dev_trees/myconfig/others/.jupyter/custom ~/.jupyter

# Consider
mkdir ~/gists
cd ~/gists
git clone https://gist.github.com/matthew-brett/2ad2081353ad468953da4eca1d9d2112 to_gist
ln -s ~/gists/to_gist/to_gist.sh ~/usr/bin

# Printing
# https://universityofbirmingham.service-now.com/itgateway/kb_view.do?sysparm_article=KB13216
