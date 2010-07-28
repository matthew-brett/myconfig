# Makefile to do stuff with configurations

DOTBACKUP = $(HOME)/.backup_dotfiles
DOTFILES = bash_personal bash_utils gitconfig noserc gnomerc hgrc git-completion \
	   vimrc vim
VENV_DIR = $(HOME)/.virtualenvs
VIM_DIR = $(HOME)/.vim

dotfiles: backup_directory
	for filename in $(DOTFILES); do \
	cp -r $(HOME)/.$${filename} $(DOTBACKUP)/$${filename}; \
	cp -r dotfiles/$${filename} $(HOME)/.$${filename}; \
	done ;

backup_directory:
	- mkdir $(DOTBACKUP)

virtualenvs:
	- mkdir $(VENV_DIR)
	cp -r virtualenvs/* $(VENV_DIR)
	ln -s `python -c 'import os; import IPython; print os.path.dirname(IPython.__file__)'` $(VENV_DIR)/virtual-packages/IPython

vim:
	- mkdir $(VIM_DIR)
	cp -r vim/* $(VIM_DIR)

.PHONY: virtualenvs vim
