# Spacemacs
cd ~/dev_trees
git clone https://github.com/syl20bnr/spacemacs --branch develop
ln -s ~/dev_trees/spacemacs ~/.emacs.d
# emacs-plus for optional dependencies of emacs
brew tap d12frosted/emacs-plus
brew install emacs-plus
# source code pro as default font
# https://github.com/syl20bnr/spacemacs/issues/3006#issuecomment-282516801
brew tap homebrew/cask-fonts
brew cask install font-source-code-pro --fontdir=/Library/Fonts
