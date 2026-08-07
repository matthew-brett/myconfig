" Performance tuning for vim-pandoc-syntax on long prose .pdc files.
" pandoc.vim already runs `syntax sync clear`; override its minlines=1000.
syntax sync minlines=100
syntax sync maxlines=250
