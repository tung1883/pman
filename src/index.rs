//! Page model and search. Pages are plain text in man style: a header line, then sections whose
//! headings are 7-space-indented lines in CAPS or numbered ("2.1 Quick start"). Pages are
//! re-flowed for the terminal width at display time; here they are only split into logical lines
//! and sections.

use serde::{Deserialize, Serialize};
use std::cell::OnceCell;
use std::collections::{BTreeMap, HashMap};
use std::fs::{self, File};
use std::io::{self, Read, Seek, SeekFrom, Write};
use std::path::{Path, PathBuf};

const BASE_INDENT: usize = 7;

pub struct Section {
    pub title: String,
    pub line: usize,
}

/// The parsed text of a page; loaded on first use.
#[derive(Default)]
pub struct Body {
    pub title: String,
    pub aliases: Vec<String>,
    pub lines: Vec<String>,
    pub lower: Vec<String>,
    pub sections: Vec<Section>,
}

enum Source {
    File(PathBuf),
    /// A byte range of a pack's `bundle.txt`.
    Bundle { path: PathBuf, off: u64, len: u64 },
}

pub struct Page {
    pub id: String,
    pub topic: String,
    pub title: String,
    pub aliases: Vec<String>,
    source: Source,
    body: OnceCell<Body>,
}

impl Page {
    /// The parsed lines and sections, read from disk on first call.
    pub fn body(&self) -> &Body {
        self.body.get_or_init(|| {
            let text = match &self.source {
                Source::File(p) => fs::read(p).unwrap_or_default(),
                Source::Bundle { path, off, len } => read_range(path, *off, *len).unwrap_or_default(),
            };
            parse(&self.id, &String::from_utf8_lossy(&text))
        })
    }

    /// True when every token occurs in the page text (case-insensitive), without parsing the page.
    fn contains_all(&self, tokens: &[String], cache: &mut HashMap<PathBuf, Vec<u8>>) -> bool {
        fn has_all(bytes: &[u8], tokens: &[String]) -> bool {
            let text = String::from_utf8_lossy(bytes).to_lowercase();
            tokens.iter().all(|t| text.contains(t.as_str()))
        }
        if let Some(b) = self.body.get() {
            return tokens.iter().all(|t| b.lower.iter().any(|l| l.contains(t.as_str())));
        }
        match &self.source {
            Source::File(p) => fs::read(p).map(|b| has_all(&b, tokens)).unwrap_or(false),
            Source::Bundle { path, off, len } => {
                let all = cache.entry(path.clone()).or_insert_with(|| fs::read(path).unwrap_or_default());
                let (start, end) = (*off as usize, (*off + *len) as usize);
                end <= all.len() && has_all(&all[start..end], tokens)
            }
        }
    }

    pub fn lines(&self) -> &Vec<String> {
        &self.body().lines
    }

    pub fn lower(&self) -> &Vec<String> {
        &self.body().lower
    }

    pub fn sections(&self) -> &Vec<Section> {
        &self.body().sections
    }

    /// Index of the last section starting at or before `line`.
    pub fn section_at(&self, line: usize) -> usize {
        let mut best = 0;
        for (i, s) in self.sections().iter().enumerate() {
            if s.line <= line {
                best = i;
            }
        }
        best
    }
}

fn read_range(path: &Path, off: u64, len: u64) -> io::Result<Vec<u8>> {
    let mut f = File::open(path)?;
    f.seek(SeekFrom::Start(off))?;
    let mut buf = vec![0u8; len as usize];
    f.read_exact(&mut buf)?;
    Ok(buf)
}

pub struct Hit {
    pub page: String,
    pub section: usize,
    pub line: usize,
    pub snippet: String,
    pub score: i32,
}

#[derive(Serialize, Deserialize)]
struct BundleMeta {
    pages: Vec<BundlePage>,
}

#[derive(Serialize, Deserialize)]
struct BundlePage {
    id: String,
    title: String,
    aliases: Vec<String>,
    off: u64,
    len: u64,
}

