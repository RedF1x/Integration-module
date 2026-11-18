from dataclasses import dataclass

from jira_integration.dto import ProjectDTO, SprintDTO, StatusDTO
from jira_integration.sources.base import SourceError

CATEGORIES = {"new": "todo", "indeterminate": "in_progress", "done": "done"}


def text(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Ожидалась непустая строка")
    return value


def identifier(value):
    if isinstance(value, str):
        return text(value)
    if type(value) is int and value > 0:
        return str(value)
    raise ValueError("Неверный ID")


def sprint_dto(raw):
    return SprintDTO(
        identifier(raw["id"]),
        text(raw["name"]),
        raw["state"],
        raw.get("startDate"),
        raw.get("endDate"),
    )


def status_dto(raw):
    return StatusDTO(
        identifier(raw["id"]),
        text(raw["name"]),
        CATEGORIES[raw["statusCategory"]["key"]],
    )


@dataclass(frozen=True)
class Catalog:
    project: ProjectDTO
    sprints: dict
    statuses: dict
    positions: dict
    priorities: dict
    sprint_field: str
    rank_field: str


def build_catalog(
    project,
    fields,
    board,
    sprints,
    statuses,
    priorities,
    priority_ids=("1", "2", "3", "4", "5"),
):
    try:
        if project["key"] != "SCRUM" or board["id"] != 1:
            raise ValueError("Чужая область")
        sprint_fields = [
            f["id"]
            for f in fields
            if f.get("schema", {}).get("custom")
            == "com.pyxis.greenhopper.jira:gh-sprint"
        ]
        if len(sprint_fields) != 1:
            raise ValueError("Неоднозначное поле Sprint")
        rank = "customfield_" + str(board["ranking"]["rankCustomFieldId"])
        if rank not in {f["id"] for f in fields}:
            raise ValueError("Не найден Rank")
        parsed_sprints = {identifier(s["id"]): sprint_dto(s) for s in sprints}
        if sum(s.state == "active" for s in parsed_sprints.values()) > 1:
            raise ValueError("MVP поддерживает один активный спринт")
        parsed_statuses = {
            identifier(s["id"]): status_dto(s)
            for group in statuses
            for s in group["statuses"]
        }
        positions = {}
        for column in board["columnConfig"]["columns"]:
            for status in column["statuses"]:
                positions[identifier(status["id"])] = len(positions)
        return Catalog(
            ProjectDTO(identifier(project["id"]), "SCRUM", text(project["name"])),
            parsed_sprints,
            parsed_statuses,
            positions,
            {
                identity: i
                for i, identity in enumerate(priority_ids)
                if identity in {identifier(p["id"]) for p in priorities}
            },
            sprint_fields[0],
            rank,
        )
    except (KeyError, TypeError, ValueError):
        raise SourceError(
            "Jira: неверные справочники или неподдерживаемая область"
        ) from None
