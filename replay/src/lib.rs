//! Rootline replay: render evidence packs exported by the Python harness,
//! summarise snapshots straight from Parquet, and validate model output
//! against the Rootline output contract.

use std::collections::BTreeMap;
use std::fs::File;
use std::path::{Path, PathBuf};

use anyhow::{bail, Context, Result};
use arrow::array::{Array, StringArray};
use parquet::arrow::arrow_reader::ParquetRecordBatchReaderBuilder;
use serde::{Deserialize, Serialize};

/// Pack export format this crate understands.
pub const FORMAT: u32 = 1;

/// One evidence line, e.g. `M-0001 svc=payment ...`.
#[derive(Debug, Clone, Deserialize, Serialize, PartialEq)]
pub struct Line {
    pub id: String,
    pub services: Vec<String>,
    pub text: String,
}

/// One signal's section of a pack.
#[derive(Debug, Clone, Deserialize, Serialize, PartialEq)]
pub struct Section {
    pub signal: String,
    pub header: String,
    pub lines: Vec<Line>,
    pub omitted: u32,
}

/// The evidence pack, as `Pack.to_json()` writes it.
#[derive(Debug, Clone, Deserialize, Serialize, PartialEq)]
pub struct Pack {
    pub incident_id: String,
    pub condition: String,
    pub perturbation: String,
    pub sections: Vec<Section>,
}

/// One file written by `rootline_harness.export_packs`.
#[derive(Debug, Clone, Deserialize)]
pub struct PackDocument {
    pub format: u32,
    pub incident_id: String,
    pub condition: String,
    pub perturbation: String,
    pub prompt_tokens: u32,
    pub prompt: String,
    pub rendered: String,
    pub pack: Pack,
}

impl Section {
    /// Mirrors `Section.render()` in harness/rootline_harness/packers/evidence.py.
    pub fn render(&self) -> String {
        let mut out = vec![format!(
            "## {}: {}",
            self.signal.to_uppercase(),
            self.header
        )];
        out.extend(self.lines.iter().map(|l| format!("{} {}", l.id, l.text)));
        if self.lines.is_empty() {
            out.push("(no evidence lines)".to_string());
        }
        if self.omitted > 0 {
            out.push(format!(
                "({} lower-ranked lines omitted for length)",
                self.omitted
            ));
        }
        out.join("\n")
    }
}

impl Pack {
    /// Mirrors `Pack.render()`: sections separated by a blank line.
    pub fn render(&self) -> String {
        self.sections
            .iter()
            .map(Section::render)
            .collect::<Vec<_>>()
            .join("\n\n")
    }

    /// Evidence IDs shown in the pack, with their lines.
    pub fn index(&self) -> BTreeMap<&str, &Line> {
        self.sections
            .iter()
            .flat_map(|s| s.lines.iter())
            .map(|l| (l.id.as_str(), l))
            .collect()
    }
}

/// Read and check a pack document.
pub fn load_pack(path: &Path) -> Result<PackDocument> {
    let raw = std::fs::read_to_string(path).with_context(|| format!("read {}", path.display()))?;
    let doc: PackDocument =
        serde_json::from_str(&raw).with_context(|| format!("parse {}", path.display()))?;
    if doc.format != FORMAT {
        bail!(
            "{}: pack format {} is not supported (want {FORMAT})",
            path.display(),
            doc.format
        );
    }
    Ok(doc)
}

#[derive(Debug, Deserialize)]
struct Manifest {
    incident_id: String,
    t0_unix_ms: i64,
    window_ms: i64,
    #[serde(default)]
    demo_git_tag: String,
}

