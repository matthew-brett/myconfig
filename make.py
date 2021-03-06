#!python
""" Python makefile for windows sort-of making """

import os
from os.path import join as pjoin, dirname, expanduser, isfile
import sys
from shutil import copyfile

HERE = dirname(__file__)
HOME = expanduser('~')
IO_ERRORS = (IOError, OSError)
if sys.platform == 'win32':
    DOTBACKUP = pjoin(HOME, '_backup_dotfiles')
    APPDATA = os.environ['APPDATA']
    BZRDIR = pjoin(APPDATA, 'bazaar', '2.0')
    IO_ERRORS += (WindowsError,)
else:
    DOTBACKUP = pjoin(HOME, '.backup_dotfiles')
    BZRDIR = pjoin(HOME, '.bazaar')
DOTFILE_MAP = [('gitconfig', '.gitconfig'),
               ('git-completion', '.git-completion'),
               ('noserc', 'nose.cfg'),
               ('bash_personal', '.bash_personal'),
               ('bash_osx', '.bash_osx'),
               ('bash_linux', '.bash_linux'),
               ('hgrc', '.hgrc'),
               ('screenrc', '.screenrc'),
               ('inputrc', '.inputrc'),
               ('gitglobalignore', '.gitglobalignore'),
               ('bash_keychain_lite', '.bash_keychain_lite'),
               ('Rprofile', '.Rprofile')]

def backupdir():
    try:
        os.mkdir(DOTBACKUP)
    except IO_ERRORS:
        pass


def ordinary_dotfiles():
    for in_fname, out_fname in DOTFILE_MAP:
        in_full = pjoin(HERE, 'dotfiles', in_fname)
        out_full = pjoin(HOME, out_fname)
        bak_full = pjoin(DOTBACKUP, out_fname)
        if isfile(out_full):
            if isfile(bak_full):
                os.unlink(bak_full)
                os.rename(out_full, bak_full)
        copyfile(in_full, out_full)


def bzrfile():
    try:
        os.makedirs(BZRDIR)
    except IO_ERRORS:
        pass
    bzrconf = 'bazaar.conf'
    in_full = pjoin('dotfiles', bzrconf)
    out_full = pjoin(BZRDIR, bzrconf)
    bak_full = pjoin(DOTBACKUP, bzrconf)
    if isfile(out_full):
        if isfile(bak_full):
            os.unlink(bak_full)
        os.rename(out_full, bak_full)
    copyfile(in_full, out_full)


def main():
    try:
        target = sys.argv[1]
    except IndexError:
        target = 'dotfiles'
    if target == 'dotfiles':
        backupdir()
        ordinary_dotfiles()
        bzrfile()
    else:
        raise RuntimeError('Confused by target "%s"' % target)


if __name__ == '__main__':
    main()
