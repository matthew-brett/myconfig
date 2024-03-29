" This must be first, because it changes other options as side effect. In fact
" nocompatible is set just by the loading of a vimrc file, but not if the file
" is loaded with the command line -u file and other circumstances, so this is
" belt-and-braces
set nocompatible

" On Windows, also use ~/.vim instead of ~/vimfiles; this makes
" synchronization across (heterogeneous) systems easier.
" https://stackoverflow.com/a/53370672
if has('win32') || has('win64')
    let &runtimepath = substitute(&runtimepath, '\C\V' . escape($HOME.'/vimfiles', '\'), escape($HOME.'/.vim', '\&'), 'g')
    if exists('&packpath')
        let &packpath = &runtimepath
    endif
  " Avoid mswin.vim making Ctrl-v act as paste
  noremap <C-V> <C-V>
endif

" Use pathogen to easily modify the runtime path to include all
" plugins under the ~/.vim/bundle directory
runtime bundle/vim-pathogen/autoload/pathogen.vim
execute pathogen#infect()
execute pathogen#helptags()
" change the mapleader from \ to ,
let mapleader=","
" Quickly edit/reload the vimrc file
nmap <silent> <leader>ev :e $MYVIMRC<CR>
nmap <silent> <leader>sv :so $MYVIMRC<CR>
" Allow hiding of changed buffers
set hidden
" Use syntax
syntax on
" turn on indentation and filetypes
filetype plugin indent on
" set filename autocompletion to be bash-like
set wildmode=longest:full,full
set wildmenu
" Turn off everything gui
set guioptions=c
" Colors
if &t_Co >= 256 || has("gui_running")
   colorscheme mustang
endif
if &t_Co > 2 || has("gui_running")
   " switch syntax highlighting on, when the terminal has colors
   syntax on
endif
" Incrementral (smart) search
set incsearch
set ignorecase
set smartcase
set hlsearch      " highlight search terms
" Make sure I have at least a few lines of context when editing
set scrolloff=2
" Expand tabs by default
set expandtab
" Fancy statusbar from:
" http://got-ravings.blogspot.com/2008/08/vim-pr0n-making-statuslines-that-own.html
set statusline=%t       "tail of the filename
set statusline+=[%{strlen(&fenc)?&fenc:'none'}, "file encoding
set statusline+=%{&ff}] "file format
set statusline+=%h      "help file flag
set statusline+=%m      "modified flag
set statusline+=%r      "read only flag
set statusline+=%y      "filetype
set statusline+=%=      "left/right separator
set statusline+=%c,     "cursor column
set statusline+=%l/%L   "cursor line/total lines
set statusline+=\ %P    "percent through file
" Other settings from boosted-vim page (link above)
set nowrap        " don't wrap lines
set tabstop=4     " a tab is four spaces
set backspace=indent,eol,start
                  " allow backspacing over everything in insert mode
set autoindent    " always set autoindenting on
set copyindent    " copy the previous indentation on autoindenting
set shiftwidth=4  " number of spaces to use for autoindenting
set shiftround    " use multiple of shiftwidth when indenting with '<' and '>'
set showmatch     " set show matching parenthesis
set smarttab      " insert tabs on the start of a line according to
                  "    shiftwidth, not tabstop
set history=1000         " remember more commands and search history
set undolevels=1000      " use many muchos levels of undo
set wildignore=*.swp,*.bak,*.pyc,*.class
set title                " change the terminal's title
set visualbell           " don't beep
set noerrorbells         " don't beep
" No temporary files while editing
set nobackup
set noswapfile
" Vim can highlight whitespaces for you in a convenient way:
set list
set listchars=tab:>.,trail:.,extends:#,nbsp:.
" Not for html, xml
autocmd filetype html,xml set listchars-=tab:>.
" Clear highlighting of last search result
nmap <silent> ,/ :nohlsearch<CR>
" After testing for while, I decided not to
" Use semicolon as well as colon for command mode
" nnoremap ; :
" While learning - disable cursor keys
map <up> <nop>
map <down> <nop>
map <left> <nop>
map <right> <nop>
" From http://www.derekwyatt.org/vim/the-vimrc-file/my-vimrc-file/
" allow command line editing like emacs - see also help for emacs-keys
cnoremap <C-A>      <Home>
" These I use the cursor keys for; ctrl-F is the command line window anyway
" cnoremap <C-B>      <Left>
" cnoremap <C-F>      <Right>
cnoremap <C-N>      <Down>
cnoremap <C-P>      <Up>
cnoremap <ESC>b     <S-Left>
cnoremap <ESC><C-B> <S-Left>
cnoremap <ESC>f     <S-Right>
cnoremap <ESC><C-F> <S-Right>
cnoremap <ESC><C-H> <C-W>
" Maps to make handling windows a bit easier
noremap <silent> ,h :wincmd h<CR>
noremap <silent> ,j :wincmd j<CR>
noremap <silent> ,k :wincmd k<CR>
noremap <silent> ,l :wincmd l<CR>
noremap <silent> ,sb :wincmd p<CR>
noremap <silent> ,w :wincmd w<CR>
noremap <silent> ,x :wincmd x<CR>
noremap <silent> <C-F9>  :vertical resize -10<CR>
noremap <silent> <C-F10> :resize +10<CR>
noremap <silent> <C-F11> :resize -10<CR>
noremap <silent> <C-F12> :vertical resize +10<CR>
noremap <silent> ,s8 :vertical resize 83<CR>
noremap <silent> ,cj :wincmd j<CR>:close<CR>
noremap <silent> ,ck :wincmd k<CR>:close<CR>
noremap <silent> ,ch :wincmd h<CR>:close<CR>
noremap <silent> ,cl :wincmd l<CR>:close<CR>
noremap <silent> ,cc :close<CR>
noremap <silent> ,cw :cclose<CR>
noremap <silent> ,ml <C-W>L
noremap <silent> ,mk <C-W>K
noremap <silent> ,mh <C-W>H
noremap <silent> ,mj <C-W>J
noremap <silent> <C-7> <C-W>>
noremap <silent> <C-8> <C-W>+
noremap <silent> <C-9> <C-W>+
noremap <silent> <C-0> <C-W>>
" From http://dancingpenguinsoflight.com/2009/02/python-and-vim-make-your-own-ide
" Toggle line numbers and fold column for easy copying:
nnoremap <silent> ,po :set nonumber!<CR>:set foldcolumn=0<CR>
" Just toggle line numbers
nnoremap <silent> ,nn :set nonumber!<CR>
" Spelling
set spelllang=en_us
" Syntax sync
" http://vim.wikia.com/wiki/Fix_syntax_highlighting
nnoremap <silent> ,ss :syntax sync fromstart<CR>
" Light, dark background shortcuts
com! -nargs=* -count=0	LightBG colorscheme pyte
com! -nargs=* -count=0	DarkBG colorscheme mustang
" Setting the gui font - from help setting-guifont
if has("gui_running")
    if has("gui_win32")
        :set guifont=Lucida_Console:h16:cANSI
    elseif has("gui_macvim")
        :set guifont=Menlo\ Regular:h15
    endif
endif
" Join all lines within paragraph
" Modified from
" http://stackoverflow.com/questions/5651454/vim-join-all-lines-in-paragraph
nnoremap <silent> ,ll :%s/\(\S\)\n\(\S\)/\1 \2/<CR>:nohlsearch<CR>
" Highlight non-ascii characters
map ,uni :match Error /[\x7f-\xff]/<CR>
map ,uni2 /[^ -~]<CR>

" CDC = Change to Directory of Current file
" http://vim.wikia.com/wiki/Set_working_directory_to_the_current_file
" command! CDC ... overwrites any previous CDC command.  The advantage is that
" this file can be sourced more than once without error.
command! CDC cd %:p:h

" Emphasize cursor
function! DoCursorShow()
    redir => original_cursor
    silent execute "highlight Cursor"
    redir END
    let fg = matchstr(original_cursor, 'guifg=\S\+')
    let bg = matchstr(original_cursor, 'guibg=\S\+')
    let g:cursor_back_cmd = 'highlight Cursor ' . fg . ' ' . bg
    highlight Cursor guifg=orange guibg=steelblue
endfunction

" Back to previous cursor highlight
function! DoCursorBack()
    if exists("g:cursor_back_cmd")
        execute g:cursor_back_cmd
    endif
endfunction

command! CursorShow :call DoCursorShow()
command! CursorBack :call DoCursorBack()

nmap <silent> <leader>py :set ft=python<CR>
nmap <silent> <leader>md :set ft=markdown<CR>
nmap <silent> <leader>R :set ft=r<CR>
nmap <silent> <leader>rmd :set ft=rmd<CR>

" set nofoldenable    " disable folding in general.
" https://vim.fandom.com/wiki/All_folds_open_when_opening_a_file
" Disable folding for some files.
autocmd Syntax python,rmarkdown,pandoc,markdown setlocal foldmethod=syntax
autocmd Syntax python,rmarkdown,pandoc,markdown normal zR

" https://medium.com/usevim/vim-101-virtual-editing-661c99c05847
" Allow block mode definitions in empty space.
set virtualedit=block

" =================================
"  configure plugins
" =================================
" Yankring
let g:yankring_history_file = '.yankring_history'
let g:yankring_min_element_length = 2
" Supertab
let g:SuperTabDefaultCompletionType = "context"
let g:SuperTabContextDefaultCompletionType="<c-x><c-o>"
" Chapa function / class / method movement
let g:chapa_default_mappings = 1
" Vinarise
let g:vinarise_enable_auto_detect = 1
" Turn off conceal stuff for pandoc
let g:pandoc#syntax#conceal#use = 0
" Syntax highlighting for some lanaguages
let g:pandoc#syntax#codeblocks#embeds#langs = ["python"]
" File types for jinja detection
au BufNewFile,BufRead *.html,*.htm,*.shtml,*.stm,*.tpl set ft=jinja
" Binding for pep8 checking
let g:pep8_map="<leader>8"
" https://www.wezm.net/technical/2016/09/ripgrep-with-vim/
if executable("rg")
    set grepprg=rg\ --vimgrep\ --no-heading
    set grepformat=%f:%l:%c:%m,%f:%l:%m
endif
" Python syntax highlighting
let python_highlight_all = 1
" RST processors
let g:rst_prefer_python_version = 3
" Pyflakes
let g:pyflakes_prefer_python_version = 3
" pandoc
let g:pandoc#modules#disabled = ["chdir"]
" https://github.com/vim-pandoc/vim-pandoc/issues/23
let g:pandoc#modules#disabled = ["folding"]
" Disable markdown folding
" https://stackoverflow.com/questions/5017009/confusion-about-vim-folding-how-to-disable
let g:vim_markdown_folding_disabled = 1
" Hard line wraps, autoformatting
" let g:pandoc#formatting#mode = 'hA'
" let g:pandoc#formatting#textwidth = 78

" Dual monitor setup
" :set guifont to see current font size
nnoremap <silent> <leader>ff :set guifont=Menlo\ Regular:h19<CR>
nnoremap <silent> <leader>fs :set guifont=Menlo\ Regular:h19 \| :wincmd v \| :wincmd v \| :wincmd v \| wincmd =<CR>
nnoremap <silent> <leader>ww :exe 1 "wincmd w"<CR>:vertical resize 80<CR>:wincmd l<CR>:vertical resize 89<CR>:wincmd l<CR>:vertical resize 80<CR>

" Avoid gopass secret leak
" https://github.com/gopasspw/gopass/blob/master/docs/setup.md#securing-your-editor
au BufNewFile,BufRead /dev/shm/gopass.* setlocal noswapfile nobackup noundofile
au BufNewFile,BufRead /private/**/gopass** setlocal noswapfile nobackup noundofile

" Ultisnips
let g:UltiSnipsExpandTrigger="<tab>"
" List all snippets for current filetype
let g:UltiSnipsListSnippets=",sl"

" Setting syntax
nnoremap <silent> <leader>sp :set ft=python<CR>
nnoremap <silent> <leader>sr :set ft=rmarkdown<CR>

" add keymappings in goneovim only
if exists("g:goneovim")
  " set CMD+V to paste in all modes
  nnoremap <D-v> a<C-r>+<Esc>
  inoremap <D-v> <C-r>+
  cnoremap <D-v> <C-r>+
endif
