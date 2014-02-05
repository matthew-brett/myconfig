#!/bin/bash
./configure \
    --with-macarchs=x86_64 \
    --with-features=huge \
    --enable-pythoninterp=dynamic \
    --enable-perlinterp \
    --enable-cscope