/// One pack's `search.idx` reader plus the page ids in the same order as its `bundle.json`, so a
/// postings page index can be turned back into a page id.
struct PackIndex {
    ids: Vec<String>,
    reader: crate::searchidx::Reader,
}

#[derive(Default)]
pub struct Index {
    pub pages: BTreeMap<String, Page>,
    readers: Vec<PackIndex>,
}

impl Index {
    /// Loads an installed pack: its `bundle.json` (fast, lazy), or a raw `man/` folder (dev).
    pub fn load_pack(&mut self, dir: &Path) {
        if let Ok(text) = fs::read_to_string(dir.join("bundle.json")) {
            if let Ok(meta) = serde_json::from_str::<BundleMeta>(&text) {
                let path = dir.join("bundle.txt");
                let ids: Vec<String> = meta.pages.iter().map(|bp| bp.id.clone()).collect();
                for bp in meta.pages {
                    let topic = bp.id.split('.').next().unwrap_or(&bp.id).to_string();
                    self.pages.insert(
                        bp.id.clone(),
                        Page {
                            id: bp.id,
                            topic,
                            title: bp.title,
                            aliases: bp.aliases,
                            source: Source::Bundle { path: path.clone(), off: bp.off, len: bp.len },
                            body: OnceCell::new(),
                        },
                    );
                }
                if let Some(reader) = crate::searchidx::Reader::open(&dir.join("search.idx")) {
                    self.readers.push(PackIndex { ids, reader });
                }
                return;
            }
        }
        self.scan(&dir.join("man"));
    }

    /// Loads every `*.txt` under `man_dir` (`man/c.txt` is page `c`, `man/ts/classes.txt` is `ts.classes`).
    pub fn scan(&mut self, man_dir: &Path) {
        let Ok(rd) = fs::read_dir(man_dir) else { return };
        let mut entries: Vec<_> = rd.flatten().collect();
        entries.sort_by_key(|e| e.file_name());
        for e in entries {
            let path = e.path();
            let name = e.file_name().to_string_lossy().to_string();
            if path.is_file() {
                if let Some(stem) = name.strip_suffix(".txt") {
                    self.add(stem, &path);
                }
            } else if path.is_dir() {
                let Ok(rd) = fs::read_dir(&path) else { continue };
                let mut kids: Vec<_> = rd.flatten().collect();
                kids.sort_by_key(|k| k.file_name());
                for k in kids {
                    let kname = k.file_name().to_string_lossy().to_string();
                    if let Some(stem) = kname.strip_suffix(".txt") {
                        self.add(&format!("{name}.{stem}"), &k.path());
                    }
                }
            }
        }
    }

    fn add(&mut self, id: &str, path: &Path) {
        let Ok(bytes) = fs::read(path) else { return };
        let body = parse(id, &String::from_utf8_lossy(&bytes));
        let topic = id.split('.').next().unwrap_or(id).to_string();
        let cell = OnceCell::new();
        let (title, aliases) = (body.title.clone(), body.aliases.clone());
        let _ = cell.set(body);
        self.pages.insert(
            id.to_string(),
            Page { id: id.to_string(), topic, title, aliases, source: Source::File(path.to_path_buf()), body: cell },
        );
    }

    pub fn page(&self, id: &str) -> Option<&Page> {
        self.pages.get(id)
    }

    /// A page id, or an alias such as `sprintf` for `c.printf`.
    pub fn by_name(&self, name: &str) -> Option<&Page> {
        if let Some(p) = self.pages.get(name) {
            return Some(p);
        }
        // several pages may document a name (kill: linux, c, cmd): prefer the fullest reference
        const RANK: [&str; 6] = ["linux", "bash", "git", "posix", "powershell", "c"];
        let rank = |t: &str| RANK.iter().position(|r| *r == t).unwrap_or(if t == "cmd" { 99 } else { 20 });
        self.pages
            .values()
            .filter(|p| p.aliases.iter().any(|a| a == name))
            .min_by_key(|p| rank(&p.topic))
    }

