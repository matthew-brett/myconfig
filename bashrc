# ~/.bashrc: executed by bash(1) for non-login shells.
# see /usr/share/doc/bash/examples/startup-files (in the package bash-doc)
# for examples

# If not running interactively, don't do anything
[ -z "$PS1" ] && return

# don't put duplicate lines in the history. See bash(1) for more options
export HISTCONTROL=ignoredups
# ... and ignore same sucessive entries.
export HISTCONTROL=ignoreboth

# check the window size after each command and, if necessary, update the
# values of LINES and COLUMNS.
shopt -s checkwinsize

# make less more friendly for non-text input files, see lesspipe(1)
[ -x /usr/bin/lesspipe ] && eval "$(SHELL=/bin/sh lesspipe)"

# set variable identifying the chroot you work in (used in the prompt
# below)
if [ -z "$debian_chroot" ] && [ -r /etc/debian_chroot ]; then
    debian_chroot=$(cat /etc/debian_chroot)
fi

# set a fancy prompt (non-color, unless we know we "want" color)
case "$TERM" in
    xterm-color) color_prompt=yes;;
esac

# uncomment for a colored prompt, if the terminal has the capability; turned
# off by default to not distract the user: the focus in a terminal window
# should be on the output of commands, not on the prompt
#force_color_prompt=yes

if [ -n "$force_color_prompt" ]; then
    if [ -x /usr/bin/tput ] && tput setaf 1 >&/dev/null; then
	# We have color support; assume it's compliant with Ecma-48
	# (ISO/IEC-6429). (Lack of such support is extremely rare, and such
	# a case would tend to support setf rather than setaf.)
	color_prompt=yes
    else
	color_prompt=
    fi
fi

if [ "$color_prompt" = yes ]; then
    PS1='${debian_chroot:+($debian_chroot)}\[\033[01;32m\]\u@\h\[\033[00m\]:\[\033[01;34m\]\w\[\033[00m\]\$ '
else
    PS1='${debian_chroot:+($debian_chroot)}\u@\h:\w\$ '
fi
unset color_prompt force_color_prompt

# If this is an xterm set the title to user@host:dir
case "$TERM" in
xterm*|rxvt*)
    PROMPT_COMMAND='echo -ne "\033]0;${USER}@${HOSTNAME}: ${PWD/$HOME/~}\007"'
    ;;
*)
    ;;
esac

# Alias definitions.
# You may want to put all your additions into a separate file like
# ~/.bash_aliases, instead of adding them here directly.
# See /usr/share/doc/bash-doc/examples in the bash-doc package.

#if [ -f ~/.bash_aliases ]; then
#    . ~/.bash_aliases
#fi

# enable color support of ls and also add handy aliases
if [ "$TERM" != "dumb" ] && [ -x /usr/bin/dircolors ]; then
    eval "`dircolors -b`"
    alias ls='ls --color=auto'
    #alias dir='ls --color=auto --format=vertical'
    #alias vdir='ls --color=auto --format=long'

    #alias grep='grep --color=auto'
    #alias fgrep='fgrep --color=auto'
    #alias egrep='egrep --color=auto'
fi

# some more ls aliases
alias ll='ls -l'
alias apt-up='sudo apt-get update;sudo apt-get -y --force-yes dselect-upgrade'
#alias la='ls -A'
#alias l='ls -CF'

# latex
export TEXINPUTS=".:~/tex:"

# CIRL SVN directory
svncirl=https://cirl.berkeley.edu/admin-svn/

# Editor
export EDITOR=jed

# enable programmable completion features (you don't need to enable
# this, if it's already enabled in /etc/bash.bashrc and /etc/profile
# sources /etc/bash.bashrc).
if [ -f /etc/bash_completion ]; then
    . /etc/bash_completion
fi

############################################################################
# Source global definitions
if [ -f /etc/bashrc ]; then
        . /etc/bashrc
fi

############################################################################
#
# Load basic bash utilities (handy functions and constants)
#
. $HOME/.bash_utils

############################################################################
#
# Configure paths, using the path generation functions in .bash_utils
#
# These are the prefixes I typically use as --prefix options for installation
# of packages.  There's a method to the madness of having several of them, and
# in this order.  The ones at the top end up first in the generated path specs,
# so they take precedence.
pfx="$pfx $HOME/tmp/junk"  # quick and dirty testing
pfx="$pfx $HOME/tmp/local"  # temporary, stable testing
pfx="$pfx $HOME/usr"  # codes *I* have written
pfx="$pfx $HOME/usr/opt"  # I don't sync this across computers
pfx="$pfx $HOME/usr/local"  # default prefix for third-party installs
pfx="$pfx /local"  # used in some machines I work on
pfx="$pfx /opt"  # vendor directory for commercial stuff

# Initialize $PATH with sbin locations so I can find system tools
export PATH=/usr/local/sbin:/usr/sbin:/sbin:$PATH

# Now, set all common paths based on the prefix list just built.  The
# export_paths function ensures that all commonly needed paths get correctly
# set and exported to the environment.
export_paths "$pfx"

# Make 2.4 and 2.5 specific ones, so it's easy to switch with a simple alias
PYTHONPATH24=`mk_pythonpath "$pfx" 2.4`
PYTHONPATH25=`mk_pythonpath "$pfx" 2.5`

# Search paths for LaTeX (Dont' forget the final colons.  The null entry `::'
# denotes `default system directories' -- try finding that in the
# documentation.)  Note that these *must* go under ~/texmf, because that
# particular path is hardcoded in LaTeX and is not overridable by the user.
# While one could keep ~/texmf for default package installs and use other
# locations for {tex/bib/bst}inputs, I prefer to centralize all Tex stuff in
# one place.  Since I can't do it in ~/usr/tex, then I'll just keep everything
# TeX related in ~/texmf
export TEXINPUTS=.:$HOME/texmf/texinputs::
export BIBINPUTS=.:$HOME/texmf/bibinputs::
export BSTINPUTS=.:$HOME/texmf/bstinputs::

############################################################################

export MATLABPATH=$HOME/matlab:$HOME/matlab/m2html