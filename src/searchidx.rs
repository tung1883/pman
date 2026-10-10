//! `search.idx`: a per-pack inverted index used to narrow `pman -k` to candidate pages before the
//! existing scorer (`index.rs::search`) parses and ranks them. Absent or unreadable -> callers fall
//! back to the old full scan, so old installs, `pman add` packs, `PMAN_DOCS` dirs and the Java
//! Android reader (which never looks at this file) keep working unchanged.
//!
//! Layout (little endian):
//!   magic   "PMIX"
//!   u8      version (1)
//!   u32     page_count
//!   u32     term_count
//!   [u32; term_count]      sorted term offsets into `term_blob` (term i spans term_off[i]..term_off[i+1],
//!                          with one extra trailing offset = len(term_blob))
//!   u32     term_blob_len
//!   [u8]    term_blob            terms' bytes, concatenated in sorted order
//!   [entry; term_count]   per term: u8 flag (1 = common, no postings), u32 postings_off, u32 postings_len
//!   [u8]    postings_blob         delta varint-encoded ascending page indices, per term
//!
//! A term in > `COMMON_FRACTION` of the pack's pages is flagged common and stores no postings: it
//! never narrows the candidate set (the existing scorer still verifies the match on the candidates).

use std::collections::BTreeMap;
use std::fs;
use std::io;
use std::path::Path;

const MAGIC: &[u8; 4] = b"PMIX";
const VERSION: u8 = 1;
const COMMON_FRACTION: f64 = 0.40;
const MAX_TOKEN_LEN: usize = 48;
const MAX_DIGIT_LEN: usize = 6;
const MAX_PREFIX_TERMS: usize = 2000;

/// Lowercase word tokens of `text`: split on anything not alphanumeric or `_`; identifiers are also
/// split on `.` and `-`, indexing the parts AND the whole (`json.dumps` -> `json`, `dumps`,
/// `json.dumps`; `no-recreate` -> `no`, `recreate`, `no-recreate`). Skips tokens over 48 chars and
/// pure-digit tokens over 6 digits.
pub fn tokens(text: &str) -> Vec<String> {
    let mut out = Vec::new();
    for raw in text.split(|c: char| !(c.is_alphanumeric() || c == '_' || c == '.' || c == '-')) {
        if raw.is_empty() {
            continue;
        }
        push_token(&mut out, raw);
        if raw.contains('.') || raw.contains('-') {
            for part in raw.split(|c| c == '.' || c == '-') {
                push_token(&mut out, part);
            }
        }
    }
    out
}

fn push_token(out: &mut Vec<String>, t: &str) {
    if t.is_empty() || t.chars().count() > MAX_TOKEN_LEN {
        return;
    }
    if t.chars().all(|c| c.is_ascii_digit()) && t.len() > MAX_DIGIT_LEN {
        return;
    }
    out.push(t.to_lowercase());
}

// ---- building ----------------------------------------------------------------------------------

pub struct Builder {
    page_count: u32,
    terms: BTreeMap<String, Vec<u32>>, // term -> ascending, deduped page indices
}

impl Builder {
    pub fn new() -> Self {
        Builder { page_count: 0, terms: BTreeMap::new() }
    }

    /// Indexes one page's text; `page_idx` must match the page's position in the pack's `bundle.json`.
    pub fn add(&mut self, page_idx: u32, text: &str) {
        self.page_count = self.page_count.max(page_idx + 1);
        for t in tokens(text) {
            let v = self.terms.entry(t).or_default();
            if v.last() != Some(&page_idx) {
                v.push(page_idx);
            }
        }
    }

    pub fn write(&self, path: &Path) -> io::Result<()> {
        let threshold = (self.page_count as f64 * COMMON_FRACTION).ceil() as usize;
        let mut term_blob = Vec::new();
        let mut term_offsets: Vec<u32> = Vec::with_capacity(self.terms.len() + 1);
        let mut entries: Vec<(u8, u32, u32)> = Vec::with_capacity(self.terms.len());
        let mut postings_blob = Vec::new();
        for (term, pages) in &self.terms {
            term_offsets.push(term_blob.len() as u32);
            term_blob.extend_from_slice(term.as_bytes());
            if threshold > 0 && pages.len() > threshold {
                entries.push((1, 0, 0));
                continue;
            }
            let off = postings_blob.len() as u32;
            let mut prev = 0u32;
            for &p in pages {
                write_varint(&mut postings_blob, p - prev);
                prev = p;
            }
            entries.push((0, off, (postings_blob.len() as u32) - off));
        }
        term_offsets.push(term_blob.len() as u32);

        let mut out = Vec::new();
        out.extend_from_slice(MAGIC);
        out.push(VERSION);
        out.extend_from_slice(&self.page_count.to_le_bytes());
        out.extend_from_slice(&(self.terms.len() as u32).to_le_bytes());
        for off in &term_offsets {
            out.extend_from_slice(&off.to_le_bytes());
        }
        out.extend_from_slice(&(term_blob.len() as u32).to_le_bytes());
        out.extend_from_slice(&term_blob);
        for (flag, off, len) in &entries {
            out.push(*flag);
            out.extend_from_slice(&off.to_le_bytes());
            out.extend_from_slice(&len.to_le_bytes());
        }
        out.extend_from_slice(&postings_blob);
        fs::write(path, out)
    }
}

