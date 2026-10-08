//! Markdown to pman page text, and `pman add`: turns a .md file or a folder of them into a local pack.
//!
//! Output follows the page format of `index.rs`: a header line, then 7-space-indented text. Headings
//! carry an invisible `\u{2}` marker so any case/wording is recognised as a section.

use std::fs;
use std::path::{Path, PathBuf};

pub const HEADING_MARK: char = '\u{2}';
const IND: &str = "       ";

/// One converted note.
pub struct Note {
    pub slug: String,
    pub text: String,
}

/// Collects the `.md` files under `src` (a file or a folder), skipping hidden and dependency dirs.
pub fn find_files(src: &Path) -> Vec<PathBuf> {
    let mut out = Vec::new();
    if src.is_file() {
        out.push(src.to_path_buf());
        return out;
    }
    fn walk(dir: &Path, out: &mut Vec<PathBuf>) {
        let Ok(rd) = fs::read_dir(dir) else { return };
        let mut entries: Vec<_> = rd.flatten().collect();
        entries.sort_by_key(|e| e.file_name());
        for e in entries {
            let name = e.file_name().to_string_lossy().to_string();
            let path = e.path();
            if path.is_dir() {
                if !name.starts_with('.') && name != "node_modules" && name != "target" {
                    walk(&path, out);
                }
            } else if !name.starts_with('.') && matches!(ext(&path).as_str(), "md" | "markdown") {
                out.push(path);
            }
        }
    }
    walk(src, &mut out);
    out
}

fn ext(p: &Path) -> String {
    p.extension().map(|e| e.to_string_lossy().to_lowercase()).unwrap_or_default()
}

/// Page slug of a file: its path relative to `root`, lowercased, any run of other characters turned into `-`.
pub fn slug(rel: &Path) -> String {
    let s = rel.with_extension("").to_string_lossy().to_lowercase();
    let mut out = String::new();
    for c in s.chars() {
        if c.is_alphanumeric() && c.is_ascii() || c == '_' {
            out.push(c);
        } else if !out.ends_with('-') {
            out.push('-');
        }
    }
    out.trim_matches('-').to_string()
}

