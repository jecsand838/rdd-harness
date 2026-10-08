# Domain patterns

Contents: [Encapsulation](#encapsulate-a-rule-once), [state alternatives](#model-alternatives-rather-than-correlated-flags), [abstraction choices](#choose-the-smallest-useful-abstraction), [sources](#primary-references).

These original illustrations are not the Todo specification or generated interfaces. Compile adapted snippets locally before reuse.

## Encapsulate a rule once

Bad: callers can create invalid values or interpret length differently.

```rust
pub struct Task { pub title: String }
pub fn rename(task: &mut Task, title: String) {
    task.title = title;
}
```

Better: a private value owns validation; mutation accepts the validated value.

```rust
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Title(String);

#[derive(Debug, PartialEq, Eq)]
pub enum TitleError { Empty, TooLong, LineBreak, Nul }

impl Title {
    pub fn parse(raw: &str) -> Result<Self, TitleError> {
        let text = raw.trim();
        if text.is_empty() { return Err(TitleError::Empty); }
        if text.chars().count() > 200 { return Err(TitleError::TooLong); }
        if text.contains('\0') { return Err(TitleError::Nul); }
        if text.chars().any(|c| matches!(c,
            '\n' | '\r' | '\u{000B}' | '\u{000C}' | '\u{0085}' |
            '\u{2028}' | '\u{2029}')) {
            return Err(TitleError::LineBreak);
        }
        Ok(Self(text.to_owned()))
    }
    pub fn as_str(&self) -> &str { &self.0 }
}

pub struct Task { title: Title }
impl Task {
    pub fn rename(&mut self, next: Title) -> bool {
        if self.title == next { return false; }
        self.title = next;
        true
    }
}
```

The application must also implement the approved timestamp, transaction, and no-op-save semantics. Pin compiler and Unicode normalization/case-folding data in specification. `to_lowercase()` is not Unicode default case folding. `String::len()` measures bytes; `chars().count()` measures scalar values; neither counts grapheme clusters.

## Model alternatives rather than correlated flags

Bad:

```rust
struct Completion { done: bool, completed_at: Option<i64> }
// done=false and completed_at=Some(...) is accidentally representable.
```

Better internal shape:

```rust
enum Completion { Open, Completed { at: i64 } }
impl Completion {
    fn complete(&mut self, now: i64) -> bool {
        match self {
            Self::Completed { .. } => false,
            Self::Open => { *self = Self::Completed { at: now }; true }
        }
    }
    fn reopen(&mut self) -> bool {
        match self {
            Self::Open => false,
            Self::Completed { .. } => { *self = Self::Open; true }
        }
    }
}
```

Do not infer increasing wall-clock timestamps: the requirements permit clock corrections. Reject impossible transport combinations rather than silently turning them into a successful write.

## Choose the smallest useful abstraction

| Situation | Starting point | Avoid |
|---|---|---|
| One store behind one application service | Concrete store with approved boundary | Generic repository framework with unused methods |
| Rule depends on time | Pass date/instant or narrow clock capability | Global mutable clock or real sleeps in unit tests |
| Algorithms share syntax but differ semantically | Keep separate until semantics agree | Generic helper with per-caller flags |
| Stable behavior with real substitutes | Small capability trait | Trait mirroring every struct method |
| Resource requires exclusivity | One owner or deliberately scoped lock | `Arc<Mutex<Everything>>` |

Derive traits because their semantics fit. Avoid `Default` for invariant-breaking zero values. Avoid `DerefMut` or broad `From<String>` that bypass validation; use `TryFrom` for fallible construction. Keep errors specific enough for callers to act without matching human text.

## Primary references

Checked 2026-10-07; recheck against the pinned toolchain.

- [Rust By Example](https://doc.rust-lang.org/rust-by-example/index.html)
- [Associated functions and methods](https://doc.rust-lang.org/rust-by-example/fn/methods.html)
- [Newtype idiom](https://doc.rust-lang.org/rust-by-example/generics/new_types.html)
- [Traits](https://doc.rust-lang.org/rust-by-example/trait.html)
- [Generic bounds](https://doc.rust-lang.org/rust-by-example/generics/bounds.html)
- [Error handling](https://doc.rust-lang.org/rust-by-example/error.html)
- [Rust API Guidelines](https://rust-lang.github.io/api-guidelines/about.html)
