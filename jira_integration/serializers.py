from .models import JiraFieldDef


def serialize_card(issue):
    assignee = None
    if issue.assignee is not None:
        assignee = {
            "display_name": issue.assignee.display_name,
            "avatar_url": issue.assignee.avatar_url,
        }

    return {
        "key": issue.issue_key,
        "summary": issue.summary,
        "status": issue.status.name,
        "issue_type": issue.issue_type,
        "priority": issue.priority,
        "assignee": assignee,
    }


def serialize_sprint(sprint):
    if sprint is None:
        return None

    return {
        "jira_id": sprint.jira_id,
        "name": sprint.name,
        "state": sprint.state,
        "start_date": sprint.start_date,
        "end_date": sprint.end_date,
    }


def serialize_issue(issue):
    data = serialize_card(issue)

    if issue.assignee is not None:
        data["assignee"].update({
            "account_id": issue.assignee.account_id,
            "email": issue.assignee.email,
        })

    display_fields = JiraFieldDef.objects.filter(
        is_enabled=True,
        purpose=JiraFieldDef.Purpose.DISPLAY,
    ).values_list("jira_field_id", flat=True)

    data.update({
        "jira_id": issue.jira_id,
        "project_key": issue.project.project_key,
        "status": {
            "jira_id": issue.status.jira_id,
            "name": issue.status.name,
            "category": issue.status.category,
        },
        "updated_at": issue.updated_jira,
        "rank": issue.rank,
        "sprint": serialize_sprint(issue.sprint),
        "labels": issue.labels,
        "description_html": None,
        "custom_fields": {
            field_id: issue.custom_fields[field_id]
            for field_id in display_fields
            if field_id in issue.custom_fields
        },
        "comments": [],
        "links": [
            {
                "link_type": link.link_type,
                "direction": link.direction,
                "target_key": link.to_key,
            }
            for link in issue.visible_links
        ],
        "synced_at": issue.synced_at,
    })
    return data