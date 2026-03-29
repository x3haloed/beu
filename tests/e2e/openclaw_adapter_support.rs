use std::env;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::sync::Mutex;
use std::sync::OnceLock;

pub struct OpenClawInstall {
    pub openclaw_repo: PathBuf,
    pub beu_binary: PathBuf,
    _temp_dir: tempfile::TempDir,
}

pub struct OpenClawHarness {
    install: &'static OpenClawInstall,
    openclaw_workspace: PathBuf,
    openclaw_state_dir: PathBuf,
    _temp_dir: tempfile::TempDir,
}

static OPENCLAW_INSTALL: OnceLock<&'static OpenClawInstall> = OnceLock::new();
static OPENCLAW_RUN_LOCK: OnceLock<Mutex<()>> = OnceLock::new();

impl OpenClawHarness {
    pub fn new(install: &'static OpenClawInstall) -> Self {
        let temp_dir = tempfile::tempdir().expect("tempdir");
        let openclaw_workspace = temp_dir.path().join("workspace");
        let openclaw_state_dir = temp_dir.path().join("state");
        fs::create_dir_all(openclaw_workspace.join("node_modules")).expect("workspace dir");
        fs::create_dir_all(&openclaw_state_dir).expect("state dir");

        // Keep module resolution real, but contained to this test workspace.
        #[cfg(unix)]
        std::os::unix::fs::symlink(
            &install.openclaw_repo,
            openclaw_workspace.join("node_modules").join("openclaw"),
        )
        .expect("link openclaw repo");

        #[cfg(windows)]
        std::os::windows::fs::symlink_dir(
            &install.openclaw_repo,
            openclaw_workspace.join("node_modules").join("openclaw"),
        )
        .expect("link openclaw repo");

        Self {
            install,
            openclaw_workspace,
            openclaw_state_dir,
            _temp_dir: temp_dir,
        }
    }

    pub fn run_tsx(&self, script: &str) -> std::process::Output {
        let _guard = OPENCLAW_RUN_LOCK.get_or_init(|| Mutex::new(())).lock().expect("run lock");
        let script_path = self.openclaw_workspace.join("adapter-e2e.ts");
        fs::write(&script_path, script).expect("write tsx script");
        Command::new(self.install.openclaw_repo.join("node_modules").join(".bin").join("tsx"))
            .current_dir(&self.install.openclaw_repo)
            .env("BEU_OPENCLAW_REPO", &self.install.openclaw_repo)
            .env("BEU_BINARY_PATH", &self.install.beu_binary)
            .env("BEU_STATE_DIR", &self.openclaw_state_dir)
            .env("OPENCLAW_WORKSPACE_DIR", &self.openclaw_workspace)
            .env("OPENCLAW_STATE_DIR", &self.openclaw_state_dir)
            .env("OPENCLAW_BUNDLED_PLUGINS_DIR", "/nonexistent/bundled/plugins")
            .env("OPENCLAW_DISABLE_PLUGIN_DISCOVERY_CACHE", "1")
            .env("OPENCLAW_DISABLE_PLUGIN_MANIFEST_CACHE", "1")
            .arg(&script_path)
            .output()
            .expect("run tsx")
    }
}

pub fn openclaw_harness() -> OpenClawHarness {
    OpenClawHarness::new(openclaw_install())
}

fn openclaw_install() -> &'static OpenClawInstall {
    OPENCLAW_INSTALL.get_or_init(|| {
        let openclaw_repo = openclaw_repo_root().expect(
            "set BEU_OPENCLAW_REPO or keep an openclaw checkout adjacent to the beu repo",
        );
        let beu_repo = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
        let beu_adapter_dir = beu_repo.join("openclaw-adapter");

        let temp_dir = tempfile::tempdir().expect("tempdir");

        let required_pkg = openclaw_repo.join("node_modules").join("ipaddr.js");
        if !required_pkg.exists() {
            let pnpm_status = Command::new("pnpm")
                .arg("install")
                .arg("--frozen-lockfile")
                .arg("--ignore-scripts")
                .current_dir(&openclaw_repo)
                .status()
                .expect("install openclaw deps");
            assert!(
                pnpm_status.success(),
                "failed to install openclaw dependencies in the local checkout"
            );
        }

        let jsonrpc_status = Command::new("npm")
            .arg("install")
            .current_dir(&beu_adapter_dir)
            .status()
            .expect("install jsonrpc-lite");
        assert!(jsonrpc_status.success(), "failed to install jsonrpc-lite");

        let beu_status = Command::new("cargo")
            .arg("build")
            .arg("--bin")
            .arg("beu")
            .current_dir(env!("CARGO_MANIFEST_DIR"))
            .status()
            .expect("build beu binary");
        assert!(beu_status.success(), "failed to build beu binary");
        let beu_binary = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("target/debug/beu");

        Box::leak(Box::new(OpenClawInstall {
            openclaw_repo,
            beu_binary,
            _temp_dir: temp_dir,
        }))
    })
}

fn openclaw_repo_root() -> Option<PathBuf> {
    if let Ok(path) = env::var("BEU_OPENCLAW_REPO") {
        let candidate = PathBuf::from(path);
        if is_openclaw_repo(&candidate) {
            return Some(candidate);
        }
    }

    let cwd = env::current_dir().ok()?;
    let mut search_roots = Vec::new();
    for root in cwd.ancestors() {
        search_roots.push(root.to_path_buf());
        search_roots.push(root.join("openclaw"));
    }

    for candidate in search_roots {
        if is_openclaw_repo(&candidate) {
            return Some(candidate);
        }
    }

    None
}

fn is_openclaw_repo(path: &Path) -> bool {
    path.join("src").join("plugins").join("loader.ts").exists()
        && path.join("src").join("plugin-sdk").join("plugin-entry.ts").exists()
        && path.join("package.json").exists()
        && path.join("tsconfig.json").exists()
}
