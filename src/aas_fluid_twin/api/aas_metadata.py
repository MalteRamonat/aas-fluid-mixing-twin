"""Everything the dashboard shows *about* a channel or a parameter comes from the AAS.

The store knows values; it does not know that `Tank_B204_Volume` is called "Volume of the
mixing tank B204", that it is in millilitres, that its sensor spans 0…8000 ml, or that
`Pressure_below_B201` is flagged unreliable. That knowledge lives in the submodels, and this
module is the only place that reads it — so the dashboard cannot quietly fall back on the
local signal dictionary and pretend the AAS is load-bearing when it is not.

Two joins do the work:

* ``AssetInterfacesDescription`` has one ``PropertyAffordance`` per channel (key, type,
  UN/CEFACT unit code, instrument span, OPC UA node, data-quality qualifiers) and a
  ``valueSemantics`` reference to that channel's ConceptDescription;
* the ConceptDescription carries the IEC 61360 data specification — preferred name, unit
  symbol, data type, definition.

``SimulationControl`` supplies the parameter set, the actuator schedules and the operation's
input defaults in the same way.

Results are cached: the plant's metadata changes when the AAS is rebuilt, not between
requests. ``refresh()`` drops the cache.
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field
from typing import Any

from aas_fluid_twin.aas.builders.asset_interfaces import INTERFACE_ID_SHORT
from aas_fluid_twin.aas.builders.asset_interfaces import SUBMODEL_ID as AID_SUBMODEL_ID
from aas_fluid_twin.aas.builders.simulation_control import SUBMODEL_ID as CONTROL_SUBMODEL_ID
from aas_fluid_twin.aas.builders.simulation_models import (
    SUBMODEL_ID as SIMULATION_MODELS_SUBMODEL_ID,
)
from aas_fluid_twin.aas.builders.time_series import (
    PLANT_TIMESERIES_ID,
    SIMULATION_TIMESERIES_ID,
)
from aas_fluid_twin.client import BasyxClient, BasyxError

__all__ = [
    "AasMetadata",
    "AasUnavailableError",
    "ChannelInfo",
    "ModelVersionInfo",
    "ParameterInfo",
    "ScheduleInfo",
    "SimulationConfig",
    "SubmodelLinks",
    "default_metadata",
]


class AasUnavailableError(RuntimeError):
    """The AAS repository could not be read. The dashboard says so rather than inventing data."""


@dataclass(frozen=True, slots=True)
class ChannelInfo:
    channel: str
    """CSV column name — the join key to the store."""
    title: str
    unit: str | None
    data_type: str
    """``number`` or ``boolean``, as the interface describes it."""
    role: str
    """``sensor`` or ``actuator``."""
    quality: str
    quality_reason: str | None
    minimum: float | None
    maximum: float | None
    node_id: str | None
    semantic_id: str | None
    definition: str | None


@dataclass(frozen=True, slots=True)
class ParameterInfo:
    id_short: str
    name: str
    """The Modelica parameter the simulation runner sets."""
    default: float | bool | None
    unit: str | None
    minimum: float | None
    maximum: float | None
    fault_role: str | None
    description: str | None


@dataclass(frozen=True, slots=True)
class ScheduleInfo:
    id_short: str
    name: str
    row_count: int | None
    column_order: str | None
    description: str | None


@dataclass(frozen=True, slots=True)
class ModelVersionInfo:
    id_short: str
    version_id: str
    file: str | None
    notes: str | None


@dataclass(frozen=True, slots=True)
class SimulationConfig:
    parameters: tuple[ParameterInfo, ...]
    schedules: tuple[ScheduleInfo, ...]
    model_versions: tuple[ModelVersionInfo, ...]
    operation_defaults: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SubmodelLinks:
    """Where a dashboard reader can see the same thing in the AAS itself."""

    repository: str
    web_ui: str | None
    submodels: dict[str, str]


#: UN/CEFACT common code -> the symbol the plant uses. The interface publishes codes, the
#: dashboard shows symbols; this is the same table the AID builder encodes with, inverted.
_UNIT_SYMBOLS: dict[str, str] = {
    "MLT": "ml",
    "2Q": "l/min",
    "KPA": "kPa",
    "CEL": "°C",
    "CMT": "cm",
    "MTR": "m",
}


def _children(element: dict[str, Any]) -> dict[str, dict[str, Any]]:
    value = element.get("value")
    if not isinstance(value, list):
        return {}
    return {str(c.get("idShort")): c for c in value if isinstance(c, dict) and c.get("idShort")}


def _text(element: dict[str, Any] | None) -> str | None:
    if element is None:
        return None
    value = element.get("value")
    if isinstance(value, list):  # MultiLanguageProperty
        for entry in value:
            if isinstance(entry, dict) and entry.get("text"):
                return str(entry["text"])
        return None
    return None if value is None else str(value)


def _number(element: dict[str, Any] | None) -> float | None:
    raw = _text(element)
    if raw in (None, ""):
        return None
    try:
        return float(str(raw))
    except ValueError:
        return None


def _description(element: dict[str, Any]) -> str | None:
    for entry in element.get("description") or []:
        if isinstance(entry, dict) and entry.get("text"):
            return str(entry["text"])
    return None


def _first_key(reference: dict[str, Any] | None) -> str | None:
    if not isinstance(reference, dict):
        return None
    keys = reference.get("keys") or []
    return str(keys[0]["value"]) if keys and isinstance(keys[0], dict) else None


def _qualifier(element: dict[str, Any], type_: str) -> str | None:
    for q in element.get("qualifiers") or []:
        if isinstance(q, dict) and q.get("type") == type_:
            return None if q.get("value") is None else str(q["value"])
    return None


def _range(element: dict[str, Any] | None) -> tuple[float | None, float | None]:
    if element is None:
        return (None, None)

    def _as_float(raw: Any) -> float | None:
        try:
            return None if raw in (None, "") else float(str(raw))
        except ValueError:
            return None

    return (_as_float(element.get("min")), _as_float(element.get("max")))


def _iec61360(concept: dict[str, Any] | None) -> dict[str, Any]:
    if concept is None:
        return {}
    for spec in concept.get("embeddedDataSpecifications") or []:
        content = spec.get("dataSpecificationContent") if isinstance(spec, dict) else None
        if isinstance(content, dict):
            return content
    return {}


def _language_text(entries: Any) -> str | None:
    if isinstance(entries, list):
        for entry in entries:
            if isinstance(entry, dict) and entry.get("text"):
                return str(entry["text"])
    return None


class AasMetadata:
    """Reads the twin's metadata from a BaSyx repository, once, and hands out views of it."""

    def __init__(self, base_url: str, web_ui_url: str | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.web_ui_url = web_ui_url
        self._lock = threading.Lock()
        self._channels: tuple[ChannelInfo, ...] | None = None
        self._simulation: SimulationConfig | None = None

    # -- plumbing --

    def _read(self, submodel_id: str) -> dict[str, Any]:
        try:
            with BasyxClient(self.base_url) as client:
                return client.get_submodel_json(submodel_id)
        except BasyxError as error:
            raise AasUnavailableError(f"{self.base_url}: {error}") from error
        except Exception as error:  # httpx connect/timeout errors
            raise AasUnavailableError(f"{self.base_url} is unreachable: {error}") from error

    def refresh(self) -> None:
        with self._lock:
            self._channels = None
            self._simulation = None

    def links(self) -> SubmodelLinks:
        return SubmodelLinks(
            repository=self.base_url,
            web_ui=self.web_ui_url,
            submodels={
                "plant_time_series": PLANT_TIMESERIES_ID,
                "simulation_time_series": SIMULATION_TIMESERIES_ID,
                "simulation_control": CONTROL_SUBMODEL_ID,
                "simulation_models": SIMULATION_MODELS_SUBMODEL_ID,
                "asset_interfaces": AID_SUBMODEL_ID,
            },
        )

    # -- channels --

    def channels(self) -> tuple[ChannelInfo, ...]:
        with self._lock:
            if self._channels is not None:
                return self._channels
        interface = self._read(AID_SUBMODEL_ID)
        try:
            with BasyxClient(self.base_url) as client:
                concepts = client.concept_descriptions_json()
        except Exception as error:
            raise AasUnavailableError(f"{self.base_url}: concept descriptions: {error}") from error
        channels = tuple(_parse_channels(interface, concepts))
        with self._lock:
            self._channels = channels
        return channels

    # -- simulation --

    def simulation(self) -> SimulationConfig:
        with self._lock:
            if self._simulation is not None:
                return self._simulation
        control = self._read(CONTROL_SUBMODEL_ID)
        models = self._read(SIMULATION_MODELS_SUBMODEL_ID)
        config = _parse_simulation(control, models)
        with self._lock:
            self._simulation = config
        return config


def _quality_reason(description: str) -> str | None:
    """The AID writes the reason into the property's description as "Quality <x>: <why>"."""
    marker = description.find("Quality ")
    if marker < 0:
        return None
    colon = description.find(":", marker)
    return description[colon + 1 :].strip() or None if colon >= 0 else None


def _parse_channels(
    interface: dict[str, Any], concepts: dict[str, dict[str, Any]]
) -> list[ChannelInfo]:
    """AID ``PropertyAffordance`` + its ConceptDescription -> one :class:`ChannelInfo`."""
    top = _children({"value": interface.get("submodelElements", [])})
    interface_element = top.get(INTERFACE_ID_SHORT)
    if interface_element is None:
        raise AasUnavailableError(
            f"the asset interface submodel has no {INTERFACE_ID_SHORT!r} interface"
        )
    metadata = _children(interface_element).get("InteractionMetadata")
    properties = _children(metadata or {}).get("properties")
    out: list[ChannelInfo] = []
    for name, element in _children(properties or {}).items():
        fields = _children(element)
        semantic_id = _first_key(fields.get("valueSemantics", {}).get("value"))
        concept = concepts.get(semantic_id or "")
        spec = _iec61360(concept)
        minimum, maximum = _range(fields.get("min_max"))
        description = _description(element) or ""
        node = _children(fields.get("forms", {})).get("href")
        unit_code = _text(fields.get("unit"))
        out.append(
            ChannelInfo(
                channel=_text(fields.get("key")) or name,
                title=_language_text(spec.get("preferredName"))
                or _text(fields.get("title"))
                or name,
                unit=spec.get("unit") or _UNIT_SYMBOLS.get(unit_code or ""),
                data_type=_text(fields.get("type")) or "number",
                role="actuator" if description.startswith("Actuator") else "sensor",
                quality=_qualifier(element, "DataQuality") or "good",
                quality_reason=_quality_reason(description),
                minimum=minimum,
                maximum=maximum,
                node_id=_text(node),
                semantic_id=semantic_id,
                definition=_language_text(spec.get("definition")) or description or None,
            )
        )
    out.sort(key=lambda c: c.channel)
    return out


def _parse_simulation(control: dict[str, Any], models: dict[str, Any]) -> SimulationConfig:
    top = _children({"value": control.get("submodelElements", [])})

    parameters: list[ParameterInfo] = []
    for id_short, element in _children(top.get("ParameterSet", {})).items():
        fields = _children(element)
        minimum, maximum = _range(fields.get("ValueRange"))
        raw_default = _text(fields.get("DefaultValue"))
        default: float | bool | None
        if raw_default in (None, ""):
            default = None
        elif str(raw_default).lower() in ("true", "false"):
            default = str(raw_default).lower() == "true"
        else:
            try:
                default = float(str(raw_default))
            except ValueError:
                default = None
        parameters.append(
            ParameterInfo(
                id_short=id_short,
                name=_text(fields.get("ParameterName")) or id_short,
                default=default,
                unit=_text(fields.get("Unit")),
                minimum=minimum,
                maximum=maximum,
                fault_role=_text(fields.get("FaultRole")),
                description=_description(element),
            )
        )

    schedules = [
        ScheduleInfo(
            id_short=id_short,
            name=_text(_children(element).get("Name")) or id_short,
            row_count=int(_number(_children(element).get("RowCount")) or 0) or None,
            column_order=_text(_children(element).get("ColumnOrder")),
            description=_description(element),
        )
        for id_short, element in _children(top.get("ActuatorSchedules", {})).items()
    ]

    defaults: dict[str, str] = {}
    run_operation = top.get("RunSimulation")
    if run_operation is not None:
        for variable in run_operation.get("inputVariables") or []:
            declaration = variable.get("value") if isinstance(variable, dict) else None
            if isinstance(declaration, dict) and declaration.get("idShort"):
                defaults[str(declaration["idShort"])] = str(declaration.get("value") or "")

    versions: list[ModelVersionInfo] = []
    model_top = _children({"value": models.get("submodelElements", [])})
    model_file = _children(_children(model_top.get("SimulationModel", {})).get("ModelFile", {}))
    for id_short, element in model_file.items():
        fields = _children(element)
        if "ModelVersionId" not in fields:  # ModelFileType and friends are not versions
            continue
        versions.append(
            ModelVersionInfo(
                id_short=id_short,
                version_id=_text(fields.get("ModelVersionId")) or id_short,
                file=_text(fields.get("DigitalFile")),
                notes=_text(fields.get("ModelFileReleaseNotesTxt")),
            )
        )

    return SimulationConfig(
        parameters=tuple(parameters),
        schedules=tuple(schedules),
        model_versions=tuple(versions),
        operation_defaults=defaults,
    )


def default_metadata() -> AasMetadata:
    """From the environment: ``AAS_BASYX_URL`` and ``AAS_WEB_UI_URL``."""
    return AasMetadata(
        os.environ.get("AAS_BASYX_URL", "http://localhost:8081"),
        os.environ.get("AAS_WEB_UI_URL", "http://localhost:3000"),
    )
