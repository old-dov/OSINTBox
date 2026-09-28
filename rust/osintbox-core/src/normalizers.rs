//! Normalize third-party tool output to the OSINTBox finding schema.

use regex::Regex;
use serde_json::{Value, json};

#[derive(Clone, Debug, PartialEq)]
pub struct Finding {
    pub source: String,
    pub category: String,
    pub kind: String,
    pub value: String,
    pub confidence: String,
    pub raw: Value,
}

impl Finding {
    fn new(
        source: &str,
        category: &str,
        kind: &str,
        value: &str,
        confidence: &str,
        raw: Value,
    ) -> Self {
        Self {
            source: source.into(),
            category: category.into(),
            kind: kind.into(),
            value: value.into(),
            confidence: confidence.into(),
            raw,
        }
    }
}

pub fn normalize_text(tool_id: &str, stdout: &str, target: &str) -> Vec<Finding> {
    match tool_id {
        "sherlock" => normalize_sherlock(stdout, target),
        "holehe" => normalize_holehe(stdout, target),
        _ => stdout
            .lines()
            .filter_map(|line| {
                let line = line.trim();
                (!line.is_empty())
                    .then(|| Finding::new(tool_id, tool_id, "raw_line", line, "low", json!({})))
            })
            .collect(),
    }
}

pub fn normalize_json(tool_id: &str, raw: &Value, target: &str) -> Vec<Finding> {
    match tool_id {
        "maigret" => normalize_maigret(raw, target),
        "theharvester" => normalize_theharvester(raw),
        _ => vec![Finding::new(
            tool_id,
            tool_id,
            "raw",
            target,
            "low",
            if raw.is_object() {
                raw.clone()
            } else {
                json!({ "items": raw })
            },
        )],
    }
}

/// Keep category order and finding order, as Python `group_by_category` does.
pub fn group_by_category(findings: &[Finding]) -> Vec<(String, Vec<Finding>)> {
    let mut groups: Vec<(String, Vec<Finding>)> = Vec::new();
    for finding in findings {
        match groups
            .iter_mut()
            .find(|(category, _)| category == &finding.category)
        {
            Some((_, values)) => values.push(finding.clone()),
            None => groups.push((finding.category.clone(), vec![finding.clone()])),
        }
    }
    groups
}

fn normalize_sherlock(stdout: &str, target: &str) -> Vec<Finding> {
    let pattern = Regex::new(r"^\[\+\]\s*(?P<site>[^:]+):\s*(?P<url>https?://\S+)$")
        .expect("valid Sherlock regex");
    stdout
        .lines()
        .filter_map(|line| {
            let captures = pattern.captures(line.trim())?;
            let site = captures.name("site")?.as_str().trim();
            let url = captures.name("url")?.as_str();
            Some(Finding::new(
                "sherlock",
                "username",
                "social_profile",
                url,
                "high",
                json!({ "site": site, "username": target }),
            ))
        })
        .collect()
}

fn normalize_holehe(stdout: &str, target: &str) -> Vec<Finding> {
    let pattern = Regex::new(r"^\[\+\]\s*(?P<site>[A-Za-z0-9][A-Za-z0-9.-]*\.[A-Za-z]{2,})\s*$")
        .expect("valid Holehe regex");
    stdout
        .lines()
        .filter_map(|line| {
            let captures = pattern.captures(line.trim())?;
            let site = captures.name("site")?.as_str();
            Some(Finding::new(
                "holehe",
                "email",
                "account_exists",
                site,
                "high",
                json!({ "site": site, "email": target }),
            ))
        })
        .collect()
}

fn normalize_maigret(raw: &Value, target: &str) -> Vec<Finding> {
    let Some(sites) = raw.as_object() else {
        return Vec::new();
    };
    sites
        .iter()
        .filter_map(|(site, entry)| {
            let status = entry.get("status")?;
            if status.get("status")?.as_str()? != "Claimed" {
                return None;
            }
            let url = entry
                .get("url_user")
                .and_then(Value::as_str)
                .filter(|value| !value.is_empty())
                .or_else(|| status.get("url").and_then(Value::as_str))?;
            let extracted = status.get("ids").cloned().unwrap_or_else(|| json!({}));
            Some(Finding::new(
                "maigret",
                "username",
                "social_profile",
                url,
                "high",
                json!({ "site": site, "username": target, "extracted": extracted }),
            ))
        })
        .collect()
}