fn write_varint(out: &mut Vec<u8>, mut v: u32) {
    loop {
        let byte = (v & 0x7f) as u8;
        v >>= 7;
        if v == 0 {
            out.push(byte);
            break;
        }
        out.push(byte | 0x80);
    }
}

fn read_varint(buf: &[u8], pos: &mut usize) -> Option<u32> {
    let mut v = 0u32;
    let mut shift = 0;
    loop {
        let b = *buf.get(*pos)?;
        *pos += 1;
        v |= ((b & 0x7f) as u32) << shift;
        if b & 0x80 == 0 {
            return Some(v);
        }
        shift += 7;
        if shift > 35 {
            return None;
        }
    }
}

// ---- reading -------------------------------------------------------------------------------------

struct Entry {
    common: bool,
    off: u32,
    len: u32,
}

pub struct Reader {
    page_count: u32,
    term_offsets: Vec<u32>,
    term_blob: Vec<u8>,
    entries: Vec<Entry>,
    postings: Vec<u8>,
}

enum PrefixResult {
    NoMatch,
    Common,
    Set(Vec<u32>),
}

impl Reader {
    pub fn open(path: &Path) -> Option<Reader> {
        let data = fs::read(path).ok()?;
        Self::parse(&data)
    }

    fn parse(data: &[u8]) -> Option<Reader> {
        let mut pos = 0usize;
        let magic = data.get(0..4)?;
        if magic != MAGIC {
            return None;
        }
        pos += 4;
        let version = *data.get(pos)?;
        pos += 1;
        if version != VERSION {
            return None;
        }
        let page_count = u32::from_le_bytes(data.get(pos..pos + 4)?.try_into().ok()?);
        pos += 4;
        let term_count = u32::from_le_bytes(data.get(pos..pos + 4)?.try_into().ok()?) as usize;
        pos += 4;
        let mut term_offsets = Vec::with_capacity(term_count + 1);
        for _ in 0..=term_count {
            term_offsets.push(u32::from_le_bytes(data.get(pos..pos + 4)?.try_into().ok()?));
            pos += 4;
        }
        let blob_len = u32::from_le_bytes(data.get(pos..pos + 4)?.try_into().ok()?) as usize;
        pos += 4;
        let term_blob = data.get(pos..pos + blob_len)?.to_vec();
        pos += blob_len;
        let mut entries = Vec::with_capacity(term_count);
        for _ in 0..term_count {
            let flag = *data.get(pos)?;
            pos += 1;
            let off = u32::from_le_bytes(data.get(pos..pos + 4)?.try_into().ok()?);
            pos += 4;
            let len = u32::from_le_bytes(data.get(pos..pos + 4)?.try_into().ok()?);
            pos += 4;
            entries.push(Entry { common: flag == 1, off, len });
        }
        let postings = data.get(pos..)?.to_vec();
        Some(Reader { page_count, term_offsets, term_blob, entries, postings })
    }

    fn term_count(&self) -> usize {
        self.entries.len()
    }

    fn term_at(&self, i: usize) -> &[u8] {
        &self.term_blob[self.term_offsets[i] as usize..self.term_offsets[i + 1] as usize]
    }

    fn cmp_prefix(&self, i: usize, prefix: &[u8]) -> std::cmp::Ordering {
        let t = self.term_at(i);
        t[..t.len().min(prefix.len())].cmp(prefix)
    }

    /// First index whose term is >= `prefix`.
    fn lower_bound(&self, prefix: &[u8]) -> usize {
        let (mut lo, mut hi) = (0usize, self.term_count());
        while lo < hi {
            let mid = (lo + hi) / 2;
            if self.term_at(mid) < prefix {
                lo = mid + 1;
            } else {
                hi = mid;
            }
        }
        lo
    }

    fn postings_of(&self, i: usize) -> Vec<u32> {
        let e = &self.entries[i];
        let mut out = Vec::new();
        let buf = &self.postings[e.off as usize..(e.off + e.len) as usize];
        let mut pos = 0usize;
        let mut prev = 0u32;
        while pos < buf.len() {
            let Some(d) = read_varint(buf, &mut pos) else { break };
            prev += d;
            out.push(prev);
        }
        out
    }