    pub fn topics(&self) -> Vec<String> {
        let mut out: Vec<String> = Vec::new();
        for p in self.pages.values() {
            if !out.contains(&p.topic) {
                out.push(p.topic.clone());
            }
        }
        out
    }

    /// Pages of a topic that has sub-pages (`ts`, `py`, `c`); empty for plain pages.
    pub fn sub_pages(&self, topic: &str) -> Vec<&Page> {
        self.pages.values().filter(|p| p.topic == topic && p.id != topic).collect()
    }

    /// Best section in `p` for `q` ("generics", "2.1", "join").
    pub fn find_section(&self, p: &Page, q: &str) -> Option<usize> {
        let q = q.to_lowercase();
        let q = q.trim();
        if q.is_empty() {
            return None;
        }
        let (mut starts, mut ends, mut contains) = (None, None, None);
        let dotted = format!(".{q}");
        for (i, s) in p.sections().iter().enumerate() {
            let t = s.title.to_lowercase();
            if t == q {
                return Some(i);
            }
            if starts.is_none() && t.starts_with(q) {
                starts = Some(i);
            }
            if ends.is_none() && t.ends_with(&dotted) {
                ends = Some(i);
            }
            if contains.is_none() && t.contains(q) {
                contains = Some(i);
            }
        }
        starts.or(ends).or(contains)
    }

    /// Matching (page, section, score) across the pages of a topic for `pman ts generics`, best
    /// first: exact title 4, ends-with-.name 3, prefix 2, contains 1; shorter titles win ties.
    pub fn find_in_topic(&self, topic: &str, q: &str) -> Vec<(String, usize, i32)> {
        let mut cands = self.sub_pages(topic);
        if cands.is_empty() {
            if let Some(p) = self.pages.get(topic) {
                cands.push(p);
            }
        }
        let needle = q.to_lowercase();
        let needle = needle.trim();
        let dotted = format!(".{needle}");
        let mut found: Vec<(i32, usize, String, usize)> = Vec::new();
        for p in cands {
            for (i, s) in p.sections().iter().enumerate() {
                let t = s.title.to_lowercase();
                let score = if t == needle {
                    4
                } else if t.ends_with(&dotted) {
                    3
                } else if t.starts_with(needle) {
                    2
                } else if t.contains(needle) {
                    1
                } else {
                    0
                };
                if score > 0 {
                    found.push((score, t.len(), p.id.clone(), i));
                }
            }
        }
        found.sort_by(|a, b| b.0.cmp(&a.0).then(a.1.cmp(&b.1)));
        found.into_iter().map(|(sc, _, id, i)| (id, i, sc)).collect()
    }

    /// Candidate pages for `tokens`: pages of packs with a `search.idx` are narrowed through it,
    /// everything else (packs without one, `PMAN_DOCS` scans) is scanned in full.
    fn candidate_pages(&self, tokens: &[String]) -> Option<Vec<&Page>> {
        let any_short = tokens.iter().any(|t| t.chars().count() < 2);
        if any_short {
            return None; // caller does a full scan
        }
        let mut indexed: std::collections::HashSet<&str> = std::collections::HashSet::new();
        let mut out: Vec<&Page> = Vec::new();
        for pi in &self.readers {
            // every id this pack's reader covers is "indexed", whether or not it matched
            indexed.extend(pi.ids.iter().map(|s| s.as_str()));
            match pi.reader.candidates(tokens) {
                Some(idxs) => {
                    for i in idxs {
                        if let Some(id) = pi.ids.get(i as usize) {
                            if let Some(p) = self.pages.get(id) {
                                out.push(p);
                            }
                        }
                    }
                }
                None => {
                    for id in &pi.ids {
                        if let Some(p) = self.pages.get(id) {
                            out.push(p);
                        }
                    }
                }
            }
        }
        for p in self.pages.values() {
            if !indexed.contains(p.id.as_str()) {
                out.push(p);
            }
        }
        Some(out)
    }

