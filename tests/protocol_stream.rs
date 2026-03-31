use std::io::{BufRead, BufReader, Write};
use std::process::{Command, Stdio};
use std::sync::mpsc;
use std::thread;
use std::time::Duration;

fn request(id: &str, command: &str, payload: serde_json::Value) -> String {
    serde_json::json!({
        "version": "1.0.0",
        "command": command,
        "id": id,
        "namespace": "stream-test",
        "payload": payload,
    })
    .to_string()
        + "\n"
}

#[test]
fn protocol_handles_new_requests_while_one_is_blocked() {
    let temp_dir = tempfile::tempdir().expect("tempdir");
    let db_dir = temp_dir.path().join("state");
    std::fs::create_dir_all(&db_dir).expect("state dir");

    let mut child = Command::new(env!("CARGO_BIN_EXE_beu"))
        .env("BEU_STATE_DIR", &db_dir)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .expect("spawn beu");

    let mut stdin = child.stdin.take().expect("child stdin");
    let stdout = child.stdout.take().expect("child stdout");
    let stderr = child.stderr.take().expect("child stderr");

    let (tx, rx) = mpsc::channel::<serde_json::Value>();
    thread::spawn(move || {
        let reader = BufReader::new(stdout);
        for line in reader.lines() {
            let line = line.expect("stdout line");
            let value: serde_json::Value = serde_json::from_str(&line).expect("json response");
            tx.send(value).expect("send response");
        }
    });

    let (stderr_tx, stderr_rx) = mpsc::channel::<String>();
    let stderr_handle = thread::spawn(move || {
        let mut reader = BufReader::new(stderr);
        let mut buf = String::new();
        let mut collected = String::new();
        while reader.read_line(&mut buf).expect("stderr read") > 0 {
            collected.push_str(&buf);
            buf.clear();
        }
        let _ = stderr_tx.send(collected);
    });

    stdin
        .write_all(
            request(
                "hold-1",
                "wait_hold",
                serde_json::json!({"token": "release-me"}),
            )
            .as_bytes(),
        )
        .expect("write hold");

    stdin
        .write_all(
            request(
                "idx-1",
                "index",
                serde_json::json!({
                    "entries": [{
                        "entry_id": "entry-1",
                        "source_type": "ledger_entry",
                        "source_id": "turn-1",
                        "content": "User prefers detailed explanations",
                        "metadata": {
                            "kind": "user_turn",
                            "thread_id": "stream-test"
                        }
                    }]
                }),
            )
            .as_bytes(),
        )
        .expect("write index");
    stdin.flush().expect("flush writes");

    let mut seen_index = None;
    for _ in 0..20 {
        if let Ok(value) = rx.recv_timeout(Duration::from_millis(500)) {
            if value["id"] == "idx-1" {
                seen_index = Some(value);
                break;
            }
        }
    }

    let index_response = match seen_index {
        Some(value) => value,
        None => {
            let stderr_output = stderr_rx
                .recv_timeout(Duration::from_secs(1))
                .unwrap_or_default();
            let _ = child.kill();
            panic!(
                "expected index response before release\nstderr:\n{}",
                stderr_output
            );
        }
    };
    assert_eq!(index_response["ok"], true);

    stdin
        .write_all(
            request(
                "rel-1",
                "wait_release",
                serde_json::json!({"token": "release-me"}),
            )
            .as_bytes(),
        )
        .expect("write release");
    stdin.flush().expect("flush release");
    drop(stdin);

    let mut hold_response = None;
    let mut release_response = None;
    for _ in 0..20 {
        if hold_response.is_some() && release_response.is_some() {
            break;
        }
        match rx.recv_timeout(Duration::from_millis(500)) {
            Ok(value) => match value["id"].as_str() {
                Some("hold-1") => hold_response = Some(value),
                Some("rel-1") => release_response = Some(value),
                _ => {}
            },
            Err(mpsc::RecvTimeoutError::Timeout) => continue,
            Err(mpsc::RecvTimeoutError::Disconnected) => break,
        }
    }

    let hold_response = hold_response.expect("missing wait_hold response");
    let release_response = release_response.expect("missing wait_release response");
    assert_eq!(hold_response["ok"], true);
    assert_eq!(release_response["ok"], true);

    let status = child.wait().expect("wait on beu");
    assert!(status.success(), "beu exited unsuccessfully");

    let _ = stderr_handle.join();
    let _ = stderr_rx.recv_timeout(Duration::from_secs(1));
}

