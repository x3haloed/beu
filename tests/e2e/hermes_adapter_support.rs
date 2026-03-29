use std::env;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::sync::OnceLock;
use std::time::UNIX_EPOCH;

pub struct HermesInstall {
    pub hermes_repo: PathBuf,
    pub venv_python: PathBuf,
    pub beu_binary: PathBuf,
    _temp_dir: tempfile::TempDir,
}

pub struct HermesHarness {
    install: &'static HermesInstall,
    hermes_repo: PathBuf,
    hermes_home: PathBuf,
    _temp_dir: tempfile::TempDir,
}

static HERMES_INSTALL: OnceLock<&'static HermesInstall> = OnceLock::new();

impl HermesHarness {
    pub fn new(install: &'static HermesInstall) -> Self {
        let hermes_repo = install.hermes_repo.clone();
        let temp_dir = tempfile::tempdir().expect("tempdir");
        let hermes_home = temp_dir.path().join("hermes_home");
        let plugin_root = hermes_home.join("plugins").join("beu");
        fs::create_dir_all(&plugin_root).expect("plugin dir");

        let adapter_dir = hermes_adapter_dir();
        fs::copy(adapter_dir.join("plugin.yaml"), plugin_root.join("plugin.yaml"))
            .expect("copy plugin.yaml");
        fs::copy(adapter_dir.join("__init__.py"), plugin_root.join("__init__.py"))
            .expect("copy __init__.py");

        Self {
            install,
            hermes_repo,
            hermes_home,
            _temp_dir: temp_dir,
        }
    }

    pub fn run_python(&self, script: &str) -> std::process::Output {
        Command::new(&self.install.venv_python)
            .current_dir(&self.hermes_repo)
            .env("BEU_HERMES_AGENT_REPO", &self.hermes_repo)
            .env("HERMES_HOME", &self.hermes_home)
            .env("BEU_BINARY_PATH", &self.install.beu_binary)
            .env("HERMES_ENABLE_PROJECT_PLUGINS", "0")
            .arg("-c")
            .arg(script)
            .output()
            .expect("run python")
    }
}

pub fn hermes_harness() -> HermesHarness {
    HermesHarness::new(hermes_install())
}

fn hermes_install() -> &'static HermesInstall {
    HERMES_INSTALL.get_or_init(|| {
        let hermes_repo = hermes_agent_repo_root().expect(
            "set BEU_HERMES_AGENT_REPO or keep a hermes-agent checkout adjacent to the beu repo",
        );
        let cache_root = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("target")
            .join("e2e-cache")
            .join("hermes");
        fs::create_dir_all(&cache_root).expect("create cache root");
        let cache_key = hermes_cache_key(&hermes_repo);
        let install_dir = cache_root.join(cache_key);
        let venv_dir = install_dir.join("venv");
        let marker = install_dir.join(".ready");

        if !marker.exists() {
            fs::create_dir_all(&install_dir).expect("create install dir");
            if venv_dir.exists() {
                fs::remove_dir_all(&venv_dir).expect("clear stale venv");
            }
            let venv_status = Command::new("python3")
                .arg("-m")
                .arg("venv")
                .arg(&venv_dir)
                .status()
                .expect("create venv");
            assert!(venv_status.success(), "failed to create isolated venv");

            let venv_python = venv_dir.join("bin").join("python");
            let pip_status = Command::new(&venv_python)
                .arg("-m")
                .arg("pip")
                .arg("install")
                .arg("-e")
                .arg(".[all]")
                .current_dir(&hermes_repo)
                .status()
                .expect("install isolated deps");
            assert!(pip_status.success(), "failed to install isolated deps");

            fs::write(&marker, b"ok").expect("write cache marker");
        }

        let cargo_status = Command::new("cargo")
            .arg("build")
            .arg("--bin")
            .arg("beu")
            .current_dir(env!("CARGO_MANIFEST_DIR"))
            .status()
            .expect("build beu binary");
        assert!(cargo_status.success(), "failed to build beu binary");

        let venv_python = venv_dir.join("bin").join("python");

        let beu_binary = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("target/debug/beu");
        let temp_dir = tempfile::tempdir().expect("tempdir");

        Box::leak(Box::new(HermesInstall {
            hermes_repo,
            venv_python,
            beu_binary,
            _temp_dir: temp_dir,
        }))
    })
}

fn hermes_cache_key(hermes_repo: &Path) -> String {
    let mut parts = vec![sanitize_cache_component(&hermes_repo.display().to_string())];
    for rel in ["pyproject.toml", "uv.lock", "requirements.txt"] {
        let stamp = file_stamp(&hermes_repo.join(rel));
        parts.push(format!("{}-{}", rel.replace('.', "_"), stamp));
    }
    parts.join("-")
}

fn file_stamp(path: &Path) -> u64 {
    let meta = fs::metadata(path).ok();
    meta.and_then(|m| m.modified().ok())
        .and_then(|t| t.duration_since(UNIX_EPOCH).ok())
        .map(|d| d.as_secs())
        .unwrap_or_default()
}

fn sanitize_cache_component(value: &str) -> String {
    value
        .chars()
        .map(|ch| match ch {
            'A'..='Z' | 'a'..='z' | '0'..='9' | '-' | '_' => ch,
            _ => '_',
        })
        .collect()
}

fn hermes_agent_repo_root() -> Option<PathBuf> {
    if let Ok(path) = env::var("BEU_HERMES_AGENT_REPO") {
        let candidate = PathBuf::from(path);
        if is_hermes_agent_repo(&candidate) {
            return Some(candidate);
        }
    }

    let cwd = env::current_dir().ok()?;
    let mut search_roots = Vec::new();
    for root in cwd.ancestors() {
        search_roots.push(root.to_path_buf());
        search_roots.push(root.join("hermes-agent"));
    }

    for candidate in search_roots {
        if is_hermes_agent_repo(&candidate) {
            return Some(candidate);
        }
    }

    None
}

fn is_hermes_agent_repo(path: &Path) -> bool {
    path.join("hermes_cli").join("plugins.py").exists()
        && path.join("tests").join("conftest.py").exists()
        && path.join("pyproject.toml").exists()
}

fn hermes_adapter_dir() -> PathBuf {
    env::current_dir()
        .expect("current dir")
        .join("hermes-adapter")
}