    /// "Did you mean": tail-match (`bash_intro` -> `w3s.bash_intro`), alias, prefix, substring, then
    /// a small-edit-distance typo match against topics, id tails and aliases. Best first.
    pub fn suggest(&self, q: &str, limit: usize) -> Vec<String> {
        let q = normalize(q);
        if q.is_empty() {
            return Vec::new();
        }
        let mut scored: Vec<(i32, usize, String)> = Vec::new();
        for p in self.pages.values() {
            let tail = normalize(p.id.rsplit('.').next().unwrap_or(&p.id));
            let aliases: Vec<String> = p.aliases.iter().map(|a| normalize(a)).collect();
            let score = if tail == q {
                100
            } else if aliases.iter().any(|a| *a == q) {
                95
            } else if tail.starts_with(&q) || aliases.iter().any(|a| a.starts_with(&q)) {
                80
            } else if tail.contains(&q) || aliases.iter().any(|a| a.contains(&q)) {
                60
            } else {
                let max_d = if q.chars().count() <= 4 { 1 } else { 2 };
                let d = edit_distance(&q, &tail, max_d + 1);
                if d <= max_d {
                    50 - d as i32 * 10
                } else {
                    continue;
                }
            };
            scored.push((score, p.id.len(), p.id.clone()));
        }
        scored.sort_by(|a, b| b.0.cmp(&a.0).then(a.1.cmp(&b.1)));
        scored.dedup_by(|a, b| a.2 == b.2);
        scored.into_iter().take(limit).map(|(_, _, id)| id).collect()
    }

    /// "Did you mean" at section level ("no section 'x' in y"): same scoring over `p`'s own titles.
    pub fn suggest_sections(&self, p: &Page, q: &str, limit: usize) -> Vec<String> {
        let q = normalize(q);
        if q.is_empty() {
            return Vec::new();
        }
        let mut scored: Vec<(i32, usize, String)> = Vec::new();
        for s in p.sections() {
            let t = normalize(&s.title);
            let score = if t == q {
                100
            } else if t.starts_with(&q) {
                80
            } else if t.contains(&q) {
                60
            } else {
                let max_d = if q.chars().count() <= 4 { 1 } else { 2 };
                let d = edit_distance(&q, &t, max_d + 1);
                if d <= max_d {
                    50 - d as i32 * 10
                } else {
                    continue;
                }
            };
            scored.push((score, s.title.len(), s.title.clone()));
        }
        scored.sort_by(|a, b| b.0.cmp(&a.0).then(a.1.cmp(&b.1)));
        scored.dedup_by(|a, b| a.2 == b.2);
        scored.into_iter().take(limit).map(|(_, _, t)| t).collect()
    }

    /// Curated bonus so a language's own reference beats duplicate coverage elsewhere (w3s repeats
    /// python/js/css/html; tldr/cmd is terse). Local notes (`pman add`) are not in this table and
    /// get the default, highest, bonus.
    fn topic_bonus(topic: &str) -> i32 {
        const HIGH: [&str; 6] = ["py", "python", "js", "ts", "rust", "go"];
        const LOW: [&str; 2] = ["cmd", "w3s"];
        if LOW.contains(&topic) {
            0
        } else if HIGH.contains(&topic) {
            30
        } else {
            20
        }
    }