    fn lookup_prefix(&self, prefix: &str) -> PrefixResult {
        let prefix = prefix.as_bytes();
        let start = self.lower_bound(prefix);
        let mut end = start;
        while end < self.term_count() && self.cmp_prefix(end, prefix) == std::cmp::Ordering::Equal {
            end += 1;
        }
        if start == end {
            return PrefixResult::NoMatch;
        }
        if end - start > MAX_PREFIX_TERMS {
            return PrefixResult::Common;
        }
        let mut set = Vec::new();
        for i in start..end {
            if self.entries[i].common {
                return PrefixResult::Common;
            }
            set.extend(self.postings_of(i));
        }
        set.sort_unstable();
        set.dedup();
        PrefixResult::Set(set)
    }

    /// Candidate page indices for `tokens` (ANDed), or `None` when a token is too short to use the
    /// index and the caller should fall back to a full scan.
    pub fn candidates(&self, tokens: &[String]) -> Option<Vec<u32>> {
        let mut sets: Vec<Vec<u32>> = Vec::new();
        for t in tokens {
            if t.chars().count() < 2 {
                return None;
            }
            match self.lookup_prefix(t) {
                PrefixResult::NoMatch => return Some(Vec::new()),
                PrefixResult::Common => {}
                PrefixResult::Set(s) => sets.push(s),
            }
        }
        if sets.is_empty() {
            return Some((0..self.page_count).collect());
        }
        sets.sort_by_key(|s| s.len());
        let mut acc = sets.remove(0);
        for s in sets {
            acc = intersect(&acc, &s);
            if acc.is_empty() {
                break;
            }
        }
        Some(acc)
    }
}

fn intersect(a: &[u32], b: &[u32]) -> Vec<u32> {
    let (mut i, mut j) = (0, 0);
    let mut out = Vec::new();
    while i < a.len() && j < b.len() {
        if a[i] == b[j] {
            out.push(a[i]);
            i += 1;
            j += 1;
        } else if a[i] < b[j] {
            i += 1;
        } else {
            j += 1;
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn tokenizer_splits_identifiers() {
        let t = tokens("json.dumps and no-recreate here");
        assert!(t.contains(&"json".to_string()));
        assert!(t.contains(&"dumps".to_string()));
        assert!(t.contains(&"json.dumps".to_string()));
        assert!(t.contains(&"no".to_string()));
        assert!(t.contains(&"recreate".to_string()));
        assert!(t.contains(&"no-recreate".to_string()));
    }

    #[test]
    fn tokenizer_skips_long_and_numeric() {
        let long = "a".repeat(49);
        let t = tokens(&format!("{long} 1234567 123456 ok"));
        assert!(!t.contains(&long));
        assert!(!t.contains(&"1234567".to_string()));
        assert!(t.contains(&"123456".to_string()));
        assert!(t.contains(&"ok".to_string()));
    }

    fn build_and_open(pages: &[&str]) -> Reader {
        use std::sync::atomic::{AtomicU32, Ordering};
        static N: AtomicU32 = AtomicU32::new(0);
        let mut b = Builder::new();
        for (i, text) in pages.iter().enumerate() {
            b.add(i as u32, text);
        }
        let n = N.fetch_add(1, Ordering::Relaxed);
        let path = std::env::temp_dir().join(format!("pman_test_{}_{n}.idx", std::process::id()));
        b.write(&path).unwrap();
        let r = Reader::open(&path).unwrap();
        let _ = fs::remove_file(&path);
        r
    }

    #[test]
    fn round_trip_and_prefix() {
        let r = build_and_open(&["list comprehension in python", "comprehensive guide", "unrelated text"]);
        let hits = r.candidates(&["compr".to_string()]).unwrap();
        assert_eq!(hits, vec![0, 1]);
    }

    #[test]
    fn intersection_across_tokens() {
        let r = build_and_open(&["alpha beta", "alpha gamma", "beta gamma"]);
        let hits = r.candidates(&["alpha".to_string(), "beta".to_string()]).unwrap();
        assert_eq!(hits, vec![0]);
    }

    #[test]
    fn no_match_returns_empty() {
        let r = build_and_open(&["alpha beta"]);
        let hits = r.candidates(&["zzzzqq".to_string()]).unwrap();
        assert!(hits.is_empty());
    }

    #[test]
    fn short_token_signals_fallback() {
        let r = build_and_open(&["alpha beta"]);
        assert!(r.candidates(&["a".to_string()]).is_none());
    }

    #[test]
    fn fallback_when_file_missing_or_corrupt() {
        let path = std::env::temp_dir().join(format!("pman_test_missing_{}_{}.idx", std::process::id(), std::line!()));
        let _ = fs::remove_file(&path);
        assert!(Reader::open(&path).is_none());
        fs::write(&path, b"not an index").unwrap();
        assert!(Reader::open(&path).is_none());
        let _ = fs::remove_file(&path);
    }
}
