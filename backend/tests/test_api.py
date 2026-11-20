"""Backend API tests (Wave 1): health, datasets, upload validation, preview, delete."""
import io

import pandas as pd


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["db"] == "sqlite"
    assert body["datasets"] == 3  # 3 golden datasets seeded on startup


def test_list_datasets_has_golden(client):
    r = client.get("/api/datasets")
    assert r.status_code == 200
    names = [d["name"] for d in r.json()["datasets"]]
    assert any("干净实验数据" in n for n in names)
    assert any("脏数据" in n for n in names)
    assert any("相关性" in n for n in names)
    assert r.json()["total"] == 3


def test_upload_csv_ok(client):
    df = pd.DataFrame({"a": [1, 2, 3], "b": [4.0, 5.0, 6.0]})
    buf = io.BytesIO()
    df.to_csv(buf, index=False)
    r = client.post(
        "/api/datasets/upload",
        files={"file": ("tiny.csv", buf.getvalue(), "text/csv")},
    )
    assert r.status_code == 201 or r.status_code == 200
    body = r.json()
    assert body["rows_count"] == 3 and body["cols_count"] == 2
    assert len(body["file_hash"]) == 64
    # clean up so other tests keep seeing exactly 3 golden datasets
    assert client.delete(f"/api/datasets/{body['id']}").status_code == 200


def test_upload_rejects_bad_extension(client):
    r = client.post(
        "/api/datasets/upload",
        files={"file": ("evil.txt", b"a,b\n1,2\n", "text/plain")},
    )
    assert r.status_code == 400
    assert "CSV / XLSX" in r.json()["detail"]


def test_upload_rejects_empty_file(client):
    r = client.post(
        "/api/datasets/upload",
        files={"file": ("empty.csv", b"", "text/csv")},
    )
    assert r.status_code == 400


def test_upload_rejects_oversize(client):
    big = b"x," * (10 * 1024 * 1024 // 2 + 10)  # just over 10 MB
    r = client.post(
        "/api/datasets/upload",
        files={"file": ("big.csv", big, "text/csv")},
    )
    assert r.status_code == 400
    assert "10 MB" in r.json()["detail"]


def test_preview_golden_clean(client):
    ds = client.get("/api/datasets").json()["datasets"]
    clean = next(d for d in ds if "干净实验数据" in d["name"])
    r = client.get(f"/api/datasets/{clean['id']}/preview?limit=5")
    assert r.status_code == 200
    body = r.json()
    assert body["rows"] == 200 and body["cols"] == 5
    assert len(body["preview_rows"]) == 5
    assert [c["name"] for c in body["columns"]] == [
        "sample_id", "temperature", "humidity", "pressure", "reaction_time",
    ]


def test_preview_missing_dataset_404(client):
    assert client.get("/api/datasets/999999/preview").status_code == 404


def test_delete_missing_dataset_404(client):
    assert client.delete("/api/datasets/999999").status_code == 404


def test_list_analyses_empty(client):
    r = client.get("/api/analyses")
    assert r.status_code == 200
    assert r.json() == {"analyses": [], "total": 0}
