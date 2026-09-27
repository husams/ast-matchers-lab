" clang-query scripts. The lab keeps them in manifests/ and manifests/queries/.
"
" A file that is clearly something else (SPARQL, SQL) keeps its own type: the
" first non-comment line decides. An empty or all-comment *.query file is
" claimed; *.cq and *.clang-query only when they look like the DSL.
function! s:AstMatcherProbe(default) abort
  for l in getline(1, 50)
    if l =~# '^\s*\%(#.*\)\=$'
      continue
    endif
    if l =~# '^\s*\%(match\|m\|let\|l\|set\|enable\|disable\|quit\|q\|help\)\>'
      setfiletype astmatcher
    endif
    return
  endfor
  if a:default
    setfiletype astmatcher
  endif
endfunction
au BufRead,BufNewFile *.query call s:AstMatcherProbe(1)
au BufRead,BufNewFile *.cq,*.clang-query call s:AstMatcherProbe(0)