    /// Sections containing every word, headings weighted over body text, best first. `max == 0`
    /// means no cap. `topics`, when given, restricts candidates to those topics.
    pub fn search_filtered(&self, query: &str, max: usize, topics: Option<&[String]>) -> Vec<Hit> {
        let tokens: Vec<String> = query.to_lowercase().split_whitespace().map(String::from).collect();
        let mut hits: Vec<Hit> = Vec::new();
        if tokens.is_empty() {
            return hits;
        }
        let joined = tokens.join(" ");
        let name_query = joined.replace(' ', "_");
        let mut cache: HashMap<PathBuf, Vec<u8>> = HashMap::new();
        let candidates = self.candidate_pages(&tokens);
        let pages_iter: Vec<&Page> = match &candidates {
            Some(v) => v.clone(),
            None => self.pages.values().collect(),
        };
        let mut scan = |pages: &[&Page], hits: &mut Vec<Hit>| {
        for p in pages {
            if let Some(ts) = topics {
                if !ts.iter().any(|t| t == &p.topic) {
                    continue;
                }
            }
            // cheap raw-text check first, so only pages that can match are parsed
            if !p.contains_all(&tokens, &mut cache) {
                continue;
            }
            let mut name_bonus = 0;
            let tail = p.id.rsplit('.').next().unwrap_or(&p.id);
            if tail == name_query || p.aliases.iter().any(|a| a == &name_query) {
                name_bonus += 200;
            }
            for s in 0..p.sections().len() {
                let from = p.sections()[s].line;
                let to = if s + 1 < p.sections().len() { p.sections()[s + 1].line } else { p.lines().len() };
                let title = p.sections()[s].title.to_lowercase();
                let mut count = vec![0usize; tokens.len()];
                let mut first_line: Vec<Option<usize>> = vec![None; tokens.len()];
                for i in from..to {
                    let l = &p.lower()[i];
                    for (k, tok) in tokens.iter().enumerate() {
                        let mut at = 0;
                        while let Some(pos) = l[at..].find(tok.as_str()) {
                            if count[k] >= 50 {
                                break;
                            }
                            count[k] += 1;
                            if first_line[k].is_none() && i > from {
                                first_line[k] = Some(i);
                            }
                            at += pos + tok.len().max(1);
                            if at >= l.len() {
                                break;
                            }
                        }
                    }
                }
                if count.iter().any(|&c| c == 0) {
                    continue;
                }
                let mut score = 0i32;
                let mut head_all = true;
                for (k, tok) in tokens.iter().enumerate() {
                    if title.contains(tok.as_str()) {
                        score += 20;
                    } else {
                        head_all = false;
                    }
                    score += count[k].min(10) as i32;
                }
                if head_all {
                    score += 100;
                }
                if title == joined || title.ends_with(&format!(".{joined}")) {
                    score += if s == 0 { 120 } else { 50 };
                }
                score += name_bonus + Self::topic_bonus(&p.topic);
                let mut line = from;
                let mut snippet = String::new();
                if !head_all {
                    if let Some(l) = first_line.iter().flatten().next() {
                        line = *l;
                        snippet = p.lines()[line].trim().to_string();
                    }
                } else {
                    for i in (from + 1)..to {
                        let l = p.lines()[i].trim();
                        if !l.is_empty() {
                            snippet = l.to_string();
                            break;
                        }
                    }
                }
                if snippet.chars().count() > 90 {
                    snippet = snippet.chars().take(90).collect::<String>() + "…";
                }
                hits.push(Hit { page: p.id.clone(), section: s, line, snippet, score });
            }
        }
        };
        scan(&pages_iter, &mut hits);
        // Index pruning missed a mid-word substring query (e.g. "ompre"): run one full scan.
        if hits.is_empty() && candidates.is_some() && tokens.iter().any(|t| t.chars().any(|c| !c.is_alphanumeric() && c != '_')) {
            let all: Vec<&Page> = self.pages.values().collect();
            scan(&all, &mut hits);
        }
        hits.sort_by(|a, b| b.score.cmp(&a.score));
        if max > 0 {
            hits.truncate(max);
        }
        hits
    }
}

// ---- suggestions -------------------------------------------------------------------------------

/// `-`, `_` and space compare equal; case-insensitive.
fn normalize(s: &str) -> String {
    s.to_lowercase().chars().map(|c| if c == '-' || c == ' ' { '_' } else { c }).collect()
}

