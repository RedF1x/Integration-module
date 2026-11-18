from datetime import UTC, datetime
from urllib.parse import urlsplit

import nh3

from jira_integration.dto import CommentDTO, IssueDTO, LinkDTO, UserDTO, parse_iso

from .catalog import identifier, status_dto, text


def safe_url(value):
    if not isinstance(value, str):
        return None
    parsed = urlsplit(value)
    return (
        value
        if (
            parsed.scheme == "https"
            and parsed.netloc
            and not parsed.username
            and not parsed.password
        )
        else None
    )


def clean_html(value):
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("HTML должен быть строкой")
    return nh3.clean(
        value,
        tags={
            "p",
            "br",
            "strong",
            "b",
            "em",
            "i",
            "ul",
            "ol",
            "li",
            "pre",
            "code",
            "blockquote",
            "a",
        },
        attributes={"a": {"href", "title"}},
        url_schemes={"https", "http"},
        clean_content_tags={"script", "style", "iframe", "object"},
        attribute_filter=lambda tag, attr, value: (
            value
            if attr != "href" or urlsplit(value).scheme in {"https", "http"}
            else None
        ),
    )


def user_dto(raw):
    if raw is None:
        return None
    # Email не требуется для assignee-владения и не переносится из Jira.
    return UserDTO(
        text(raw["accountId"]),
        text(raw["displayName"]),
        None,
        safe_url(raw.get("avatarUrls", {}).get("48x48")),
    )


def select_sprint(values, catalog):
    if values is None:
        return None
    if not isinstance(values, list):
        raise ValueError("Sprint должен быть списком")
    candidates = []
    for value in values:
        # Справочник обновляется и при отсутствии updated у задачи.
        sprint = catalog.sprints[identifier(value["id"])]
        if sprint.state in {"active", "future"}:
            candidates.append(sprint)
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda s: (
            s.state != "active",
            s.start_date is None,
            parse_iso(s.start_date)
            if s.start_date
            else datetime.max.replace(tzinfo=UTC),
            s.jira_id,
        ),
    )


def normalize(raw, catalog, policy, config, comments=()):
    fields = raw["fields"]
    priority = fields["priority"]
    parsed_comments = []
    if config.comments:
        for comment in comments:
            if "visibility" in comment or comment.get("jsdPublic") is False:
                continue
            author = user_dto(comment["author"])
            if author is None:
                raise ValueError("Нет автора комментария")
            created = text(comment["created"])
            parse_iso(created)
            parsed_comments.append(
                CommentDTO(
                    identifier(comment["id"]),
                    author,
                    clean_html(comment["renderedBody"]) or "",
                    created,
                )
            )
    links = []
    for link in fields["issuelinks"]:
        for direction in ("inward", "outward"):
            target = link.get(direction + "Issue")
            if target is not None:
                links.append(
                    LinkDTO(text(link["type"]["name"]), direction, text(target["key"]))
                )
    description = None
    if config.descriptions:
        description = clean_html(raw["renderedFields"]["description"])
    return IssueDTO(
        jira_id=identifier(raw["id"]),
        key=text(raw["key"]),
        project_key=text(fields["project"]["key"]),
        summary=text(fields["summary"]),
        issue_type=text(fields["issuetype"]["name"]),
        status=status_dto(fields["status"]),
        updated_at=text(fields["updated"]),
        priority=text(priority["name"]) if priority else None,
        rank=fields[catalog.rank_field],
        assignee=user_dto(fields["assignee"]),
        sprint=select_sprint(fields[catalog.sprint_field], catalog),
        labels=policy.public_labels(fields["labels"]),
        description_html=description,
        custom_fields=policy.display_fields(fields),
        comments=parsed_comments,
        links=links,
    )