/// Converts one markdown source. `label` goes in the header line; `stem` titles notes without a heading.
pub fn convert(src: &str, label: &str, stem: &str) -> String {
    let (fm_title, body) = front_matter(src);
    let mut out: Vec<String> = Vec::new();
    let mut para: Vec<String> = Vec::new();
    let mut in_code = false;
    let mut in_comment = false;
    let mut have_heading = false;
    let mut kind = 0u8; // block type of the last line: 1 list, 2 table, 3 quote

    fn blank(out: &mut Vec<String>) {
        if out.last().map_or(false, |l| !l.is_empty()) {
            out.push(String::new());
        }
    }
    fn heading(out: &mut Vec<String>, text: &str) {
        blank(out);
        out.push(format!("{IND}{HEADING_MARK}{text}"));
        out.push(String::new());
    }
    fn flush(out: &mut Vec<String>, para: &mut Vec<String>) {
        if !para.is_empty() {
            out.push(format!("{IND}{}", inline(&para.join(" "))));
            out.push(String::new());
            para.clear();
        }
    }

    let lines: Vec<&str> = body.lines().collect();
    for raw in lines.iter() {
        let line = raw.trim_end().replace('\t', "    ");
        let t = line.trim();
        if in_comment {
            if t.contains("-->") {
                in_comment = false;
            }
            continue;
        }
        if t.starts_with("<!--") {
            if !t.contains("-->") {
                in_comment = true;
            }
            continue;
        }
        if t.starts_with("```") || t.starts_with("~~~") {
            flush(&mut out, &mut para);
            blank(&mut out);
            in_code = !in_code;
            if !in_code {
                blank(&mut out);
            }
            continue;
        }
        if in_code {
            out.push(if t.is_empty() { String::new() } else { format!("{IND}  {line}") });
            continue;
        }
        if t.is_empty() {
            flush(&mut out, &mut para);
            kind = 0;
            continue;
        }
        // ATX heading
        let hashes = t.chars().take_while(|&c| c == '#').count();
        if (1..=6).contains(&hashes) && t[hashes..].starts_with(' ') {
            flush(&mut out, &mut para);
            let text = inline(t[hashes..].trim().trim_end_matches('#').trim());
            if !text.is_empty() {
                if !have_heading {
                    have_heading = true;
                }
                heading(&mut out, &text);
            }
            continue;
        }
        // setext heading: the paragraph so far is the title
        if !para.is_empty() && t.len() >= 2 && (t.chars().all(|c| c == '=') || t.chars().all(|c| c == '-')) {
            let text = inline(&para.join(" "));
            para.clear();
            have_heading = true;
            heading(&mut out, &text);
            continue;
        }
        // horizontal rule
        if t.len() >= 3 && (t.chars().all(|c| c == '-') || t.chars().all(|c| c == '*') || t.chars().all(|c| c == '_')) {
            flush(&mut out, &mut para);
            continue;
        }
        let this = if list_item(&line).is_some() { 1 } else if t.starts_with('|') { 2 } else if t.starts_with('>') { 3 } else { 0 };
        if this != kind && this != 0 {
            blank(&mut out);
        }
        kind = this;
        if let Some((depth, marker, rest)) = list_item(&line) {
            flush(&mut out, &mut para);
            let task = rest.strip_prefix("[ ] ").map(|r| format!("[ ] {r}"))
                .or_else(|| rest.strip_prefix("[x] ").or_else(|| rest.strip_prefix("[X] ")).map(|r| format!("[x] {r}")))
                .unwrap_or_else(|| rest.to_string());
            let pad = "  ".repeat(depth);
            if marker == "*" {
                out.push(format!("{IND}{pad}* {}", inline(&task)));
            } else {
                out.push(format!("{IND} {pad}{marker} {}", inline(&task)));
            }
            continue;
        }
        if t.starts_with('|') {
            flush(&mut out, &mut para);
            let cells: Vec<String> = t.trim_matches('|').split('|').map(|c| inline(c.trim())).collect();
            let rule = cells.iter().all(|c| c.is_empty() || c.chars().all(|ch| ch == '-' || ch == ':' || ch == ' '));
            if !rule {
                let row: Vec<&str> = cells.iter().map(String::as_str).filter(|c| !c.is_empty()).collect();
                out.push(format!("{IND}  {}", row.join("  |  ")));
            }
            continue;
        }
        if t.starts_with('>') {
            flush(&mut out, &mut para);
            let q = inline(t.trim_start_matches(|c| c == '>' || c == ' '));
            if !q.is_empty() {
                out.push(format!("{IND}> {q}"));
            }
            continue;
        }
        // lines that are only a html tag or a continuation of a list item
        if t.starts_with('<') && t.ends_with('>') && !t.contains(' ') && inline(t).is_empty() {
            continue;
        }
        if para.is_empty() && !have_heading && out.is_empty() {
            // first content is plain text: give the note a title
            have_heading = true;
            let title = fm_title.clone().unwrap_or_else(|| stem.to_string());
            heading(&mut out, &title);
        }
        para.push(t.to_string());
    }
    flush(&mut out, &mut para);
    while out.last().map_or(false, |l| l.is_empty()) {
        out.pop();
    }
    if !out.iter().any(|l| l.contains(HEADING_MARK)) {
        let title = fm_title.unwrap_or_else(|| stem.to_string());
        let mut with = vec![format!("{IND}{HEADING_MARK}{title}"), String::new()];
        with.append(&mut out);
        out = with;
    } else if !out.first().map_or(false, |l| l.contains(HEADING_MARK)) {
        // text before the first heading: title it first
        let title = fm_title.unwrap_or_else(|| stem.to_string());
        let mut with = vec![format!("{IND}{HEADING_MARK}{title}"), String::new()];
        with.append(&mut out);
        out = with;
    }
    let mut text = format!("{label}\n\n{}\n", out.join("\n"));
    while text.contains("\n\n\n") {
        text = text.replace("\n\n\n", "\n\n");
    }
    text
}

