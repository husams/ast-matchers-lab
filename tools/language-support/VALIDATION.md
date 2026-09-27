# AST Matcher run workflow validation

Date: 2026-09-27. Local extension: 1.6.0. Toolchain: Homebrew LLVM 22.1.8.

## Delivered behavior

- Run a matcher against one file, a directory, or all workspace folders; source discovery respects `.gitignore` and configured exclusion globs.
- Results group nodes under a filename and full path; filenames use the theme's link color. Location cells contain only `line:column`.
- The results panel opens a settings form for visible columns, compiler arguments, compilation database, traversal, exclusions, and cache enablement/location.
- Declaration kinds come from the AST, including class, struct, union, field, function, method, constructor, and destructor.
- Explorer files and folders offer an existing-query picker and a saved new-query-and-run action.
- Per-translation-unit cache entries include compiler context and dependency contents; changes to included headers invalidate affected entries.

## Automated checks

All checks were launched through the terminal in the already-open VS Code window, followed by interactive validation in that same window.

`tools/language-support/check.sh` passed: generated files current; 74 Python tests; 7 Node tests; 998 verified matcher examples, zero false positives and zero warnings. `git diff --check` passed. An independent final read-only review found no major release blockers.

## Interactive evidence

The disposable fixture was `/private/tmp/astmatcher-ui-validation-20260927`.

| Workflow | Observed result |
| --- | --- |
| Single file and compilation database | Six explicit declarations from `alpha.cpp`; a required macro came from `compile_commands.json`. |
| Directory and exclusions | Seven declarations across `alpha.cpp` and `beta.cpp`; `.gitignore` removed `ignored.cpp`, and a configured glob removed `excluded.cpp`. |
| Cache | First run missed; repeated directory run had two hits; changing the included header produced one hit and one miss. |
| Declaration kinds and locations | Class, struct, union, field, and function were distinct; locations were line/column only. |
| Source selection | Selecting the struct result highlighted exactly `struct Point {}` in its source editor. |
| Traversal | The record matcher produced six records with `AsIs` and three with `IgnoreUnlessSpelledInSource`. |
| Visible columns | Hiding AST kind and Source left Binding, Declaration kind, Summary, and Location. |
| Workspace | Sixteen C++ translation units were grouped by path; the `main` matcher produced one result with the required include path and language flags. |
| Explorer | Existing-query and new-query-and-run actions worked for both a source file and a directory; created queries were saved before execution. |
| Settings persistence | Reloading VS Code preserved the workspace scope, custom flags, disabled cache, and selected result columns. |
| Target changes | Repeating the Explorer folder action preserved `-fblocks`, `-fopenmp`, and the configured include path. |
| Status feedback | The packaged build showed `Running against all workspace folders` and `Cache off` for the corresponding settings. |
| Final layout | All six columns fit the existing VS Code window; filenames were blue, full paths remained visible, and long source snippets were truncated with tooltips. |
| Existing binding groups | The unchanged `foreach.astmatcher` produced two query matches and three unique nodes; selecting `v` selected two source ranges totaling 19 characters. |
| Streaming directory run | During a 120-file scan, the panel displayed 3 matches from 3 completed files before the server finished; the final result contained 120 matches. |

The workspace run used `-std=c++23 -fblocks -fopenmp -isystem <repo>/manifests/include`, excluding C, Objective-C, and CUDA files because they require different compiler contexts. Earlier deliberately incomplete settings visibly reported compiler diagnostics, including the missing `sys.h` include.

## Practical limits

- Directory/workspace runs discover supported source translation units; headers are visited through their includes, or can be selected explicitly as a file target.
- A mixed-language codebase needs appropriate compilation database entries and flags. Shared extra flags are appended to compilation database arguments.
- A header included by several translation units can appear in several results; translation-unit identity is preserved.
- If dependency discovery cannot establish a safe cache key, that translation unit runs without caching.
- Explicitly selecting an ignored or excluded source respects the exclusion and yields no discovered files.
- A running query observes saved source files; unsaved matcher text is sent from the editor.

The final 1.6.0 package was installed in the current VS Code window. The local VSIX is `/private/tmp/astmatcher-delivery-baseline/astmatcher-dsl-1.6.0.vsix`; the full gate transcript is in the same directory as `check.log`. Extension tests also passed after the initial layout adjustment; the final presentation changes passed JavaScript syntax and patch-format checks and were verified visually in the installed extension.

Validation-created settings and queries were moved into the disposable evidence directories. The original `foreach.astmatcher` and `trav_decls.cpp` tabs remain open, original workspace settings and accessibility mode were restored, and the original query's source selections were restored. No lesson documents or sample sources were changed during the initial UI validation.
