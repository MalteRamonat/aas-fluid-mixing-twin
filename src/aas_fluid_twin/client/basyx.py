"""A thin client for the AAS Part-2 HTTP API as served by Eclipse BaSyx.

``basyx-python-sdk`` models the AAS but ships no repository client, so this module is the
bridge: it speaks the standard endpoints (``/shells``, ``/submodels``,
``/concept-descriptions``, ``…/attachment``, ``…/invoke``) and BaSyx's AASX upload, moving
SDK objects in and out through the SDK's own JSON encoder/decoder so nothing is hand-mapped.

Identifiers travel base64url-encoded in paths, as the API specification requires.
"""

from __future__ import annotations

import base64
import json
import urllib.parse
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from basyx.aas import model
from basyx.aas.adapter.json import AASToJsonEncoder, StrictAASFromJsonDecoder

__all__ = ["BasyxClient", "BasyxError", "OperationResult", "encode_id", "encode_path"]


def encode_id(identifier: str) -> str:
    """Base64url without padding, per the AAS API specification."""
    return base64.urlsafe_b64encode(identifier.encode("utf-8")).decode("ascii").rstrip("=")


def encode_path(id_short_path: str) -> str:
    """Percent-encode an idShortPath for use in a URL path.

    List indices (``Documents[0]``) contain ``[`` and ``]``, which Tomcat rejects unencoded.
    """
    return urllib.parse.quote(id_short_path, safe=".")


class BasyxError(RuntimeError):
    def __init__(self, response: httpx.Response, what: str) -> None:
        detail = response.text[:500]
        super().__init__(f"{what}: HTTP {response.status_code} {response.reason_phrase} — {detail}")
        self.status_code = response.status_code


@dataclass(frozen=True, slots=True)
class OperationResult:
    """What an invoked operation returned."""

    success: bool
    outputs: dict[str, Any]
    raw: dict[str, Any]


def _to_json(obj: model.Referable | model.Identifiable) -> Any:
    return json.loads(json.dumps(obj, cls=AASToJsonEncoder))


def _from_json(payload: Any) -> Any:
    return json.loads(json.dumps(payload), cls=StrictAASFromJsonDecoder)


