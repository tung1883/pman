"""Previous/Next/Contents footers, generalised from import_w3s.py's `add_nav` (which hard-codes
`w3s.`). An importer calls `add_nav` once it knows a tutorial/book's ordered page ids, and
`contents_page` to build the page `pman c` (the pager's `c` key) jumps to.

The pager (src/pager.rs) binds `[`/Left, `]`/Right and `c` to the `Previous:`/`Next:`/`Contents:`
labels in a page's last 12 lines, looked up by fully qualified page id -- nothing pack-specific is
hard-coded in Rust. `pman list <pack>_contents>` or `pman <pack> <name>_contents` opens a contents
page directly; in a terminal it is shown as a filterable list (main.rs::contents).
"""


def add_nav(text, pack, prev=None, nxt=None, contents=None):
    """Appends a `Previous:`/`Next:`/`Contents:` footer naming fully qualified ids
    (`pack.page`). `prev`/`nxt`/`contents` are bare page ids within `pack`, or None to omit."""
    lines = [f"{label} {pack}.{p}" for label, p in (("Previous:", prev), ("Next:", nxt), ("Contents:", contents)) if p]
    if not lines:
        return text
    body = text.rstrip("\n")
    return body + "\n\n" + "".join("       " + l + "\n" for l in lines)


def contents_page(pack, name, entries):
    """A man-style page listing `entries` ((id, title) pairs, bare ids within `pack`); id is
    `<pack>.<name>_contents`, text is man-style with `* pack.id  Title` rows the pager's `c`/`contents`
    flow parses (main.rs::contents)."""
    pid = f"{name}_contents"
    head = f"{pack.upper()}.{pid.upper()}(1)"
    rows = [f"       * {pack}.{i}  {t}" for i, t in entries]
    header = f"{head:<30}Sandbox manual{head:>30}"
    text = f"{header}\n\n       {name.upper()} CONTENTS\n\n" + "\n".join(rows) + "\n"
    return pid, text
