" ftplugin for the Clang AST Matcher DSL.

if exists("b:did_ftplugin")
  finish
endif
let b:did_ftplugin = 1

setlocal comments=:#
setlocal commentstring=#\ %s
setlocal formatoptions-=t formatoptions+=croql
setlocal matchpairs=(:)
" attr::Override and CK_NullToPointer are single words for w/* and completion.
setlocal iskeyword+=:
setlocal iskeyword+=_

" <C-x><C-k> completes matcher names, settings and enum values from the
" generated word list.
let s:dict = expand('<sfile>:p:h:h') . '/dict/astmatcher.txt'
if filereadable(s:dict)
  execute 'setlocal dictionary+=' . fnameescape(s:dict)
  setlocal complete+=k
endif

" Optional: omni-completion (<C-x><C-o>) through the language server's batch
" interface. Opt in with  let g:astmatcher_omnifunc = 1
if get(g:, 'astmatcher_omnifunc', 0)
  setlocal omnifunc=astmatcher#Complete
endif

" :AstMatcherCheck — type-check the buffer into the quickfix list.
command! -buffer AstMatcherCheck call astmatcher#Check()

let b:undo_ftplugin = 'setlocal comments< commentstring< formatoptions<'
      \ . ' matchpairs< iskeyword< dictionary< complete< omnifunc<'
      \ . ' | delcommand AstMatcherCheck'
