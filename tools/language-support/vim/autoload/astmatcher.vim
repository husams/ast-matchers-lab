" Optional bridge to astmatcher-lsp's batch interface, for users who do not run
" an LSP client. Everything here is opt-in; the syntax file needs none of it.

" …/tools/language-support/vim/autoload/ -> …/tools/language-support. Expanded
" here: inside a function <sfile> is the call stack, not this file.
let s:root = expand('<sfile>:p:h:h:h')

function! s:Server() abort
  if exists('g:astmatcher_lsp')
    return g:astmatcher_lsp
  endif
  let l:path = s:root . '/astmatcher-lsp/bin/astmatcher-lsp'
  return executable(l:path) ? l:path : 'astmatcher-lsp'
endfunction

" Type-check the current buffer into the quickfix list.
function! astmatcher#Check() abort
  let l:server = s:Server()
  if !executable(l:server)
    echohl WarningMsg | echo 'astmatcher-lsp not found' | echohl None
    return
  endif
  let l:lines = system(shellescape(l:server) . ' --check -', join(getline(1, '$'), "\n"))
  let l:items = []
  for l:line in split(l:lines, "\n")
    let l:m = matchlist(l:line, '^-:\(\d\+\):\(\d\+\): \(\w\+\): \(.*\)$')
    if !empty(l:m)
      call add(l:items, {'bufnr': bufnr('%'), 'lnum': str2nr(l:m[1]),
            \ 'col': str2nr(l:m[2]), 'type': l:m[3] ==# 'error' ? 'E' : 'W',
            \ 'text': l:m[4]})
    endif
  endfor
  call setqflist(l:items, 'r')
  if empty(l:items)
    echo 'astmatcher: no problems found'
  else
    copen
  endif
endfunction

" omnifunc: ask the server what belongs at the cursor.
function! astmatcher#Complete(findstart, base) abort
  if a:findstart
    let l:line = getline('.')
    let l:start = col('.') - 1
    while l:start > 0 && l:line[l:start - 1] =~# '[A-Za-z0-9_:]'
      let l:start -= 1
    endwhile
    return l:start
  endif

  let l:server = s:Server()
  if !executable(l:server)
    return []
  endif
  let l:tmp = tempname()
  call writefile(getline(1, '$'), l:tmp)
  let l:at = line('.') . ':' . col('.')
  let l:out = system(printf('%s --complete %s --at %s',
        \ shellescape(l:server), shellescape(l:tmp), shellescape(l:at)))
  call delete(l:tmp)
  if v:shell_error
    return []
  endif
  let l:items = []
  for l:item in get(json_decode(l:out), 'items', [])
    if empty(a:base) || l:item.label =~# '^' . escape(a:base, '\')
      call add(l:items, {'word': l:item.label, 'menu': get(l:item, 'detail', ''),
            \ 'kind': get(get(l:item, 'labelDetails', {}), 'description', '')[0:0]})
    endif
  endfor
  return l:items
endfunction
