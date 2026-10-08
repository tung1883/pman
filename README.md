# pman

Man-style docs for any language or tool, in your terminal. Pages come as downloadable packs; search is ranked
(headings first, multi-word AND); the built-in pager has `/` search, section list and paging.

    pman pack install all          # or pick: c js py rust go zig bash powershell linux cmd git web sql java kotlin ruby lua php cpp tools
    pman c printf                  # a page (pman sprintf works too)
    pman ts narrowing              # jump to a section
    pman py str.join
    pman -k type guard             # ranked search, pick a result to open
    pman list c                    # pages of a topic

In a page: `j/k` line, `space/b` page, `d/u` half page, `g/G` ends, `/` search, `n/N` next/previous match,
`t` section list, `q` quit. When stdout is not a terminal the page is printed as text (`pman c printf | grep size`).

## Packs

`docs/<pack>/man/` holds the text (`man/js.txt` is page `js`, `man/ts/classes.txt` is `ts.classes`).
`python tools/build_packs.py` zips each pack and writes `dist/registry.json`; `--publish` uploads them to the
`latest` release. Point `PMAN_REGISTRY` at a local `dist/registry.json` to test without publishing.

Env: `PMAN_HOME` (data dir), `PMAN_REGISTRY` (URL or file), `PMAN_DOCS` (extra dir of `<pack>/man` folders).

## Your own notes

```
pman add ~/Vault --name notes   # a .md file or a folder of them (Obsidian vaults work: read as plain markdown)
pman notes                      # pick a note;  pman notes <note> [section]
pman -k words                   # searches your notes together with the doc packs
pman pack update                # re-imports local packs from their source
pman pack remove notes
```

Notes are copied into a local pack under the data dir; the source is never modified. Hidden folders
(`.obsidian`, `.git`) are skipped.

## Sources and licenses

The code is MIT. The doc packs are converted from other projects' documentation and keep their licenses;
`tools/import_*.py` shows where each comes from:

| Pack | Source | License |
|---|---|---|
| c, linux | Linux man-pages, Debian packaged man pages, tcc manual | various free licenses (see each page) |
| js (ts) | QuickJS docs, TypeScript-Website handbook | MIT / CC BY 4.0 |
| py | generated from the Python 3.12 docstrings | PSF |
| rust | rust-lang book, reference, Cargo book, Rust by Example, Nomicon | MIT / Apache-2.0 |
| go | go.dev, pkg.go.dev | BSD-3 / CC BY 4.0 |
| zig | ziglang.org language reference | MIT |
| bash | GNU Bash manual | GFDL / GPL |
| powershell | MicrosoftDocs/PowerShell-Docs; local `Get-Help` | CC BY 4.0 / MIT |
| cmd | tldr-pages | CC BY 4.0 |
| git | git-scm.com docs; Pro Git (Chacon, Straub) | GPL-2 / CC BY-NC-SA 3.0 |
| web | MDN (mdn/content) | CC BY-SA 2.5 |
| sql | sqlite.org, PostgreSQL manual | public domain / PostgreSQL license |
| java | Java Language Specification | Oracle |
| kotlin | JetBrains/kotlin-web-site | Apache-2.0 |
| ruby | docs.ruby-lang.org | Ruby / BSD-2 |
| lua | lua.org manual | MIT |
| php | php.net manual | CC BY 3.0 |
| cpp | cppreference.com | CC BY-SA 3.0 / GFDL |
| tools | POSIX.1 utilities (The Open Group), jq, CMake, Vim | various |

Note the Pro Git book is non-commercial (CC BY-NC-SA); drop the `git.book-*` pages if you redistribute commercially.