/// Find a snapshot's exported pack: `<packs>/<incident_id>/<condition>-<perturbation>.json`.
/// By default `packs` is `data/packs` next to `data/snapshots`.
pub fn pack_path(
    snapshot_dir: &Path,
    packs: Option<&Path>,
    condition: &str,
    perturbation: &str,
) -> Result<PathBuf> {
    let manifest = read_manifest(snapshot_dir)?;
    let base = match packs {
        Some(p) => p.to_path_buf(),
        None => snapshot_dir
            .parent()
            .and_then(Path::parent)
            .map(|d| d.join("packs"))
            .context("cannot locate data/packs; pass --packs")?,
    };
    Ok(base
        .join(&manifest.incident_id)
        .join(format!("{condition}-{perturbation}.json")))
}

fn read_manifest(dir: &Path) -> Result<Manifest> {
    let path = dir.join("manifest.json");
    let raw = std::fs::read_to_string(&path).with_context(|| format!("read {}", path.display()))?;
    serde_json::from_str(&raw).with_context(|| format!("parse {}", path.display()))
}

/// Per-service span summary from spans.parquet.
#[derive(Debug, Default, Clone, PartialEq, Eq)]
pub struct ServiceSpans {
    pub spans: u64,
    pub errors: u64,
}

/// What `rootline info` prints.
#[derive(Debug, Clone)]
pub struct SnapshotInfo {
    pub incident_id: String,
    pub demo_git_tag: String,
    pub t0_unix_ms: i64,
    pub window_ms: i64,
    pub rows: BTreeMap<String, usize>,
    pub services: BTreeMap<String, ServiceSpans>,
}

fn count_rows(path: &Path) -> Result<usize> {
    let file = File::open(path).with_context(|| format!("open {}", path.display()))?;
    let builder = ParquetRecordBatchReaderBuilder::try_new(file)?;
    Ok(builder.metadata().file_metadata().num_rows() as usize)
}

fn string_column<'a>(
    batch: &'a arrow::record_batch::RecordBatch,
    name: &str,
) -> Result<&'a StringArray> {
    batch
        .column_by_name(name)
        .with_context(|| format!("missing column {name}"))?
        .as_any()
        .downcast_ref::<StringArray>()
        .with_context(|| format!("column {name} is not a string column"))
}

/// Summarise a snapshot directory straight from its Parquet files.
pub fn snapshot_info(dir: &Path) -> Result<SnapshotInfo> {
    let m = read_manifest(dir)?;
    let mut rows = BTreeMap::new();
    for name in ["spans", "metrics", "logs"] {
        let path = dir.join(format!("{name}.parquet"));
        rows.insert(name.to_string(), count_rows(&path)?);
    }
    let mut services: BTreeMap<String, ServiceSpans> = BTreeMap::new();
    let file = File::open(dir.join("spans.parquet"))?;
    for batch in ParquetRecordBatchReaderBuilder::try_new(file)?.build()? {
        let batch = batch?;
        let svc = string_column(&batch, "service")?;
        let status = string_column(&batch, "status_code")?;
        for i in 0..batch.num_rows() {
            let entry = services.entry(svc.value(i).to_string()).or_default();
            entry.spans += 1;
            if !status.is_null(i) && status.value(i).contains("ERROR") {
                entry.errors += 1;
            }
        }
    }
    Ok(SnapshotInfo {
        incident_id: m.incident_id,
        demo_git_tag: m.demo_git_tag,
        t0_unix_ms: m.t0_unix_ms,
        window_ms: m.window_ms,
        rows,
        services,
    })
}

/// The model output contract (harness/rootline_harness/schema.py).
#[derive(Debug, Clone, Deserialize, Serialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct ModelOutput {
    pub abstain: bool,
    pub layer: String,
    pub hypotheses: Vec<Hypothesis>,
    pub action: Action,
}

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct Hypothesis {
    pub rank: u32,
    pub service: String,
    pub category: String,
    pub confidence: f64,
    pub evidence: Vec<String>,
}

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct Action {
    #[serde(rename = "type")]
    pub kind: String,
    pub target: Option<String>,
}