/// Bounded Levenshtein distance; returns `cap` (not the true distance) once it is certain the
/// distance is >= `cap`, so typo lookups over many short strings stay cheap.
fn edit_distance(a: &str, b: &str, cap: usize) -> usize {
    let (a, b): (Vec<char>, Vec<char>) = (a.chars().collect(), b.chars().collect());
    if a.len().abs_diff(b.len()) >= cap {
        return cap;
    }
    let mut prev: Vec<usize> = (0..=b.len()).collect();
    for i in 1..=a.len() {
        let mut cur = vec![0usize; b.len() + 1];
        cur[0] = i;
        let mut row_min = cur[0];
        for j in 1..=b.len() {
            cur[j] = if a[i - 1] == b[j - 1] {
                prev[j - 1]
            } else {
                1 + prev[j - 1].min(prev[j]).min(cur[j - 1])
            };
            row_min = row_min.min(cur[j]);
        }
        if row_min >= cap {
            return cap;
        }
        prev = cur;
    }
    prev[b.len()].min(cap)
}

// ---- parsing ----------------------------------------------------------------------------------

fn parse(id: &str, text: &str) -> Body {
    let raw: Vec<&str> = text.split('\n').collect();
    let mut p = Body::default();
    // 0 = blank/none, 1 = flowing text, 2 = bullet/quote (takes continuations), 3 = verbatim
    let mut prev = 0;
    let mut first_heading = true;
    let mut have_title = false;
    for i in 0..raw.len() {
        let r = raw[i].trim_end_matches('\r');
        if i == raw.len() - 1 && r.is_empty() {
            break;
        }
        if r.trim().is_empty() {
            emit(&mut p, "", prev != 0);
            prev = 0;
            continue;
        }
        if !r.starts_with(' ') || r.len() <= BASE_INDENT {
            // header and footer lines
            emit(&mut p, r.trim(), false);
            prev = 3;
            continue;
        }
        let t: &str = if r.is_char_boundary(BASE_INDENT) { &r[BASE_INDENT..] } else { r.trim_start() };
        if let Some(h) = t.strip_prefix(crate::md::HEADING_MARK) {
            // explicit heading (converted markdown): any wording or case
            let h = h.trim();
            p.sections.push(Section { title: h.to_string(), line: p.lines.len() });
            if first_heading {
                p.title = h.to_string();
                have_title = true;
                first_heading = false;
            }
            emit(&mut p, h, false);
            prev = 3;
            continue;
        }
        let trimmed = t.trim();
        // Numbered headings may be stacked ("2 Usage" directly above "2.1 Install").
        let blank_before = i == 0 || raw[i - 1].trim().is_empty() || is_numbered(raw[i - 1]);
        let blank_after = i + 1 >= raw.len() || raw[i + 1].trim().is_empty() || is_numbered(raw[i + 1]);
        let heading = (blank_before && blank_after && is_heading(trimmed)) || (blank_before && strong_numbered(trimmed));
        if !t.starts_with(' ') && heading {
            p.sections.push(Section { title: trimmed.to_string(), line: p.lines.len() });
            if first_heading && trimmed != "NAME" {
                p.title = trimmed.to_string();
                have_title = true;
                first_heading = false;
            }
            emit(&mut p, trimmed, false);
            prev = 3;
            continue;
        }
        let bullet = trimmed.starts_with("* ") || trimmed.starts_with("> ");
        if bullet {
            emit(&mut p, t, false);
            prev = 2;
        } else if prev == 2 && leading_spaces(t) >= 2 {
            join(&mut p, trimmed);
        } else if t.starts_with(' ') {
            emit(&mut p, t, false);
            prev = 3;
        } else if prev == 1 {
            join(&mut p, trimmed);
        } else {
            emit(&mut p, t, false);
            prev = 1;
        }
    }
    // man-page style NAME section: "printf, fprintf - formatted output" gives aliases and a title.
    if let Some(s) = p.sections.iter().position(|s| s.title == "NAME") {
        let start = p.sections[s].line + 1;
        for i in start..p.lines.len() {
            let l = p.lines[i].trim().to_string();
            if l.is_empty() {
                continue;
            }
            let (names, desc) = match l.find(" - ") {
                Some(d) => (l[..d].to_string(), Some(l[d + 3..].trim().to_string())),
                None => (l.clone(), None),
            };
            for n in names.split(',') {
                let n = n.trim();
                if !n.is_empty() && n.chars().all(|c| c.is_alphanumeric() || c == '_' || c == '-' || c == '.') {
                    p.aliases.push(n.to_lowercase());
                }
            }
            if let Some(d) = desc {
                p.title = d;
                have_title = true;
            }
            break;
        }
    }
    if !have_title {
        p.title = id.to_string();
    }
    if p.sections.is_empty() || p.sections[0].line > 0 {
        let title = p.title.clone();
        p.sections.insert(0, Section { title, line: 0 });
    }
    p
}

