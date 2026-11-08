//! `rootline`: replay Rootline evidence packs without Python.

use std::path::PathBuf;
use std::time::Duration;

use anyhow::{bail, Context, Result};
use clap::{Parser, Subcommand, ValueEnum};
use rootline::{load_pack, pack_path, parse_output, snapshot_info};
use serde_json::json;

#[derive(Parser)]
#[command(
    name = "rootline",
    version,
    about = "Replay Rootline incident snapshots"
)]
struct Cli {
    #[command(subcommand)]
    command: Command,
}

#[derive(Clone, Copy, ValueEnum)]
enum Condition {
    Metrics,
    Traces,
    Logs,
    Combined,
}

impl Condition {
    fn as_str(self) -> &'static str {
        match self {
            Condition::Metrics => "metrics",
            Condition::Traces => "traces",
            Condition::Logs => "logs",
            Condition::Combined => "combined",
        }
    }
}

#[derive(Clone, Copy, ValueEnum)]
enum Perturb {
    P0,
    P1,
}

#[derive(Subcommand)]
enum Command {
    /// Print a snapshot's evidence pack, or send its prompt to a local model.
    Replay {
        /// Snapshot directory, e.g. data/snapshots/paymentFailure-r1
        incident_dir: PathBuf,
        #[arg(long, value_enum, default_value = "combined")]
        condition: Condition,
        #[arg(long, value_enum, default_value = "p0")]
        perturb: Perturb,
        /// Exported packs directory (default: data/packs beside data/snapshots)
        #[arg(long)]
        packs: Option<PathBuf>,
        /// Print the full prompt instead of the pack
        #[arg(long)]
        prompt: bool,
        /// Send the prompt to a local model, e.g. ollama/qwen3:4b
        #[arg(long)]
        model: Option<String>,
        #[arg(long, default_value = "http://localhost:11434")]
        ollama_url: String,
    },
    /// Summarise a snapshot from its Parquet files and manifest.
    Info { incident_dir: PathBuf },
}

fn main() -> Result<()> {
    match Cli::parse().command {
        Command::Replay {
            incident_dir,
            condition,
            perturb,
            packs,
            prompt,
            model,
            ollama_url,
        } => {
            let pert = match perturb {
                Perturb::P0 => "p0",
                Perturb::P1 => "p1",
            };
            let path = pack_path(&incident_dir, packs.as_deref(), condition.as_str(), pert)?;
            let doc = load_pack(&path).with_context(|| {
                "export packs first: uv run --project harness python -m rootline_harness.export_packs"
            })?;
            let rendered = doc.pack.render();
            if rendered != doc.rendered {
                eprintln!("warning: pack rendering differs from the Python packer's");
            }
            match model {
                None if prompt => println!("{}", doc.prompt),
                None => println!("{rendered}"),
                Some(m) => ask(&m, &ollama_url, &doc)?,
            }
            eprintln!("[{} prompt tokens]", doc.prompt_tokens);
        }
        Command::Info { incident_dir } => {
            let info = snapshot_info(&incident_dir)?;
            println!("incident   {}", info.incident_id);
            println!(
                "demo tag   {}",
                if info.demo_git_tag.is_empty() {
                    "(not recorded)"
                } else {
                    &info.demo_git_tag
                }
            );
            println!(
                "t0         {} (window {} s)",
                info.t0_unix_ms,
                info.window_ms / 1000
            );
            for (name, n) in &info.rows {
                println!("{name:<10} {n} rows");
            }
            println!("\n{:<24} {:>8} {:>8}", "service", "spans", "errors");
            for (svc, s) in &info.services {
                println!("{svc:<24} {:>8} {:>8}", s.spans, s.errors);
            }
        }
    }
    Ok(())
}

/// Send the prompt to Ollama at temperature 0, then print the validated
/// answer with the evidence lines it cites.
fn ask(model: &str, url: &str, doc: &rootline::PackDocument) -> Result<()> {
    let Some(name) = model.strip_prefix("ollama/") else {
        bail!("only ollama/<name> models are supported, got {model}");
    };
    let client = reqwest::blocking::Client::builder()
        .timeout(Duration::from_secs(600))
        .build()?;
    let resp: serde_json::Value = client
        .post(format!("{}/api/generate", url.trim_end_matches('/')))
        .json(&json!({
            "model": name,
            "prompt": doc.prompt,
            "stream": false,
            "format": "json",
            "options": {"temperature": 0, "seed": 0},
        }))
        .send()
        .with_context(|| format!("is Ollama running at {url}?"))?
        .error_for_status()?
        .json()?;
    let raw = resp["response"].as_str().unwrap_or_default();
    let out = parse_output(raw).with_context(|| format!("model reply: {raw}"))?;
    println!("{}", serde_json::to_string_pretty(&out)?);
    let index = doc.pack.index();
    for h in &out.hypotheses {
        println!(
            "\n#{} {} / {} ({:.2})",
            h.rank, h.service, h.category, h.confidence
        );
        for id in &h.evidence {
            match index.get(id.as_str()) {
                Some(line) => println!("  {} {}", line.id, line.text),
                None => println!("  {id} (not in the pack)"),
            }
        }
    }
    Ok(())
}
