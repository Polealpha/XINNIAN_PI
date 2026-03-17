from backend.assistant_store import AssistantWorkspaceStore


def test_assistant_workspace_store_todo_and_memory(tmp_path):
    store = AssistantWorkspaceStore(str(tmp_path))

    created = store.create_todo(1, title="买麦克风", details="给机器人接 USB 麦")
    assert created["title"] == "买麦克风"
    assert created["state"] == "open"

    updated = store.update_todo(1, created["id"], {"state": "done"})
    assert updated["state"] == "done"

    note = store.write_note(1, "硬件规划", "先接相机，再接两个舵机。")
    assert note["path"].endswith(".md")

    results = store.search_memory(1, "舵机", limit=5)
    assert results
    assert any("舵机" in item["snippet"] for item in results)
