#!/bin/bash
export HOMEBREW_PREFIX=$(brew --prefix)
if [ -n $HOMEBREW_PREFIX ]; then
    envsubst < gpg-agent-mac.conf.tpl > gpg-agent-mac.conf.built
fi