fn normalize_theharvester(raw: &Value) -> Vec<Finding> {
    let Some(data) = raw.as_object() else {
        return Vec::new();
    };
    let mut findings = Vec::new();
    for (key, category, kind, confidence) in [
        ("hosts", "domain", "subdomain", "high"),
        ("emails", "email", "email_address", "high"),
        ("ips", "domain", "ip", "medium"),
    ] {
        if let Some(items) = data.get(key).and_then(Value::as_array) {
            for value in items.iter().filter_map(Value::as_str) {
                findings.push(Finding::new(
                    "theharvester",
                    category,
                    kind,
                    value,
                    confidence,
                    json!({}),
                ));
            }
        }
    }
    findings
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn sherlock_matches_real_output_shape() {
        let text = "[*] Checking username torvalds on:\n[+] GitHub: https://www.github.com/torvalds\n[+] Reddit: https://www.reddit.com/user/torvalds\n[-] Other: Not Found!\n";
        let findings = normalize_text("sherlock", text, "torvalds");
        assert_eq!(findings.len(), 2);
        assert_eq!(findings[0].value, "https://www.github.com/torvalds");
        assert_eq!(
            findings[0].raw,
            json!({ "site": "GitHub", "username": "torvalds" })
        );
        assert_eq!(findings[1].category, "username");
    }

    #[test]
    fn holehe_skips_legend_and_banners() {
        let text = "Twitter : @palenath\n[+] any.do\n[+] devrant.com\n[+] firefox.com\n[+] Email used, [-] Email not used, [x] Rate limit\n121 websites checked\n";
        let findings = normalize_text("holehe", text, "test@gmail.com");
        assert_eq!(
            findings
                .iter()
                .map(|item| item.value.as_str())
                .collect::<Vec<_>>(),
            ["any.do", "devrant.com", "firefox.com"]
        );
        assert_eq!(
            findings[0].raw,
            json!({ "site": "any.do", "email": "test@gmail.com" })
        );
    }

    #[test]
    fn maigret_only_claimed_and_keeps_order() {
        let raw: Value = serde_json::from_str(r#"{
            "GitHub":{"status":{"status":"Claimed","url":"https://github.com/torvalds","ids":{"fullname":"Linus Torvalds"}},"url_user":"https://github.com/torvalds"},
            "WordPress":{"status":{"status":"Available","url":"https://torvalds.wordpress.com/"}},
            "Reddit":{"status":{"status":"Claimed","url":"https://reddit.com/u/torvalds"}}
        }"#).unwrap();
        let findings = normalize_json("maigret", &raw, "torvalds");
        assert_eq!(
            findings
                .iter()
                .map(|item| item.raw["site"].as_str().unwrap())
                .collect::<Vec<_>>(),
            ["GitHub", "Reddit"]
        );
        assert_eq!(findings[0].raw["extracted"]["fullname"], "Linus Torvalds");
    }

    #[test]
    fn harvester_handles_absent_keys_and_all_categories() {
        let raw = json!({ "hosts": ["blog.python.org", "wiki.python.org"], "emails": ["contact@python.org"], "ips": ["1.2.3.4"] });
        let findings = normalize_json("theharvester", &raw, "python.org");
        assert_eq!(
            findings
                .iter()
                .map(|item| item.category.as_str())
                .collect::<Vec<_>>(),
            ["domain", "domain", "email", "domain"]
        );
        assert_eq!(findings[3].confidence, "medium");
        assert!(normalize_json("theharvester", &json!({ "cmd": "..." }), "python.org").is_empty());
    }

    #[test]
    fn generic_fallback_and_category_order() {
        let mut findings = normalize_text("other", "line one\n\nline two", "x");
        assert_eq!(findings.len(), 2);
        findings.extend(normalize_json("unknown", &json!(["a"]), "x"));
        assert_eq!(findings[2].raw, json!({ "items": ["a"] }));
        let groups = group_by_category(&findings);
        assert_eq!(
            groups
                .iter()
                .map(|(category, _)| category.as_str())
                .collect::<Vec<_>>(),
            ["other", "unknown"]
        );
        assert_eq!(groups[0].1.len(), 2);
    }
}
