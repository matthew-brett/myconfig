# Makefile to do stuff with configurations

DOTBACKUP = $(HOME)/.backup_dotfiles
DOTFILES = bash_personal bash_utils gitconfig noserc gnomerc hgrc git-completion
VENV_DIR = $(HOME)/.virtualenvs

dotfiles: backup_directory
	for filename in $(DOTFILES); do \
	mv $(HOME)/.$${filename} $(DOTBACKUP)/$${filename}; \
	cp dotfiles/$${filename} $(HOME)/.$${filename}; \
	done ;

backup_directory:
	- mkdir $(DOTBACKUP)

virtualenvs:
	- mkdir $(VENV_DIR)
	cp -r virtualenvs/* $(VENV_DIR)
	ln -s `python -c 'import os; import IPython; print os.path.dirname(IPython.__file__)'` $(VENV_DIR)/virtual-packages/IPython

.PHONY: virtualenvs 
