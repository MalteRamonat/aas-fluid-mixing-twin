"""The BaSyx client, exercised against a mock transport — no server needed.

The live round trip is ``tests/test_basyx_integration.py``; these tests pin the client's
contract with the AAS Part-2 API: identifier encoding, create-or-replace semantics,
paging, attachment upload shape and operation-result parsing.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from basyx.aas import model
from basyx.aas.model import datatypes

from aas_fluid_twin.aas.traverse import id_short_paths
from aas_fluid_twin.client import BasyxClient, BasyxError, encode_id, encode_path


def test_identifier_encoding_is_base64url_without_padding() -> None:
    assert encode_id("https://ramonat.dev/modva/aas/Plant/ModVA/001") == (
        "aHR0cHM6Ly9yYW1vbmF0LmRldi9tb2R2YS9hYXMvUGxhbnQvTW9kVkEvMDAx"
    )
    assert "=" not in encode_id("ab")  # 'ab' would pad to 'YWI=' in plain base64


def test_id_short_paths_are_percent_encoded_for_urls() -> None:
    """Tomcat rejects raw brackets in a URL path with HTTP 400."""
    assert encode_path("Documents[0].DocumentVersions[0].DigitalFiles[0]") == (
        "Documents%5B0%5D.DocumentVersions%5B0%5D.DigitalFiles%5B0%5D"
    )
    assert encode_path("Segments.Linked_dataset_10_leakage.Query") == (
        "Segments.Linked_dataset_10_leakage.Query"
    )


class _Server:
    """A minimal in-memory stand-in for the repository, driven through httpx.MockTransport."""

    def __init__(self) -> None:
        self.submodels: dict[str, dict[str, Any]] = {}
        self.shells: dict[str, dict[str, Any]] = {}
        self.attachments: dict[tuple[str, str], tuple[str, bytes]] = {}
        self.requests: list[tuple[str, str]] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append((request.method, request.url.path))
        path = request.url.path
        if path == "/actuator/health":
            return httpx.Response(200, json={"status": "UP"})
        if path == "/submodels" and request.method == "GET":
            items = list(self.submodels.values())
            cursor = request.url.params.get("cursor")
            limit = int(request.url.params.get("limit", 100))
            start = int(cursor) if cursor else 0
            page = items[start : start + limit]
            meta = {"cursor": str(start + limit)} if start + limit < len(items) else {}
            return httpx.Response(200, json={"result": page, "paging_metadata": meta})
        if path.startswith("/submodels/"):
            parts = path.split("/")
            key = parts[2]
            if len(parts) == 3:
                if request.method == "GET":
                    if key not in self.submodels:
                        return httpx.Response(404, json={"messages": [{"text": "not found"}]})
                    return httpx.Response(200, json=self.submodels[key])
                if request.method == "PUT":
                    if key not in self.submodels:
                        return httpx.Response(404)
                    self.submodels[key] = json.loads(request.content)
                    return httpx.Response(204)
            if len(parts) >= 6 and parts[-1] == "attachment":
                element_path = parts[4]
                if request.method == "PUT":
                    body = request.content
                    self.attachments[(key, element_path)] = (
                        request.headers.get("content-type", ""),
                        body,
                    )
                    return httpx.Response(204)
                if request.method == "GET":
                    stored = self.attachments.get((key, element_path))
                    if stored is None:
                        return httpx.Response(404)
                    return httpx.Response(200, content=b"payload")
            if len(parts) >= 6 and parts[-1] == "invoke":
                return httpx.Response(
                    200,
                    json={
                        "success": True,
                        "outputArguments": [
                            {
                                "value": {
                                    "modelType": "Property",
                                    "idShort": "runId",
                                    "valueType": "xs:string",
                                    "value": "run-42",
                                }
                            },
                            {
                                "value": {
                                    "modelType": "Property",
                                    "idShort": "status",
                                    "valueType": "xs:string",
                                    "value": "queued",
                                }
                            },
                        ],
                    },
                )
        if path == "/submodels" and request.method == "POST":
            payload = json.loads(request.content)
            self.submodels[encode_id(payload["id"])] = payload
            return httpx.Response(201, json=payload)
        return httpx.Response(500, text=f"unhandled {request.method} {path}")


@pytest.fixture
def server() -> _Server:
    return _Server()


@pytest.fixture
def client(server: _Server, monkeypatch: pytest.MonkeyPatch) -> BasyxClient:
    c = BasyxClient("http://basyx.test")
    c._http = httpx.Client(
        base_url="http://basyx.test", transport=httpx.MockTransport(server.handle)
    )
    return c


def _submodel(identifier: str) -> model.Submodel:
    return model.Submodel(
        id_=identifier,
        id_short="S",
        submodel_element=[model.Property("p", datatypes.Int, 3)],
    )


def test_put_falls_back_to_post_when_absent(client: BasyxClient, server: _Server) -> None:
    sm = _submodel("urn:sm:1")
    client.put_submodel(sm)
    assert server.requests[-2:] == [
        ("PUT", f"/submodels/{encode_id('urn:sm:1')}"),
        ("POST", "/submodels"),
    ]
    client.put_submodel(sm)  # second time: PUT succeeds, no POST
    assert server.requests[-1] == ("PUT", f"/submodels/{encode_id('urn:sm:1')}")


def test_get_submodel_returns_sdk_objects(client: BasyxClient) -> None:
    client.put_submodel(_submodel("urn:sm:2"))
    back = client.get_submodel("urn:sm:2")
    assert isinstance(back, model.Submodel)
    prop = back.get_referable("p")
    assert isinstance(prop, model.Property)
    assert prop.value == 3


def test_listing_follows_paging_cursors(client: BasyxClient) -> None:
    for i in range(7):
        client.put_submodel(_submodel(f"urn:sm:{i}"))
    ids = client.list_submodel_ids()
    assert ids == [f"urn:sm:{i}" for i in range(7)]


def test_errors_carry_status_and_body(client: BasyxClient) -> None:
    with pytest.raises(BasyxError, match="HTTP 404") as info:
        client.get_submodel("urn:absent")
    assert info.value.status_code == 404


def test_attachment_upload_is_multipart_with_file_name(
    client: BasyxClient, server: _Server
) -> None:
    client.upload_attachment("urn:sm:x", "Segments.Seg.File", "run.csv", b"a,b\n1,2\n", "text/csv")
    content_type, body = server.attachments[(encode_id("urn:sm:x"), "Segments.Seg.File")]
    assert content_type.startswith("multipart/form-data")
    assert b'name="fileName"' in body and b"run.csv" in body
    assert b'name="file"' in body and b"a,b" in body
    assert client.download_attachment("urn:sm:x", "Segments.Seg.File") == b"payload"


def test_invoke_parses_output_arguments(client: BasyxClient) -> None:
    result = client.invoke(
        "urn:sm:sim", "RunSimulation", [model.Property("stopTime", datatypes.Double, 600.0)]
    )
    assert result.success
    assert result.outputs == {"runId": "run-42", "status": "queued"}


# --- idShortPath convention -------------------------------------------------------


def test_id_short_paths_index_list_children() -> None:
    inner = model.SubmodelElementCollection(
        "Version", value=[model.Property("Title", datatypes.String, "t")]
    )
    versions = model.SubmodelElementList(
        "DocumentVersions", model.SubmodelElementCollection, value=[inner]
    )
    doc = model.SubmodelElementCollection("Doc", value=[versions])
    documents = model.SubmodelElementList("Documents", model.SubmodelElementCollection, value=[doc])
    sm = model.Submodel("urn:sm:paths", submodel_element=[documents])
    paths = [p for p, _ in id_short_paths(sm)]
    assert paths == [
        "Documents",
        "Documents[0]",
        "Documents[0].DocumentVersions",
        "Documents[0].DocumentVersions[0]",
        "Documents[0].DocumentVersions[0].Title",
    ]
