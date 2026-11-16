//! Golden tests: the Rust renderer must reproduce the Python packer's
//! output exactly. Fixtures come from harness/tests/test_export_packs.py.

use std::path::{Path, PathBuf};

use rootline::{load_pack, pack_path, snapshot_info};

fn fixtures() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("tests/fixtures")
}

#[test]
fn rendering_matches_python() {
    for case in ["combined-p0", "logs-p1"] {
        let doc = load_pack(&fixtures().join(format!("{case}.json"))).unwrap();
        let expected =
            std::fs::read_to_string(fixtures().join(format!("{case}.expected.txt"))).unwrap();
        assert_eq!(doc.pack.render() + "\n", expected, "{case}");
        assert_eq!(doc.pack.render(), doc.rendered, "{case}");
    }
}

#[test]
fn index_covers_every_line() {
    let doc = load_pack(&fixtures().join("combined-p0.json")).unwrap();
    let index = doc.pack.index();
    let total: usize = doc.pack.sections.iter().map(|s| s.lines.len()).sum();
    assert_eq!(index.len(), total);
    assert!(index.contains_key("M-0001"));
}

#[test]
fn info_reads_the_snapshotter_fixture() {
    let dir =
        Path::new(env!("CARGO_MANIFEST_DIR")).join("../snapshotter/testdata/fixture-snapshot");
    let info = snapshot_info(&dir).unwrap();
    assert_eq!(info.incident_id, "paymentFailure-r1");
    assert_eq!(info.rows["spans"], 2);
    assert_eq!(info.rows["metrics"], 10);
    assert_eq!(info.rows["logs"], 2);
    assert_eq!(info.services["payment"].errors, 1);
    assert_eq!(info.services["checkout"].spans, 1);
}

#[test]
fn pack_path_defaults_to_data_packs() {
    let dir =
        Path::new(env!("CARGO_MANIFEST_DIR")).join("../snapshotter/testdata/fixture-snapshot");
    let p = pack_path(&dir, None, "logs", "p1").unwrap();
    assert!(
        p.ends_with("packs/paymentFailure-r1/logs-p1.json"),
        "{}",
        p.display()
    );
}
