"""The dashboard is an open local view: pages and APIs answer, there is no login, docs resolve under
``DATA_DIR/artifact``, and shutdown closes the hub without raising."""
import asyncio
import json

from aiohttp.test_utils import TestClient, TestServer

from sol_mev.app.dashboard import Hub
from sol_mev.app.dashboard import server


def test_routes_and_clean_shutdown(tmp_path, monkeypatch):
    (tmp_path / "optimal").mkdir()
    (tmp_path / "optimal" / "summary.json").write_text(json.dumps({"ok": 1}))
    monkeypatch.setattr(server, "DOCS", tmp_path)
    hub = Hub()

    async def run():
        client = TestClient(TestServer(server.app(hub)))
        await client.start_server()
        try:
            assert (await client.get("/")).status == 200
            snap = await client.get("/api/snapshot?parts=stats")
            assert snap.status == 200 and "stats" in await snap.json()
            assert (await client.get("/api/doc/optimal/summary")).status == 200
            assert (await client.get("/api/doc/../secret")).status == 404
            assert (await client.get("/login")).status == 404
        finally:
            await client.close()          # runs on_shutdown: must not raise

    asyncio.run(run())


def test_docs_live_under_data_dir():
    from sol_mev.config import DATA_DIR
    assert server.DOCS == DATA_DIR / "artifact"