fn leading_spaces(s: &str) -> usize {
    s.chars().take_while(|&c| c == ' ').count()
}

fn is_numbered_text(s: &str) -> bool {
    // digits(.digits)* then whitespace then a non-space character
    let b = s.as_bytes();
    let mut i = 0;
    loop {
        let start = i;
        while i < b.len() && b[i].is_ascii_digit() {
            i += 1;
        }
        if i == start {
            return false;
        }
        if i < b.len() && b[i] == b'.' {
            i += 1;
            continue;
        }
        break;
    }
    if i >= b.len() || !(b[i] == b' ' || b[i] == b'\t') {
        return false;
    }
    s[i..].trim_start().chars().next().is_some()
}

/// A numbered heading ("2.1 Quick start") is recognised even when text follows on the next line.
fn strong_numbered(s: &str) -> bool {
    if !is_numbered_text(s) || s.chars().count() > 60 || s.ends_with('.') || s.ends_with(':') {
        return false;
    }
    let rest = s.trim_start_matches(|c: char| c.is_ascii_digit() || c == '.').trim_start();
    rest.chars().next().map_or(false, |c| c.is_uppercase())
}

fn is_numbered(raw: &str) -> bool {
    raw.len() > BASE_INDENT
        && raw.starts_with(' ')
        && raw.as_bytes()[BASE_INDENT] != b' '
        && raw.is_char_boundary(BASE_INDENT)
        && is_numbered_text(raw[BASE_INDENT..].trim())
}

fn is_heading(s: &str) -> bool {
    let n = s.chars().count();
    if !(2..=70).contains(&n) {
        return false;
    }
    if is_numbered_text(s) {
        return true;
    }
    let ok = |c: char| c.is_ascii_uppercase() || c.is_ascii_digit() || " ,&'()./:_+#-".contains(c);
    let first = s.chars().next().unwrap();
    (first.is_ascii_uppercase() || first.is_ascii_digit()) && s.chars().all(ok) && s.chars().any(|c| c.is_alphabetic())
}

/// Adds a line; collapses runs of blank lines.
fn emit(p: &mut Body, line: &str, allow_blank: bool) {
    if line.is_empty() && (!allow_blank || p.lines.last().map_or(true, |l| l.is_empty())) {
        return;
    }
    p.lines.push(line.to_string());
    p.lower.push(line.to_lowercase());
}

fn join(p: &mut Body, more: &str) {
    if let Some(last) = p.lines.last_mut() {
        last.push(' ');
        last.push_str(more);
        // extend the lowercase copy instead of rebuilding it (a long joined paragraph was quadratic)
        let low = p.lower.last_mut().unwrap();
        low.push(' ');
        low.push_str(&more.to_lowercase());
    }
}

