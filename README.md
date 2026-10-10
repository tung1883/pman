# pman

pman shows documentation in your terminal, in the style of man pages. Here are some commands showing you how to use it:

    pman pack install all          # or pick: c js py rust go zig (check pman pack list for all packages)
    pman pack install @devops      # or a whole group (pman pack list shows them)
    pman c printf                  # a page (pman sprintf works too)
    pman ts narrowing              # jump to a section
    pman -k type guard             # search something
    pman -k proxy_pass -t nginx    # restrict to a pack/topic; -n max, --all, --by-page
    pman list c                    # pages of a topic

## Your own notes

```
pman add DIRECTORY --name notes   # a .md file or a folder of them (Obsidian vaults work: read as plain markdown)
pman add w3s.zip                  # a ready-made pack zip (man/ inside), kept as a local pack
pman notes                        # pick a note;  pman notes <note> [section]
pman pack update                  # re-imports local packs from their source
pman pack remove notes
```

**Note:**

- pman copies your notes into a local pack under the data directory. It never changes the source.
- It skips hidden folders, such as `.obsidian` and `.git`.

## Sources and licenses

The pman code has the MIT license.