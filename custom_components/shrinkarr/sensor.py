"""Sensors: savings, queue, the running conversion, kept originals and the GPU."""
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone

from homeassistant.components.sensor import (
    SensorDeviceClass, SensorEntity, SensorEntityDescription, SensorStateClass,
)
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfInformation, UnitOfTemperature, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import ShrinkarrConfigEntry
from .entity import ShrinkarrEntity

STATES = ["running", "paused", "waiting", "waiting_auto", "idle", "setup"]


def _ts(value) -> datetime | None:
    return datetime.fromtimestamp(value, timezone.utc) if value else None


def _current(d: dict, key: str):
    cur = d["queue"].get("current")
    return cur.get(key) if cur else None


@dataclass(frozen=True, kw_only=True)
class ShrinkarrSensorDescription(SensorEntityDescription):
    value_fn: Callable[[dict], object]
    attrs_fn: Callable[[dict], dict] | None = None


def _size(key: str, value_fn, **kw) -> ShrinkarrSensorDescription:
    return ShrinkarrSensorDescription(
        key=key, value_fn=value_fn, device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.BYTES, suggested_unit_of_measurement=UnitOfInformation.GIGABYTES,
        suggested_display_precision=1, state_class=SensorStateClass.MEASUREMENT, **kw)


def _duration(key: str, value_fn, **kw) -> ShrinkarrSensorDescription:
    return ShrinkarrSensorDescription(
        key=key, value_fn=value_fn, device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS, suggested_unit_of_measurement=UnitOfTime.HOURS,
        suggested_display_precision=1, **kw)


SENSORS: tuple[ShrinkarrSensorDescription, ...] = (
    _size("to_save", lambda d: d["library"]["toSave"]),
    _size("saved", lambda d: d["library"]["saved"]),
    _size("library_size", lambda d: d["library"]["size"],
          attrs_fn=lambda d: {"movies": d["library"].get("movies"), "series": d["library"].get("series")}),
    ShrinkarrSensorDescription(key="savings", value_fn=lambda d: d["library"]["pct"],
                               native_unit_of_measurement=PERCENTAGE, state_class=SensorStateClass.MEASUREMENT),
    ShrinkarrSensorDescription(key="titles_todo", value_fn=lambda d: d["library"]["titlesTodo"],
                               state_class=SensorStateClass.MEASUREMENT),
    _duration("encode_time", lambda d: round(d["library"]["encodeSeconds"])),
    ShrinkarrSensorDescription(key="status", value_fn=lambda d: d["queue"]["state"] if d["queue"]["state"] in STATES else None,
                               device_class=SensorDeviceClass.ENUM, options=STATES,
                               attrs_fn=lambda d: {"paused": d["queue"]["paused"]}),
    ShrinkarrSensorDescription(key="queue", value_fn=lambda d: d["queue"]["queued"], state_class=SensorStateClass.MEASUREMENT),
    _duration("queue_time", lambda d: round(d["queue"]["queuedSeconds"] + (_current(d, "eta") or 0))),
    ShrinkarrSensorDescription(
        key="progress", value_fn=lambda d: round(_current(d, "progress") * 100, 1) if d["queue"].get("current") else None,
        native_unit_of_measurement=PERCENTAGE, suggested_display_precision=0,
        attrs_fn=lambda d: {"title": _current(d, "title"), "episode": _current(d, "subtitle"), "stage": _current(d, "stage"),
                            "seconds_left": round(_current(d, "eta")) if _current(d, "eta") is not None else None,
                            "fps": _current(d, "fps"), "speed": _current(d, "speed")}),
    ShrinkarrSensorDescription(key="done", value_fn=lambda d: d["queue"]["done"], state_class=SensorStateClass.TOTAL),
    _size("kept", lambda d: d["kept"]["bytes"], attrs_fn=lambda d: {"count": d["kept"]["count"], "days": d["kept"]["days"]}),
    ShrinkarrSensorDescription(key="kept_next_delete", value_fn=lambda d: _ts(d["kept"]["nextDelete"]),
                               device_class=SensorDeviceClass.TIMESTAMP),
    ShrinkarrSensorDescription(key="gpu_busy", value_fn=lambda d: d["gpu"]["busy"], native_unit_of_measurement=PERCENTAGE,
                               state_class=SensorStateClass.MEASUREMENT, suggested_display_precision=0,
                               attrs_fn=lambda d: {"name": d["gpu"]["name"], "encoder": d["gpu"]["encoder"],
                                                   **{f"engine_{k}": v for k, v in (d["gpu"]["engines"] or {}).items()}}),
    ShrinkarrSensorDescription(key="gpu_temperature", value_fn=lambda d: d["gpu"]["temp"],
                               device_class=SensorDeviceClass.TEMPERATURE, native_unit_of_measurement=UnitOfTemperature.CELSIUS,
                               state_class=SensorStateClass.MEASUREMENT, suggested_display_precision=0,
                               entity_category=EntityCategory.DIAGNOSTIC),
    ShrinkarrSensorDescription(key="cpu", value_fn=lambda d: d["gpu"]["cpu"], native_unit_of_measurement=PERCENTAGE,
                               state_class=SensorStateClass.MEASUREMENT, suggested_display_precision=0,
                               entity_category=EntityCategory.DIAGNOSTIC),
)


async def async_setup_entry(hass: HomeAssistant, entry: ShrinkarrConfigEntry,
                            async_add_entities: AddConfigEntryEntitiesCallback) -> None:
    async_add_entities(ShrinkarrSensor(entry.runtime_data, d) for d in SENSORS)


class ShrinkarrSensor(ShrinkarrEntity, SensorEntity):
    entity_description: ShrinkarrSensorDescription

    def __init__(self, coordinator, description: ShrinkarrSensorDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self):
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict | None:
        fn = self.entity_description.attrs_fn
        return fn(self.coordinator.data) if fn else None
