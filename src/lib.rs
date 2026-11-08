// SPDX-License-Identifier: Apache-2.0
//! SigmaOS-system-admin — SigmaOS system-admin component inspired by Linux Mint / Omarchy / Arch Linux.
//!
//! Registry of named entries with fail-fast duplicate/missing handling.
//! Principles: single responsibility, fail-fast, defensive programming,
//! component isolation, stable API, deterministic tests.

#![forbid(unsafe_code)]

use std::fmt;
use std::collections::BTreeMap;

/// Errors for `RegistryError` operations. Fail-fast: invalid input is rejected.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum RegistryError {
    /// An entry with this key is already registered
    Duplicate(String),
    /// No entry exists for the requested key
    NotFound(String),
    /// Registration key must not be empty
    EmptyKey,
}

impl fmt::Display for RegistryError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Duplicate(x) => write!(f, "an entry with this key is already registered: {x}"),
            Self::NotFound(x) => write!(f, "no entry exists for the requested key: {x}"),
            Self::EmptyKey => write!(f, "registration key must not be empty"),
        }
    }
}

impl std::error::Error for RegistryError {}

/// Named-entry registry (SRP: storage only; callers own semantics).
#[derive(Debug, Default)]
pub struct Registry {
    items: BTreeMap<String, String>,
}

impl Registry {
    /// Empty registry.
    pub fn new() -> Self { Self::default() }

    /// Register `key -> value`. Fails on empty key or duplicate.
    pub fn register(&mut self, key: impl Into<String>, value: impl Into<String>) -> Result<(), RegistryError> {
        let key = key.into();
        if key.trim().is_empty() { return Err(RegistryError::EmptyKey); }
        if self.items.contains_key(&key) { return Err(RegistryError::Duplicate(key)); }
        self.items.insert(key, value.into());
        Ok(())
    }

    /// Look up a value by key.
    pub fn get(&self, key: &str) -> Option<&str> {
        self.items.get(key).map(String::as_str)
    }

    /// Remove an entry; fails if absent.
    pub fn remove(&mut self, key: &str) -> Result<String, RegistryError> {
        self.items.remove(key).ok_or_else(|| RegistryError::NotFound(key.to_string()))
    }

    /// Number of entries.
    pub fn len(&self) -> usize { self.items.len() }

    /// Whether the registry is empty.
    pub fn is_empty(&self) -> bool { self.items.is_empty() }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn reg() -> Registry {
        let mut r = Registry::new();
        r.register("alpha", "one").unwrap();
        r.register("beta", "two").unwrap();
        r
    }

    #[test]
    fn register_and_get() {
        let r = reg();
        assert_eq!(r.get("alpha"), Some("one"));
        assert_eq!(r.len(), 2);
    }

    #[test]
    fn duplicate_key_fails() {
        let mut r = Registry::new();
        r.register("x", "1").unwrap();
        assert!(matches!(r.register("x", "2"), Err(RegistryError::Duplicate(_))));
    }

    #[test]
    fn remove_missing_fails() {
        assert!(matches!(Registry::new().remove("nope"), Err(RegistryError::NotFound(_))));
    }

    #[test]
    fn empty_key_fails() {
        assert_eq!(Registry::new().register("  ", "v"), Err(RegistryError::EmptyKey));
    }

}

/// Backwards-compatible component handle (kept for existing callers/tests).
#[derive(Debug, Default)]
pub struct Component {
    name: &'static str,
}

impl Component {
    /// Create the component handle.
    pub fn new() -> Self {
        Self { name: "SigmaOS Component" }
    }
}
