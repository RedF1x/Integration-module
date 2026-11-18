from dataclasses import dataclass

from jira_integration.normalizer.catalog import identifier, text


@dataclass(frozen=True)
class Field:
    jira_id: str
    purpose: str
    value_type: str


@dataclass(frozen=True)
class Rule:
    source: str
    expected: object
    field_id: str | None = None


@dataclass(frozen=True)
class Decision:
    jira_id: str
    owner_ref: str | None
    allowed: bool


@dataclass(frozen=True)
class Policy:
    enabled: bool
    fields: tuple[Field, ...] = ()
    rules: tuple[Rule, ...] = ()

    @property
    def field_ids(self):
        return tuple(f.jira_id for f in self.fields)

    def evaluate(self, raw):
        identity = identifier(raw["id"])
        fields = raw["fields"]
        if text(fields["project"]["key"]) != "SCRUM":
            return Decision(identity, None, False)
        if not self.enabled:
            return Decision(identity, None, False)
        labels = fields["labels"]
        if not isinstance(labels, list) or not all(isinstance(v, str) for v in labels):
            raise ValueError("Некорректные метки")
        allowed = False
        definitions = {f.jira_id: f for f in self.fields}
        for rule in self.rules:
            if rule.source == "label":
                allowed |= isinstance(rule.expected, str) and rule.expected in labels
            elif rule.source == "custom_field":
                definition = definitions.get(rule.field_id)
                if definition is None or definition.purpose != "policy_flag":
                    continue
                value = fields[rule.field_id]  # отсутствие != явное null
                if rule.expected is not None:
                    allowed |= (
                        type(value) is type(rule.expected) and value == rule.expected
                    )
        if not allowed:
            return Decision(identity, None, False)
        assignee = fields["assignee"]
        owner = None if assignee is None else text(assignee["accountId"])
        return Decision(identity, owner, bool(allowed and owner))

    def public_labels(self, labels):
        service_labels = {
            r.expected
            for r in self.rules
            if r.source == "label" and isinstance(r.expected, str)
        }
        return [
            label
            for label in labels
            if label not in service_labels and not label.startswith("intern:")
        ]

    def display_fields(self, raw_fields):
        result = {}
        supported = {"string": str, "number": (int, float), "boolean": bool}
        for field in self.fields:
            if field.purpose != "display":
                continue
            expected = supported.get(field.value_type)
            if expected is None:
                raise ValueError("Тип display-поля пока не поддерживается")
            value = raw_fields[field.jira_id]
            if value is not None:
                if not isinstance(value, expected) or (
                    field.value_type == "number" and isinstance(value, bool)
                ):
                    raise ValueError("Неверный тип display-поля")
                result[field.jira_id] = value
        return result
