"""Turn the config model into an editable HTML form and back.

The configuration page must cover every setting, and the set of settings grows
over time, so the form is derived from the pydantic model rather than hand-written
field by field. :func:`field_specs` walks the model once to describe each field
(its dotted name, input kind, label, help text, and any enum choices);
:func:`flatten` reads a config into the values those fields display; and
:func:`parse` rebuilds a nested dict from submitted form data, ready for
``Config.model_validate``. Adding a setting to the model adds it to the form for
free.
"""

from __future__ import annotations

import enum
import typing
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

from subtitle_tool.config.models import Config


@dataclass(frozen=True)
class FieldSpec:
    """How one config field is rendered and parsed."""

    name: str  # dotted path, e.g. "language.filter.enabled"
    kind: str  # bool | integer | number | text | list | enum
    label: str
    help: str
    choices: list[str] = field(default_factory=list)

    @property
    def section(self) -> str:
        """The top-level config section this field belongs to."""
        return self.name.split(".", 1)[0]


def field_specs(model_cls: type[BaseModel] = Config) -> list[FieldSpec]:
    """Describe every field of ``model_cls``, recursing into nested models."""
    specs: list[FieldSpec] = []
    _walk(model_cls, "", specs)
    return specs


def _walk(model_cls: type[BaseModel], prefix: str, specs: list[FieldSpec]) -> None:
    for name, info in model_cls.model_fields.items():
        annotation = info.annotation
        dotted = f"{prefix}{name}"
        label = name.replace("_", " ")
        help_text = info.description or ""
        if isinstance(annotation, type) and issubclass(annotation, BaseModel):
            _walk(annotation, f"{dotted}.", specs)
        elif isinstance(annotation, type) and issubclass(annotation, enum.Enum):
            choices = [member.value for member in annotation]
            specs.append(FieldSpec(dotted, "enum", label, help_text, choices))
        elif annotation is bool:
            specs.append(FieldSpec(dotted, "bool", label, help_text))
        elif annotation is int:
            specs.append(FieldSpec(dotted, "integer", label, help_text))
        elif annotation is float:
            specs.append(FieldSpec(dotted, "number", label, help_text))
        elif typing.get_origin(annotation) is list:
            specs.append(FieldSpec(dotted, "list", label, help_text))
        else:
            specs.append(FieldSpec(dotted, "text", label, help_text))


def flatten(config: Config) -> dict[str, Any]:
    """Flatten a config into ``{dotted_name: value}`` for form display."""
    flat: dict[str, Any] = {}
    _flatten(config.model_dump(mode="json"), "", flat)
    return flat


def flatten_partial(nested: Mapping[str, Any]) -> dict[str, Any]:
    """Flatten an already-nested dict (e.g. parsed form data) for redisplay.

    Used to repopulate the form with the user's own input after a failed save,
    including any value that did not validate.
    """
    flat: dict[str, Any] = {}
    _flatten(nested, "", flat)
    return flat


def _flatten(data: Mapping[str, Any], prefix: str, out: dict[str, Any]) -> None:
    for key, value in data.items():
        dotted = f"{prefix}{key}"
        if isinstance(value, dict):
            _flatten(value, f"{dotted}.", out)
        else:
            out[dotted] = value


def parse(form: Mapping[str, Any], specs: list[FieldSpec]) -> dict[str, Any]:
    """Build a nested dict from submitted form data for ``Config.model_validate``.

    Checkboxes are present only when ticked, so booleans are derived from presence.
    List fields are newline-separated textareas. Numbers and enums are passed
    through as strings for pydantic to coerce and validate; an empty value is
    omitted so the model default applies.
    """
    nested: dict[str, Any] = {}
    for spec in specs:
        if spec.kind == "bool":
            _assign(nested, spec.name, spec.name in form)
            continue
        if spec.kind == "list":
            raw = str(form.get(spec.name, ""))
            value = [line.strip() for line in raw.splitlines() if line.strip()]
            _assign(nested, spec.name, value)
            continue
        raw_value = form.get(spec.name)
        if raw_value is None or raw_value == "":
            continue
        _assign(nested, spec.name, raw_value)
    return nested


def _assign(target: dict[str, Any], dotted: str, value: Any) -> None:
    parts = dotted.split(".")
    cursor = target
    for part in parts[:-1]:
        cursor = cursor.setdefault(part, {})
    cursor[parts[-1]] = value