class BasyxClient:
    """Synchronous client for one AAS environment (repository) base URL."""

    def __init__(self, base_url: str, *, timeout: float = 60.0) -> None:
        self.base_url = base_url.rstrip("/")
        self._http = httpx.Client(base_url=self.base_url, timeout=timeout)

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> BasyxClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # --- health ---------------------------------------------------------------

    def is_up(self) -> bool:
        try:
            response = self._http.get("/actuator/health", timeout=5.0)
        except httpx.HTTPError:
            return False
        return response.status_code == 200 and response.json().get("status") == "UP"

    # --- paging ---------------------------------------------------------------

    def _paged(self, path: str, limit: int = 100) -> Iterator[dict[str, Any]]:
        cursor: str | None = None
        while True:
            params: dict[str, Any] = {"limit": limit}
            if cursor:
                params["cursor"] = cursor
            response = self._http.get(path, params=params)
            if response.status_code != 200:
                raise BasyxError(response, f"GET {path}")
            body = response.json()
            yield from body.get("result", [])
            cursor = (body.get("paging_metadata") or {}).get("cursor")
            if not cursor:
                return

    # --- shells ---------------------------------------------------------------

    def list_shell_ids(self) -> list[str]:
        return [str(s["id"]) for s in self._paged("/shells")]

    def get_shell(self, aas_id: str) -> model.AssetAdministrationShell:
        response = self._http.get(f"/shells/{encode_id(aas_id)}")
        if response.status_code != 200:
            raise BasyxError(response, f"GET shell {aas_id}")
        shell = _from_json(response.json())
        assert isinstance(shell, model.AssetAdministrationShell)
        return shell

    def put_shell(self, shell: model.AssetAdministrationShell) -> None:
        """Create or replace."""
        payload = _to_json(shell)
        response = self._http.put(f"/shells/{encode_id(shell.id)}", json=payload)
        if response.status_code == 404:
            response = self._http.post("/shells", json=payload)
        if response.status_code not in (200, 201, 204):
            raise BasyxError(response, f"PUT shell {shell.id}")

    def delete_shell(self, aas_id: str) -> None:
        response = self._http.delete(f"/shells/{encode_id(aas_id)}")
        if response.status_code not in (200, 204, 404):
            raise BasyxError(response, f"DELETE shell {aas_id}")

    # --- submodels ------------------------------------------------------------

    def list_submodel_ids(self) -> list[str]:
        return [str(s["id"]) for s in self._paged("/submodels")]

    def get_submodel(self, submodel_id: str) -> model.Submodel:
        response = self._http.get(f"/submodels/{encode_id(submodel_id)}")
        if response.status_code != 200:
            raise BasyxError(response, f"GET submodel {submodel_id}")
        submodel = _from_json(response.json())
        assert isinstance(submodel, model.Submodel)
        return submodel

    def get_submodel_json(self, submodel_id: str) -> dict[str, Any]:
        response = self._http.get(f"/submodels/{encode_id(submodel_id)}")
        if response.status_code != 200:
            raise BasyxError(response, f"GET submodel {submodel_id}")
        body: dict[str, Any] = response.json()
        return body

    def put_submodel(self, submodel: model.Submodel) -> None:
        payload = _to_json(submodel)
        response = self._http.put(f"/submodels/{encode_id(submodel.id)}", json=payload)
        if response.status_code == 404:
            response = self._http.post("/submodels", json=payload)
        if response.status_code not in (200, 201, 204):
            raise BasyxError(response, f"PUT submodel {submodel.id}")

    def delete_submodel(self, submodel_id: str) -> None:
        response = self._http.delete(f"/submodels/{encode_id(submodel_id)}")
        if response.status_code not in (200, 204, 404):
            raise BasyxError(response, f"DELETE submodel {submodel_id}")

    def get_element_value(self, submodel_id: str, id_short_path: str) -> Any:
        response = self._http.get(
            f"/submodels/{encode_id(submodel_id)}/submodel-elements/{encode_path(id_short_path)}/$value"
        )
        if response.status_code != 200:
            raise BasyxError(response, f"GET value {submodel_id} {id_short_path}")
        return response.json()

    def put_element(
        self, submodel_id: str, id_short_path: str, element: model.SubmodelElement
    ) -> None:
        response = self._http.put(
            f"/submodels/{encode_id(submodel_id)}/submodel-elements/{encode_path(id_short_path)}",
            json=_to_json(element),
        )
        if response.status_code not in (200, 201, 204):
            raise BasyxError(response, f"PUT element {submodel_id} {id_short_path}")

    def post_element(
        self, submodel_id: str, parent_path: str | None, element: model.SubmodelElement
    ) -> None:
        """Add an element to a submodel (or to a collection inside it)."""
        path = f"/submodels/{encode_id(submodel_id)}/submodel-elements"
        if parent_path:
            path += f"/{parent_path}"
        response = self._http.post(path, json=_to_json(element))
        if response.status_code not in (200, 201, 204):
            raise BasyxError(response, f"POST element {submodel_id} {parent_path or ''}")

    # --- concept descriptions -------------------------------------------------

    def list_concept_description_ids(self) -> list[str]:
        return [str(c["id"]) for c in self._paged("/concept-descriptions")]

    def concept_descriptions_json(self) -> dict[str, dict[str, Any]]:
        """Every concept description, by id. One paged listing rather than a GET per channel."""
        return {str(c["id"]): c for c in self._paged("/concept-descriptions")}

    def put_concept_description(self, concept: model.ConceptDescription) -> None:
        payload = _to_json(concept)
        response = self._http.put(f"/concept-descriptions/{encode_id(concept.id)}", json=payload)
        if response.status_code == 404:
            response = self._http.post("/concept-descriptions", json=payload)
        if response.status_code not in (200, 201, 204):
            raise BasyxError(response, f"PUT concept description {concept.id}")

    # --- attachments ----------------------------------------------------------

    def upload_attachment(
        self,
        submodel_id: str,
        id_short_path: str,
        file_name: str,
        content: bytes,
        content_type: str,
    ) -> None:
        response = self._http.put(
            f"/submodels/{encode_id(submodel_id)}/submodel-elements/{encode_path(id_short_path)}/attachment",
            data={"fileName": file_name},
            files={"file": (file_name, content, content_type)},
        )
        if response.status_code not in (200, 201, 204):
            raise BasyxError(response, f"PUT attachment {submodel_id} {id_short_path}")

    def download_attachment(self, submodel_id: str, id_short_path: str) -> bytes:
        response = self._http.get(
            f"/submodels/{encode_id(submodel_id)}/submodel-elements/{encode_path(id_short_path)}/attachment"
        )
        if response.status_code != 200:
            raise BasyxError(response, f"GET attachment {submodel_id} {id_short_path}")
        return response.content

    # --- operations -----------------------------------------------------------

    def invoke(
        self,
        submodel_id: str,
        id_short_path: str,
        inputs: Iterable[model.SubmodelElement],
        *,
        timeout_ms: int = 120_000,
    ) -> OperationResult:
        """Invoke an Operation synchronously (``…/invoke``)."""
        request = {
            "inputArguments": [{"value": _to_json(e)} for e in inputs],
            "inoutputArguments": [],
            "clientTimeoutDuration": f"PT{timeout_ms / 1000:.0f}S",
        }
        response = self._http.post(
            f"/submodels/{encode_id(submodel_id)}/submodel-elements/{encode_path(id_short_path)}/invoke",
            json=request,
            timeout=timeout_ms / 1000 + 10,
        )
        if response.status_code != 200:
            raise BasyxError(response, f"POST invoke {submodel_id} {id_short_path}")
        body: dict[str, Any] = response.json()
        outputs: dict[str, Any] = {}
        for argument in body.get("outputArguments", []):
            value = argument.get("value", {})
            outputs[str(value.get("idShort"))] = value.get("value")
        success = bool(body.get("success", True))
        return OperationResult(success=success, outputs=outputs, raw=body)

    # --- packages -------------------------------------------------------------

    def upload_aasx(self, path: Path) -> None:
        """BaSyx-specific: ``POST /upload`` of a complete AASX package."""
        with path.open("rb") as handle:
            response = self._http.post(
                "/upload",
                files={
                    "file": (path.name, handle, "application/asset-administration-shell-package")
                },
                timeout=600.0,
            )
        if response.status_code not in (200, 201, 204):
            raise BasyxError(response, f"POST /upload {path.name}")
