//! Tool catalog schema and command construction, ported from `osintbox/catalog.py`.

use std::borrow::Cow;
use std::collections::HashSet;
use std::fmt;
use std::fs;
use std::path::Path;

use serde_yaml_ng::{Mapping, Value};

use crate::TARGET_TYPES;

#[derive(Clone, Debug, PartialEq)]
pub struct ToolSpec {
    pub id: String,
    pub category: String,
    pub desc: String,
    pub command: Vec<String>,
    pub target_type: String,
    pub output_mode: String,
    pub output_path_template: Option<String>,
    pub default_timeout_s: u64,
    pub example: String,
    pub nonzero_exit_ok: bool,
    pub min_delay_s: f64,
    pub territory_flag: Option<String>,
}

impl ToolSpec {
    pub fn build_argv(&self, target: &str) -> Vec<String> {
        self.command
            .iter()
            .map(|part| {
                if part == "{target}" {
                    target.to_owned()
                } else {
                    part.clone()
                }
            })
            .collect()
    }

    /// Borrow the original spec when no territory flag can be applied.
    pub fn with_territory(&self, territory: Option<&str>) -> Cow<'_, Self> {
        match (self.territory_flag.as_deref(), territory) {
            (Some(flag), Some(value)) if !value.is_empty() => {
                let mut spec = self.clone();
                spec.command.extend([flag.to_owned(), value.to_owned()]);
                Cow::Owned(spec)
            }
            _ => Cow::Borrowed(self),
        }
    }
}

#[derive(Debug)]
pub struct CatalogError(pub String);

impl fmt::Display for CatalogError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}

impl std::error::Error for CatalogError {}

pub fn load_catalog(path: impl AsRef<Path>) -> Result<Vec<ToolSpec>, CatalogError> {
    let content = fs::read_to_string(path).map_err(|error| CatalogError(error.to_string()))?;
    parse_catalog(&content)
}

pub fn parse_catalog(content: &str) -> Result<Vec<ToolSpec>, CatalogError> {
    let raw: Value = serde_yaml_ng::from_str(content)
        .map_err(|error| CatalogError(format!("YAML invalide: {error}")))?;
    let entries = raw
        .as_sequence()
        .ok_or_else(|| CatalogError("catalog.yaml doit etre une liste d'entrees".into()))?;

    let mut tools = Vec::with_capacity(entries.len());
    let mut seen_ids = HashSet::new();
    for entry in entries {
        let map = entry
            .as_mapping()
            .ok_or_else(|| CatalogError("Entree catalogue invalide: objet attendu".into()))?;
        let id = required_string(map, "id")?;
        let category = required_string(map, "category")?;
        let desc = required_string(map, "desc")?;
        let target_type = required_string(map, "target_type")?;
        if !TARGET_TYPES.contains(&target_type.as_str()) {
            return Err(CatalogError(format!(
                "{id}: target_type invalide '{target_type}'"
            )));
        }

        let command = get(map, "command")
            .and_then(Value::as_sequence)
            .filter(|items| !items.is_empty())
            .and_then(|items| {
                items
                    .iter()
                    .map(|item| item.as_str().map(str::to_owned))
                    .collect::<Option<Vec<_>>>()
            })
            .ok_or_else(|| {
                CatalogError(format!(
                    "{id}: 'command' doit etre une liste non vide de textes"
                ))
            })?;
        if !command.iter().any(|part| part == "{target}") {
            return Err(CatalogError(format!(
                "{id}: 'command' doit contenir le placeholder '{{target}}'"
            )));
        }

        let output_mode = optional_string(map, "output_mode")?.unwrap_or_else(|| "stdout".into());
        if output_mode != "stdout" && output_mode != "json_file" {
            return Err(CatalogError(format!(
                "{id}: output_mode invalide '{output_mode}'"
            )));
        }
        let output_path_template = optional_string(map, "output_path_template")?;
        if output_mode == "json_file" && output_path_template.as_deref().is_none_or(str::is_empty) {
            return Err(CatalogError(format!(
                "{id}: output_mode='json_file' requiert 'output_path_template'"
            )));
        }
        if !seen_ids.insert(id.clone()) {
            return Err(CatalogError(format!(
                "id duplique dans le catalogue : {id}"
            )));
        }

        tools.push(ToolSpec {
            id,
            category,
            desc,
            command,
            target_type,
            output_mode,
            output_path_template,
            default_timeout_s: optional_u64(map, "default_timeout_s")?.unwrap_or(60),
            example: optional_string(map, "example")?.unwrap_or_default(),
            nonzero_exit_ok: optional_bool(map, "nonzero_exit_ok")?.unwrap_or(false),
            min_delay_s: optional_f64(map, "min_delay_s")?.unwrap_or(0.0),
            territory_flag: optional_string(map, "territory_flag")?,
        });
    }
    Ok(tools)
}