/// `(depth, marker, text)` of a list item line: `-`/`*`/`+` become `*`, `1.`/`1)` stay numbered.
fn list_item(line: &str) -> Option<(usize, String, &str)> {
    let indent = line.len() - line.trim_start().len();
    let t = line.trim_start();
    let b = t.as_bytes();
    if b.len() >= 2 && matches!(b[0], b'-' | b'*' | b'+') && b[1] == b' ' {
        return Some((indent / 2, "*".into(), t[2..].trim()));
    }
    let digits = t.chars().take_while(|c| c.is_ascii_digit()).count();
    if digits > 0 && digits <= 3 && t.len() > digits + 1 {
        let sep = t.as_bytes()[digits];
        if (sep == b'.' || sep == b')') && t.as_bytes()[digits + 1] == b' ' {
            return Some((indent / 2, format!("{}.", &t[..digits]), t[digits + 2..].trim()));
        }
    }
    None
}

/// Drops a leading `---` YAML block; returns its `title:` value and the rest.
fn front_matter(src: &str) -> (Option<String>, String) {
    let src = src.trim_start_matches('\u{feff}');
    if !(src.starts_with("---\n") || src.starts_with("---\r\n")) {
        return (None, src.to_string());
    }
    let mut title = None;
    let mut consumed = 0;
    let mut lines = src.split_inclusive('\n');
    consumed += lines.next().map_or(0, str::len);
    for l in lines {
        consumed += l.len();
        let tl = l.trim();
        if tl == "---" || tl == "..." {
            return (title, src[consumed..].to_string());
        }
        if let Some(v) = tl.strip_prefix("title:") {
            let v = v.trim().trim_matches(|c| c == '"' || c == '\'');
            if !v.is_empty() {
                title = Some(v.to_string());
            }
        }
    }
    (None, src.to_string()) // never closed: it was not front matter
}

/// Inline markdown to plain text: links keep their label, emphasis markers and html tags go, code keeps its text.
pub fn inline(s: &str) -> String {
    let mut out = String::new();
    for (i, seg) in s.split('`').enumerate() {
        if i % 2 == 1 {
            out.push_str(seg); // code span, verbatim
        } else {
            out.push_str(&inline_plain(seg));
        }
    }
    out.split_whitespace().collect::<Vec<_>>().join(" ")
}

