//! Shared, dependency-free validation core for the OSINTBox Rust migration.
//!
//! The Python desktop application remains the production entry point while
//! components are ported and checked for behavioral parity.

use std::net::IpAddr;

pub mod catalog;

pub const TARGET_TYPES: &[&str] = &["username", "email", "domain", "host", "ip", "url"];

const TERRITORY_TAGS: &[&str] = &[
    "ae", "am", "ar", "at", "au", "az", "bd", "be", "bg", "br", "by", "ca", "ch", "cl", "cn", "co",
    "cr", "cz", "de", "dk", "dz", "ee", "eg", "es", "fi", "fr", "gb", "gr", "hk", "hr", "hu", "id",
    "ie", "il", "in", "ir", "it", "jp", "kg", "kr", "kz", "lk", "lt", "lv", "ma", "md", "mk", "mx",
    "my", "ng", "nl", "no", "nz", "ph", "pk", "pl", "pt", "ro", "rs", "ru", "sa", "se", "sg", "th",
    "tm", "tn", "tr", "tw", "tz", "ua", "us", "uz", "ve", "vn", "za",
];

/// Same `(valid, error)` contract and French errors as Python `validate_territory`.
pub fn validate_territory(value: &str) -> (bool, String) {
    let value = value.trim().to_ascii_lowercase();
    if value.is_empty() {
        return invalid("Territoire vide");
    }
    if value.starts_with('-') {
        return invalid(
            "Le territoire ne peut pas commencer par '-' (serait interprete comme une option)",
        );
    }
    if !TERRITORY_TAGS.contains(&value.as_str()) {
        return invalid(format!(
            "Territoire inconnu '{value}' (ex: fr, us, de, gb...)"
        ));
    }
    valid()
}

/// Same `(valid, error)` contract and French errors as Python `validate_target`.
pub fn validate_target(value: &str, target_type: &str) -> (bool, String) {
    let value = value.trim();
    if value.is_empty() {
        return invalid("Valeur vide");
    }
    if value.starts_with('-') {
        return invalid(
            "La valeur ne peut pas commencer par '-' (serait interpretee comme une option)",
        );
    }
    match target_type {
        "username" if username(value) => valid(),
        "username" => invalid("Nom d'utilisateur invalide"),
        "email" if email(value) => valid(),
        "email" => invalid("Adresse email invalide"),
        "domain" if hostname(value, true) => valid(),
        "domain" => invalid("Domaine invalide (ex: exemple.com)"),
        "host" if value.parse::<IpAddr>().is_ok() || hostname(value, false) => valid(),
        "host" => invalid("Doit etre une IP ou un nom d'hote valide"),
        "ip" if value.parse::<IpAddr>().is_ok() => valid(),
        "ip" => invalid("Adresse IP invalide"),
        "url" if url(value) => valid(),
        "url" => invalid("URL invalide (doit commencer par http:// ou https://)"),
        _ => invalid(format!("Type de cible inconnu: {target_type}")),
    }
}

fn valid() -> (bool, String) {
    (true, String::new())
}

fn invalid(message: impl Into<String>) -> (bool, String) {
    (false, message.into())
}

fn username(value: &str) -> bool {
    (1..=64).contains(&value.len())
        && value
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b"_.-".contains(&b))
}

fn hostname(value: &str, require_dot: bool) -> bool {
    if value.is_empty() || value.len() > 253 || (require_dot && !value.contains('.')) {
        return false;
    }
    value.split('.').all(|label| {
        (1..=63).contains(&label.len())
            && !label.starts_with('-')
            && !label.ends_with('-')
            && label
                .bytes()
                .all(|b| b.is_ascii_alphanumeric() || b == b'-')
    })
}

fn email(value: &str) -> bool {
    let Some((local, domain)) = value.split_once('@') else {
        return false;
    };
    if !(1..=64).contains(&local.len())
        || !local
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b"_.+-".contains(&b))
    {
        return false;
    }
    let Some((first, rest)) = domain.split_once('.') else {
        return false;
    };
    (1..=253).contains(&first.len())
        && first
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b == b'-')
        && rest.split('.').all(|label| {
            (1..=63).contains(&label.len())
                && label
                    .bytes()
                    .all(|b| b.is_ascii_alphanumeric() || b == b'-')
        })
}

fn url(value: &str) -> bool {
    let remainder = value
        .strip_prefix("https://")
        .or_else(|| value.strip_prefix("http://"));
    remainder.is_some_and(|part| {
        (1..=2048).contains(&part.chars().count()) && !part.chars().any(char::is_whitespace)
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn target_types_match_python_contract() {
        assert_eq!(
            TARGET_TYPES,
            ["username", "email", "domain", "host", "ip", "url"]
        );
        for (value, kind) in [
            ("torvalds", "username"),
            ("user@example.com", "email"),
            ("example.com", "domain"),
            ("myhost", "host"),
            ("192.168.1.1", "host"),
            ("8.8.8.8", "ip"),
            ("2001:db8::1", "ip"),
            ("https://example.com/path", "url"),
        ] {
            assert_eq!(validate_target(value, kind), valid(), "{kind}: {value}");
        }
        for (value, kind, error) in [
            ("torv alds!", "username", "Nom d'utilisateur invalide"),
            ("not-an-email", "email", "Adresse email invalide"),
            ("localhost", "domain", "Domaine invalide (ex: exemple.com)"),
            ("999.999.999.999", "ip", "Adresse IP invalide"),
            (
                "ftp://example.com",
                "url",
                "URL invalide (doit commencer par http:// ou https://)",
            ),
            (
                "--evil-flag",
                "username",
                "La valeur ne peut pas commencer par '-' (serait interpretee comme une option)",
            ),
            ("", "username", "Valeur vide"),
            (
                "whatever",
                "not_a_type",
                "Type de cible inconnu: not_a_type",
            ),
        ] {
            assert_eq!(
                validate_target(value, kind),
                invalid(error),
                "{kind}: {value}"
            );
        }
    }

    #[test]
    fn territory_matches_python_contract() {
        assert_eq!(validate_territory("FR"), valid());
        assert_eq!(validate_territory("  fr  "), valid());
        assert_eq!(
            validate_territory("zz"),
            invalid("Territoire inconnu 'zz' (ex: fr, us, de, gb...)")
        );
        assert_eq!(validate_territory(""), invalid("Territoire vide"));
        assert_eq!(
            validate_territory("--evil-flag"),
            invalid(
                "Le territoire ne peut pas commencer par '-' (serait interprete comme une option)"
            )
        );
    }

    #[test]
    fn boundaries_and_injection() {
        assert!(validate_target(&"a".repeat(64), "username").0);
        assert!(!validate_target(&"a".repeat(65), "username").0);
        assert!(!validate_target("a..example.com", "domain").0);
        assert!(!validate_target("-example.com", "domain").0);
        assert!(!validate_target("example-.com", "domain").0);
        assert!(!validate_target("https://example.com/a b", "url").0);
    }
}
