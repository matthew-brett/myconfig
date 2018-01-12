# Set up a Mac Pro from bare OS install

# Make some useful directories
cd
mkdir -p .ssh usr/bin dev_trees tmp

# Set up ssh
scp mb312@dans.dyn.berkeley.edu:.ssh/id_rsa* .ssh
ssh-add
scp mb312@dans.dyn.berkeley.edu:.ssh/config .ssh

# Check that xcode command line tools are installed
xcode-select --install

# Install homebrew
# Run on its own - needs RETURN
/usr/bin/ruby -e "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/master/install)"

# Then
brew update

# Get configuration
brew install python3 hub
cd dev_trees

# The following needs a username and password, so run on its own.
hub clone myconfig

(cd myconfig && make dotfiles)
hub clone myvim
(cd myvim && git submodule update --init --recursive && make links)

# More utilities
brew install vim && brew install macvim

# Set up configuration
cat >> ~/.bash_profile << EOF
# Source personal definitions
if [ -f ~/.bash_personal ]; then
    . ~/.bash_personal
fi

# To source stuff for docker machine
alias idocker="eval \$(docker-machine env)"
EOF

pip3 install virtualenvwrapper

# Other setup
brew install bash-completion
brew cask install firefox
brew install pandoc
brew install pandoc-citeproc
brew tap caskroom/cask
brew cask install mactex
brew install cabal
brew install gnupg
brew install pinentry-mac
scp -r mb312@dans.dyn.berkeley.edu:.gnupg .

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

# Printing
# https://universityofbirmingham.service-now.com/itgateway/kb_view.do?sysparm_article=KB13216