/// Packs `<pack_dir>/man/**.txt` into one `bundle.txt` plus a small `bundle.json` index and removes
/// the loose files. Opening a pack then reads one small file; pages are parsed only when used.
pub fn build_bundle(pack_dir: &Path) -> io::Result<()> {
    let mut ix = Index::default();
    ix.scan(&pack_dir.join("man"));
    let mut out = File::create(pack_dir.join("bundle.txt"))?;
    let mut off = 0u64;
    let mut meta = BundleMeta { pages: Vec::new() };
    let mut builder = crate::searchidx::Builder::new();
    for (idx, (id, page)) in ix.pages.iter().enumerate() {
        let Source::File(path) = &page.source else { continue };
        let bytes = fs::read(path)?;
        builder.add(idx as u32, &String::from_utf8_lossy(&bytes));
        out.write_all(&bytes)?;
        meta.pages.push(BundlePage {
            id: id.clone(),
            title: page.title.clone(),
            aliases: page.aliases.clone(),
            off,
            len: bytes.len() as u64,
        });
        off += bytes.len() as u64;
    }
    out.flush()?;
    fs::write(pack_dir.join("bundle.json"), serde_json::to_string(&meta).map_err(io::Error::other)?)?;
    builder.write(&pack_dir.join("search.idx"))?;
    fs::remove_dir_all(pack_dir.join("man"))
}

/// (Re)builds `search.idx` for an already-installed pack (its `man/` folder is gone; read the
/// pages back out of `bundle.txt`/`bundle.json`). Used by `pman reindex` and lazily on the first
/// `-k` against a pack installed before this feature existed.
pub fn reindex_installed(pack_dir: &Path) -> io::Result<()> {
    let text = fs::read_to_string(pack_dir.join("bundle.json"))?;
    let meta: BundleMeta = serde_json::from_str(&text).map_err(io::Error::other)?;
    let bundle_path = pack_dir.join("bundle.txt");
    let mut builder = crate::searchidx::Builder::new();
    for (idx, bp) in meta.pages.iter().enumerate() {
        let bytes = read_range(&bundle_path, bp.off, bp.len)?;
        builder.add(idx as u32, &String::from_utf8_lossy(&bytes));
    }
    builder.write(&pack_dir.join("search.idx"))
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::atomic::{AtomicU32, Ordering};

    static N: AtomicU32 = AtomicU32::new(0);

    fn temp_pack(pages: &[(&str, &str)]) -> PathBuf {
        let n = N.fetch_add(1, Ordering::Relaxed);
        let dir = std::env::temp_dir().join(format!("pman_idx_test_{}_{n}", std::process::id()));
        let man = dir.join("man");
        fs::create_dir_all(&man).unwrap();
        for (id, text) in pages {
            fs::write(man.join(format!("{id}.txt")), text).unwrap();
        }
        build_bundle(&dir).unwrap();
        dir
    }

    /// A no-match query against an indexed pack must not fall back to scoring every page (that
    /// was the bug: an empty-but-indexed candidate set was indistinguishable from "not indexed").
    #[test]
    fn no_match_on_indexed_pack_scans_nothing() {
        let dir = temp_pack(&[
            ("a", "A(1)       man       A(1)\n\n       ALPHA\n\n       some text about alpha\n"),
            ("b", "B(1)       man       B(1)\n\n       BETA\n\n       some text about beta\n"),
        ]);
        let mut ix = Index::default();
        ix.load_pack(&dir);
        assert_eq!(ix.readers.len(), 1);
        let hits = ix.search_filtered("zzzzqq_no_such_word", 0, None);
        assert!(hits.is_empty());
        let _ = fs::remove_dir_all(&dir);
    }

    #[test]
    fn indexed_pack_still_finds_real_matches() {
        let dir = temp_pack(&[
            ("a", "A(1)       man       A(1)\n\n       ALPHA\n\n       some text about alpha\n"),
            ("b", "B(1)       man       B(1)\n\n       BETA\n\n       some text about beta\n"),
        ]);
        let mut ix = Index::default();
        ix.load_pack(&dir);
        let hits = ix.search_filtered("alpha", 0, None);
        assert_eq!(hits.len(), 1);
        assert_eq!(hits[0].page, "a");
        let _ = fs::remove_dir_all(&dir);
    }
}
