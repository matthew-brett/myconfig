# Makefile to do stuff with configurations

DOTBACKUP = $(HOME)/.backup_dotfiles
DOTFILES = bash_personal bash_osx bash_linux gitconfig noserc gnomerc hgrc \
		   git-completion screenrc muttrc gitglobalignore
VENV_DIR = $(HOME)/.virtualenvs

dotfiles: backup_directory bzrcfg vmailcfg
	for filename in $(DOTFILES); do \
	mv $(HOME)/.$${filename} $(DOTBACKUP)/$${filename}; \
	cp dotfiles/$${filename} $(HOME)/.$${filename}; \
	done ;

bzrcfg : dotfiles/bazaar.conf
	- mv $(HOME)/.bazaar/bazaar.conf $(DOTBACKUP)/bazaar.conf
	- mkdir $(HOME)/.bazaar
	cp dotfiles/bazaar.conf $(HOME)/.bazaar

vmailcfg : dotfiles/vmailrc
	- mv $(HOME)/.vmail/default/.vmailrc $(DOTBACKUP)/vmailrc
	- mkdir -p $(HOME)/.vmail/default
	cp dotfiles/vmailrc $(HOME)/.vmail/default/.vmailrc

backup_directory:
	- mkdir $(DOTBACKUP)

virtualenvs:
	- mkdir $(VENV_DIR)
	cp -r virtualenvs/* $(VENV_DIR)

.PHONY: virtualenvs
