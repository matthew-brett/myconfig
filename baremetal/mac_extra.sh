# Spacemacs
cd ~/dev_trees
git clone https://github.com/syl20bnr/spacemacs
ln -s ~/dev_trees/spacemacs ~/.emacs.d
brew install emacs-plus
# https://github.com/syl20bnr/spacemacs/issues/3006#issuecomment-282516801
brew tap homebrew/cask-fonts
brew cask install font-source-code-pro --fontdir=/Library/Fonts