/// Parse and validate a reply. Like the Python parser, one surrounding
/// Markdown code fence is tolerated.
pub fn parse_output(raw: &str) -> Result<ModelOutput> {
    let text = strip_fence(raw.trim());
    let out: ModelOutput = serde_json::from_str(text).context("invalid JSON or wrong shape")?;
    if !["application", "network", "none"].contains(&out.layer.as_str()) {
        bail!(
            "layer must be application, network or none, got {:?}",
            out.layer
        );
    }
    let mut ranks = Vec::new();
    for h in &out.hypotheses {
        if h.rank < 1 {
            bail!("hypothesis rank must be >= 1");
        }
        if !(0.0..=1.0).contains(&h.confidence) {
            bail!("confidence must be in [0, 1], got {}", h.confidence);
        }
        if h.service.is_empty() || h.category.is_empty() {
            bail!("hypothesis service and category must not be empty");
        }
        ranks.push(h.rank);
    }
    ranks.sort_unstable();
    if ranks.windows(2).any(|w| w[0] == w[1]) {
        bail!("hypothesis ranks must be unique");
    }
    let target = out.action.target.as_deref().unwrap_or("");
    match out.action.kind.as_str() {
        "no_action" if !target.is_empty() => bail!("no_action takes no target"),
        "no_action" => {}
        "restart" | "disable_feature" | "clear_network_fault" if target.is_empty() => {
            bail!("{} needs a target", out.action.kind)
        }
        "restart" | "disable_feature" | "clear_network_fault" => {}
        other => bail!("action {other:?} is not on the menu"),
    }
    Ok(out)
}

fn strip_fence(text: &str) -> &str {
    let Some(rest) = text.strip_prefix("```") else {
        return text;
    };
    let rest = rest.strip_prefix("json").unwrap_or(rest);
    let Some(rest) = rest.strip_prefix('\n') else {
        return text;
    };
    match rest.trim_end().strip_suffix("```") {
        Some(body) => body.trim_end_matches('\n'),
        None => text,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const GOOD: &str = r#"{"abstain": false, "layer": "application",
        "hypotheses": [{"rank": 1, "service": "payment", "category": "error",
                        "confidence": 0.7, "evidence": ["M-0001"]}],
        "action": {"type": "disable_feature", "target": "payment"}}"#;

    #[test]
    fn parses_valid_output_and_fence() {
        assert_eq!(parse_output(GOOD).unwrap().hypotheses[0].service, "payment");
        let fenced = format!("```json\n{GOOD}\n```");
        assert!(parse_output(&fenced).is_ok());
    }

    #[test]
    fn rejects_contract_violations() {
        let cases = [
            ("not json", "invalid JSON"),
            (
                r#"{"abstain":false,"layer":"db","hypotheses":[],"action":{"type":"no_action","target":null}}"#,
                "layer",
            ),
            (
                r#"{"abstain":false,"layer":"none","hypotheses":[],"action":{"type":"exec","target":"sh"}}"#,
                "menu",
            ),
            (
                r#"{"abstain":false,"layer":"none","hypotheses":[],"action":{"type":"restart","target":null}}"#,
                "needs a target",
            ),
            (
                r#"{"abstain":false,"layer":"none","hypotheses":[],"action":{"type":"no_action","target":null},"x":1}"#,
                "invalid JSON",
            ),
            (
                r#"{"abstain":false,"layer":"none","hypotheses":[{"rank":1,"service":"a","category":"b","confidence":1.5,"evidence":[]}],"action":{"type":"no_action","target":null}}"#,
                "confidence",
            ),
        ];
        for (raw, want) in cases {
            let err = format!("{:#}", parse_output(raw).unwrap_err());
            assert!(err.contains(want), "{raw}: {err}");
        }
    }

    #[test]
    fn renders_empty_and_omitted_sections() {
        let s = Section {
            signal: "logs".into(),
            header: "h".into(),
            lines: vec![],
            omitted: 3,
        };
        assert_eq!(
            s.render(),
            "## LOGS: h\n(no evidence lines)\n(3 lower-ranked lines omitted for length)"
        );
    }
}