fn inline_plain(s: &str) -> String {
    let c: Vec<char> = s.chars().collect();
    let mut out = String::new();
    let mut i = 0;
    while i < c.len() {
        let ch = c[i];
        match ch {
            '\\' if i + 1 < c.len() && c[i + 1].is_ascii_punctuation() => {
                out.push(c[i + 1]);
                i += 2;
            }
            '!' if c.get(i + 1) == Some(&'[') => {
                // image: dropped
                if let Some((_, end)) = link_at(&c, i + 1) {
                    i = end;
                } else {
                    out.push(ch);
                    i += 1;
                }
            }
            '[' => {
                if let Some((label, end)) = link_at(&c, i) {
                    out.push_str(&inline_plain(&label));
                    i = end;
                } else {
                    out.push(ch);
                    i += 1;
                }
            }
            '<' => {
                // html tag or comment; autolinks <https://..> keep their text
                if let Some(close) = c[i..].iter().position(|&x| x == '>') {
                    let inner: String = c[i + 1..i + close].iter().collect();
                    if inner.starts_with("http") && !inner.contains(' ') {
                        out.push_str(&inner);
                        i += close + 1;
                        continue;
                    }
                    if inner.starts_with('!') || inner.starts_with('/') || inner.chars().next().map_or(false, |x| x.is_ascii_alphabetic()) {
                        i += close + 1;
                        continue;
                    }
                }
                out.push('<');
                i += 1;
            }
            '*' | '~' => {
                // **bold**, *italic*, ~~strike~~: drop the markers when they hug text
                let run = c[i..].iter().take_while(|&&x| x == ch).count();
                let next = c.get(i + run).copied().unwrap_or(' ');
                let prev = if i == 0 { ' ' } else { c[i - 1] };
                if ch == '~' && run < 2 {
                    out.push(ch);
                    i += 1;
                } else if !next.is_whitespace() || !prev.is_whitespace() {
                    i += run;
                } else {
                    out.extend(std::iter::repeat(ch).take(run));
                    i += run;
                }
            }
            '_' => {
                // only at word edges, so snake_case survives
                let run = c[i..].iter().take_while(|&&x| x == '_').count();
                let prev = if i == 0 { ' ' } else { c[i - 1] };
                let next = c.get(i + run).copied().unwrap_or(' ');
                if (!prev.is_alphanumeric() && next.is_alphanumeric()) || (prev.is_alphanumeric() && !next.is_alphanumeric()) {
                    i += run;
                } else {
                    out.extend(std::iter::repeat('_').take(run));
                    i += run;
                }
            }
            '&' => {
                let rest: String = c[i..].iter().take(8).collect();
                let ent = [("&lt;", '<'), ("&gt;", '>'), ("&amp;", '&'), ("&nbsp;", ' '), ("&quot;", '"')];
                if let Some((e, r)) = ent.iter().find(|(e, _)| rest.starts_with(e)) {
                    out.push(*r);
                    i += e.len();
                } else {
                    out.push('&');
                    i += 1;
                }
            }
            _ => {
                out.push(ch);
                i += 1;
            }
        }
    }
    out
}

/// `[label](target)` or `[label][ref]` starting at `c[i] == '['`: the label and the index after it.
fn link_at(c: &[char], i: usize) -> Option<(String, usize)> {
    let mut depth = 0;
    let mut j = i;
    while j < c.len() {
        match c[j] {
            '\\' => j += 1,
            '[' => depth += 1,
            ']' => {
                depth -= 1;
                if depth == 0 {
                    break;
                }
            }
            _ => {}
        }
        j += 1;
    }
    if j >= c.len() {
        return None;
    }
    let label: String = c[i + 1..j].iter().collect();
    let (open, close) = match c.get(j + 1) {
        Some('(') => ('(', ')'),
        Some('[') => ('[', ']'),
        _ => return None,
    };
    let _ = open;
    let end = c[j + 2..].iter().position(|&x| x == close)? + j + 2;
    Some((label, end + 1))
}

/// Converts `src` (file or folder) into notes. Single file: one note slugged `""`; folder: one per file.
pub fn convert_source(src: &Path, name: &str) -> Vec<Note> {
    let files = find_files(src);
    let single = src.is_file();
    let mut notes: Vec<Note> = Vec::new();
    for f in files {
        let rel = if single { PathBuf::from(f.file_name().unwrap_or_default()) } else { f.strip_prefix(src).unwrap_or(&f).to_path_buf() };
        let Ok(bytes) = fs::read(&f) else { continue };
        let source = String::from_utf8_lossy(&bytes);
        let stem = f.file_stem().map(|s| s.to_string_lossy().to_string()).unwrap_or_default();
        let label = format!("{:<40}{name}", rel.to_string_lossy().replace('\\', "/"));
        let text = convert(&source, &label, &stem);
        let mut slug = if single { String::new() } else { slug(&rel) };
        if !single {
            if slug.is_empty() {
                slug = "note".into();
            }
            let base = slug.clone();
            let mut n = 2;
            while notes.iter().any(|x| x.slug == slug) {
                slug = format!("{base}-{n}");
                n += 1;
            }
        }
        notes.push(Note { slug, text });
    }
    notes
}
