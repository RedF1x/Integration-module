import copy
from dataclasses import replace

import pytest

from jira_integration.normalizer.issues import clean_html, normalize
from jira_integration.policy.rules import Field, Policy, Rule


@pytest.fixture
def policy():
    return Policy(True, rules=(Rule("label", "intern-visible"),))


def test_recon_cases_are_deterministic_and_private_text_is_omitted(raw_source, policy):
    catalog = raw_source.catalog()
    values = list(raw_source.raw_issues())
    assert len(values) == 12
    decisions = {v["key"]: policy.evaluate(v) for v in values}
    assert {key for key, d in decisions.items() if not d.allowed} == {
        "SCRUM-6",
        "SCRUM-7",
        "SCRUM-12",
        "SCRUM-16",
    }
    normalized = {
        v["key"]: normalize(v, catalog, policy, raw_source.config)
        for v in values
        if decisions[v["key"]].allowed
    }
    assert normalized["SCRUM-10"].sprint.jira_id == "2"
    assert normalized["SCRUM-9"].sprint.jira_id == "3"
    assert normalized["SCRUM-8"].sprint is None
    assert normalized["SCRUM-15"].description_html is None
    for dto in normalized.values():
        assert dto.comments == [] and dto.custom_fields == {}
        assert dto.assignee.email is None
        assert "intern-visible" not in dto.labels


@pytest.mark.parametrize(
    "enabled,rules", [(False, (Rule("label", "intern-visible"),)), (True, ())]
)
def test_default_deny(raw_source, enabled, rules):
    assert (
        not Policy(enabled, rules=rules)
        .evaluate(raw_source.raw_issue_detail("SCRUM-5"))
        .allowed
    )


def test_owner_and_revocation(raw_source, policy):
    raw = raw_source.raw_issue_detail("SCRUM-5")
    assert policy.evaluate(raw).owner_ref == "test-account-1"
    raw["fields"]["assignee"]["accountId"] = "test-account-2"
    assert policy.evaluate(raw).owner_ref == "test-account-2"
    raw["fields"]["labels"].remove("intern-visible")
    assert not policy.evaluate(raw).allowed


def test_explicit_denial_does_not_require_assignee(raw_source, policy):
    raw = raw_source.raw_issue_detail("SCRUM-5")
    raw["fields"]["labels"] = []
    del raw["fields"]["assignee"]
    assert not policy.evaluate(raw).allowed


def test_move_to_other_project_revokes_access(raw_source, policy):
    raw = raw_source.raw_issue_detail("SCRUM-5")
    raw["fields"]["project"]["key"] = "OTHER"
    assert not policy.evaluate(raw).allowed


def test_missing_policy_field_is_error_not_explicit_denial(raw_source):
    policy = Policy(
        True,
        (Field("customfield_1", "policy_flag", "boolean"),),
        (Rule("custom_field", True, "customfield_1"),),
    )
    raw = raw_source.raw_issue_detail("SCRUM-5")
    with pytest.raises(KeyError):
        policy.evaluate(raw)
    raw["fields"]["customfield_1"] = 1
    assert not policy.evaluate(raw).allowed  # bool != int
    raw["fields"]["customfield_1"] = True
    assert policy.evaluate(raw).allowed
    assert policy.display_fields(raw["fields"]) == {}


def test_custom_field_whitelist_and_service_fields():
    policy = Policy(
        True,
        (
            Field("customfield_1", "display", "string"),
            Field("customfield_2", "owner", "string"),
            Field("customfield_3", "policy_flag", "boolean"),
        ),
    )
    assert policy.display_fields(
        {
            "customfield_1": "public",
            "customfield_2": "private",
            "customfield_3": True,
            "customfield_4": "secret",
        }
    ) == {
        "customfield_1": "public",
    }
    assert policy.public_labels(["intern:secret", "ordinary"]) == ["ordinary"]


def test_comments_are_complete_and_restricted_one_is_excluded(raw_source, policy):
    comments = raw_source.comments("SCRUM-11")
    assert len(comments) == 5
    config = replace(raw_source.config, comments=True)
    dto = normalize(
        raw_source.raw_issue_detail("SCRUM-11"),
        raw_source.catalog(),
        policy,
        config,
        comments,
    )
    assert len(dto.comments) == 4
    assert "10004" not in {c.jira_id for c in dto.comments}


def test_html_sanitization_and_missing_rendered_fields(raw_source, policy):
    cleaned = clean_html(
        '<script>SECRET</script><p onclick="x()">ok</p>'
        '<img src="https://tracker.test/x"><a href="javascript:x()">x</a>'
    )
    assert (
        "SECRET" not in cleaned and "onclick" not in cleaned and "<img" not in cleaned
    )
    assert "javascript" not in cleaned and "<p>ok</p>" in cleaned
    raw = raw_source.raw_issue_detail("SCRUM-14")
    dto = normalize(
        raw, raw_source.catalog(), policy, replace(raw_source.config, descriptions=True)
    )
    assert dto.description_html
    raw.pop("renderedFields")
    with pytest.raises(KeyError):
        normalize(
            raw,
            raw_source.catalog(),
            policy,
            replace(raw_source.config, descriptions=True),
        )


def test_closed_sprint_uses_fresh_catalog_even_if_issue_history_says_active(
    raw_source, policy
):
    catalog = raw_source.catalog()
    sprints = copy.copy(catalog.sprints)
    sprints["2"] = replace(sprints["2"], state="closed")
    dto = normalize(
        raw_source.raw_issue_detail("SCRUM-5"),
        replace(catalog, sprints=sprints),
        policy,
        raw_source.config,
    )
    assert dto.sprint is None
