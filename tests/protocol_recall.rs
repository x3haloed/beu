use beu::protocol::Protocol;
use beu::storage::Db;
use beu::types::Request;

#[tokio::test]
async fn protocol_recall_searches_indexed_memory() {
    let db = Db::open_in_memory().await.unwrap();

    let index_request = Request {
        version: "1.0.0".to_string(),
        command: "index".to_string(),
        id: "idx-1".to_string(),
        namespace: Some("agent-123".to_string()),
        payload: serde_json::json!({
            "entries": [{
                "entry_id": "entry-1",
                "source_type": "user_turn",
                "source_id": "turn-1",
                "content": "User prefers verbose responses",
                "metadata": { "thread_id": "thread-1", "turn_id": "turn-1" }
            }]
        }),
    };

    let index_response = Protocol::handle_request(index_request, &db).await;
    assert!(matches!(index_response.status, beu::types::ResponseStatus::Ok { .. }));

    let recall_request = Request {
        version: "1.0.0".to_string(),
        command: "recall".to_string(),
        id: "rec-1".to_string(),
        namespace: Some("agent-123".to_string()),
        payload: serde_json::json!({
            "query": "verbose responses",
            "limit": 5
        }),
    };

    let recall_response = Protocol::handle_request(recall_request, &db).await;
    let data = match recall_response.status {
        beu::types::ResponseStatus::Ok { data, .. } => data,
        other => panic!("expected ok response, got {other:?}"),
    };

    let hits = data["hits"].as_array().unwrap();
    assert_eq!(hits.len(), 1);
    assert_eq!(hits[0]["source_type"], "user_turn");
    assert_eq!(hits[0]["source_id"], "turn-1");
}

#[tokio::test]
async fn protocol_recall_honors_namespace_and_source_filters() {
    let db = Db::open_in_memory().await.unwrap();

    let default_index = Request {
        version: "1.0.0".to_string(),
        command: "index".to_string(),
        id: "idx-default".to_string(),
        namespace: Some("default".to_string()),
        payload: serde_json::json!({
            "entries": [{
                "entry_id": "entry-default",
                "source_type": "user_turn",
                "source_id": "turn-default",
                "content": "User prefers detailed explanations",
                "metadata": { "thread_id": "thread-default", "turn_id": "turn-default" }
            }]
        }),
    };
    let agent_index = Request {
        version: "1.0.0".to_string(),
        command: "index".to_string(),
        id: "idx-agent".to_string(),
        namespace: Some("agent-123".to_string()),
        payload: serde_json::json!({
            "entries": [{
                "entry_id": "entry-agent",
                "source_type": "assistant_turn",
                "source_id": "turn-agent",
                "content": "User prefers short answers",
                "metadata": { "thread_id": "thread-agent", "turn_id": "turn-agent" }
            }]
        }),
    };

    assert!(matches!(
        Protocol::handle_request(default_index, &db).await.status,
        beu::types::ResponseStatus::Ok { .. }
    ));
    assert!(matches!(
        Protocol::handle_request(agent_index, &db).await.status,
        beu::types::ResponseStatus::Ok { .. }
    ));

    let default_recall = Request {
        version: "1.0.0".to_string(),
        command: "recall".to_string(),
        id: "rec-default".to_string(),
        namespace: Some("default".to_string()),
        payload: serde_json::json!({
            "query": "detailed explanations",
            "limit": 5
        }),
    };
    let default_response = Protocol::handle_request(default_recall, &db).await;
    let default_data = match default_response.status {
        beu::types::ResponseStatus::Ok { data, .. } => data,
        other => panic!("expected ok response for default namespace, got {other:?}"),
    };
    let default_hits = default_data["hits"].as_array().unwrap();
    assert_eq!(default_hits.len(), 1);
    assert_eq!(default_hits[0]["source_type"], "user_turn");
    assert_eq!(default_hits[0]["source_id"], "turn-default");

    let agent_recall = Request {
        version: "1.0.0".to_string(),
        command: "recall".to_string(),
        id: "rec-agent".to_string(),
        namespace: Some("agent-123".to_string()),
        payload: serde_json::json!({
            "query": "short answers",
            "limit": 5
        }),
    };
    let agent_response = Protocol::handle_request(agent_recall, &db).await;
    let agent_data = match agent_response.status {
        beu::types::ResponseStatus::Ok { data, .. } => data,
        other => panic!("expected ok response for agent namespace, got {other:?}"),
    };
    let agent_hits = agent_data["hits"].as_array().unwrap();
    assert_eq!(agent_hits.len(), 1);
    assert_eq!(agent_hits[0]["source_type"], "assistant_turn");
    assert_eq!(agent_hits[0]["source_id"], "turn-agent");
}