fn get<'a>(map: &'a Mapping, name: &str) -> Option<&'a Value> {
    map.get(Value::String(name.to_owned()))
}

fn required_string(map: &Mapping, name: &str) -> Result<String, CatalogError> {
    optional_string(map, name)?.ok_or_else(|| {
        CatalogError(format!(
            "Entree catalogue incomplete : champ manquant {name}"
        ))
    })
}

fn optional_string(map: &Mapping, name: &str) -> Result<Option<String>, CatalogError> {
    match get(map, name) {
        None | Some(Value::Null) => Ok(None),
        Some(Value::String(value)) => Ok(Some(value.clone())),
        _ => Err(CatalogError(format!("{name}: texte attendu"))),
    }
}

fn optional_u64(map: &Mapping, name: &str) -> Result<Option<u64>, CatalogError> {
    match get(map, name) {
        None | Some(Value::Null) => Ok(None),
        Some(Value::Number(value)) => value
            .as_u64()
            .map(Some)
            .ok_or_else(|| CatalogError(format!("{name}: entier positif attendu"))),
        _ => Err(CatalogError(format!("{name}: entier positif attendu"))),
    }
}

fn optional_f64(map: &Mapping, name: &str) -> Result<Option<f64>, CatalogError> {
    match get(map, name) {
        None | Some(Value::Null) => Ok(None),
        Some(Value::Number(value)) => value
            .as_f64()
            .map(Some)
            .ok_or_else(|| CatalogError(format!("{name}: nombre attendu"))),
        _ => Err(CatalogError(format!("{name}: nombre attendu"))),
    }
}

fn optional_bool(map: &Mapping, name: &str) -> Result<Option<bool>, CatalogError> {
    match get(map, name) {
        None | Some(Value::Null) => Ok(None),
        Some(Value::Bool(value)) => Ok(Some(*value)),
        _ => Err(CatalogError(format!("{name}: booleen attendu"))),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const VALID: &str = r#"
- id: sherlock
  category: username
  desc: test
  command: ["sherlock", "--print-found", "{target}"]
  target_type: username
"#;

    #[test]
    fn loads_real_catalog_in_source_order() {
        let tools = parse_catalog(include_str!("../../../osintbox/catalog.yaml")).unwrap();
        assert_eq!(
            tools
                .iter()
                .map(|tool| tool.id.as_str())
                .collect::<Vec<_>>(),
            ["sherlock", "maigret", "holehe", "theharvester"]
        );
        assert_eq!(tools[0].default_timeout_s, 180);
        assert_eq!(tools[1].output_mode, "json_file");
        assert_eq!(tools[1].territory_flag.as_deref(), Some("--tags"));
        assert_eq!(
            tools[1].with_territory(Some("fr")).build_argv("alice"),
            [
                "maigret",
                "alice",
                "-J",
                "simple",
                "--no-progressbar",
                "--no-color",
                "--tags",
                "fr"
            ]
        );
        assert_eq!(tools[1].command[1], "{target}");
    }

    #[test]
    fn defaults_and_command_substitution() {
        let tools = parse_catalog(VALID).unwrap();
        assert_eq!(tools[0].default_timeout_s, 60);
        assert_eq!(tools[0].output_mode, "stdout");
        assert_eq!(
            tools[0].build_argv("alice"),
            ["sherlock", "--print-found", "alice"]
        );
        assert!(matches!(
            tools[0].with_territory(Some("fr")),
            Cow::Borrowed(_)
        ));
    }

    #[test]
    fn rejects_invalid_schema() {
        for (source, message) in [
            ("id: not_a_list", "liste"),
            (&VALID.replace("  desc: test\n", ""), "desc"),
            (
                &VALID.replace("target_type: username", "target_type: unknown"),
                "target_type",
            ),
            (&VALID.replace("\"{target}\"", "\"missing\""), "{target}"),
            (&format!("{VALID}{VALID}"), "duplique"),
            (
                &format!("{VALID}  output_mode: json_file\n"),
                "output_path_template",
            ),
        ] {
            assert!(
                parse_catalog(source)
                    .unwrap_err()
                    .to_string()
                    .contains(message),
                "{message}"
            );
        }
    }
}
