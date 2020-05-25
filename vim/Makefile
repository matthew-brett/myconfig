# Makefile for vim directory

all: allhelp

general:
	git submodule update --init --recursive

allhelp:
	vim -c "call pathogen#helptags() | q"

helpfor-%:
	vim -c 'helptags bundle/$*/doc | q'