#[test]
fn protocol_handles_index_while_a_request_is_blocked() {
    let temp_dir = tempfile::tempdir().expect("tempdir");
    let db_dir = temp_dir.path().join("state");
    std::fs::create_dir_all(&db_dir).expect("state dir");

    let mut child = Command::new(env!("CARGO_BIN_EXE_beu"))
        .env("BEU_STATE_DIR", &db_dir)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .expect("spawn beu");

    let mut stdin = child.stdin.take().expect("child stdin");
    let stdout = child.stdout.take().expect("child stdout");
    let stderr = child.stderr.take().expect("child stderr");

    let (tx, rx) = mpsc::channel::<serde_json::Value>();
    thread::spawn(move || {
        let reader = BufReader::new(stdout);
        for line in reader.lines() {
            let line = line.expect("stdout line");
            let value: serde_json::Value = serde_json::from_str(&line).expect("json response");
            tx.send(value).expect("send response");
        }
    });

    let stderr_handle = thread::spawn(move || {
        let mut reader = BufReader::new(stderr);
        let mut buf = String::new();
        while reader.read_line(&mut buf).expect("stderr read") > 0 {
            buf.clear();
        }
    });

    stdin
        .write_all(
            request(
                "hold-1",
                "wait_hold",
                serde_json::json!({"token": "release-me-2"}),
            )
            .as_bytes(),
        )
        .expect("write hold");

    stdin
        .write_all(
            request(
                "idx-1",
                "index",
                serde_json::json!({
                    "entries": [{
                        "entry_id": "entry-overlap-1",
                        "source_type": "ledger_entry",
                        "source_id": "turn-overlap-1",
                        "content": "User wants the real database-backed path",
                        "metadata": {
                            "kind": "invariant",
                            "thread_id": "stream-test"
                        }
                    }]
                }),
            )
            .as_bytes(),
        )
        .expect("write index");
    stdin.flush().expect("flush writes");

    let index_response = loop {
        match rx.recv_timeout(Duration::from_secs(10)) {
            Ok(value) if value["id"] == "idx-1" => break value,
            Ok(_) => continue,
            Err(err) => panic!("timed out waiting for index response: {err:?}"),
        }
    };
    assert_eq!(index_response["ok"], true);
    assert_eq!(index_response["data"]["indexed"], 1);

    stdin
        .write_all(
            request(
                "rel-1",
                "wait_release",
                serde_json::json!({"token": "release-me-2"}),
            )
            .as_bytes(),
        )
        .expect("write release");
    stdin.flush().expect("flush release");
    drop(stdin);

    let mut hold_response = None;
    let mut release_response = None;
    for _ in 0..20 {
        if hold_response.is_some() && release_response.is_some() {
            break;
        }
        match rx.recv_timeout(Duration::from_millis(500)) {
            Ok(value) => match value["id"].as_str() {
                Some("hold-1") => hold_response = Some(value),
                Some("rel-1") => release_response = Some(value),
                _ => {}
            },
            Err(mpsc::RecvTimeoutError::Timeout) => continue,
            Err(mpsc::RecvTimeoutError::Disconnected) => break,
        }
    }

    assert!(hold_response.is_some(), "missing wait_hold response");
    assert!(release_response.is_some(), "missing wait_release response");

    let status = child.wait().expect("wait on beu");
    assert!(status.success(), "beu exited unsuccessfully");

    let _ = stderr_handle.join();
}
