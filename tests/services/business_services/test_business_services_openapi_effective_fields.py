from app.api.openapi.spec import build_openapi_spec


def test_business_service_component_openapi_documents_effective_impact_fields():
    spec = build_openapi_spec()
    schema = spec["paths"]["/api/business-services/{business_service_id}/components"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    properties = schema["items"]["properties"]

    assert "service_status" in properties
    assert "effective_status" in properties
    assert "effective_status_reason" in properties
    assert "alert_impact_status" in properties
    assert "dependency_impact_status" in properties
    assert "open_alert_groups" in properties
    assert "critical_open_alert_groups" in properties
    assert "upstream_issues_count" in properties

    assert properties["service_status"]["description"].startswith("Raw persisted")
    assert properties["effective_status"]["description"].startswith("Calculated Service Impact")


def test_business_service_manual_status_openapi_paths_are_registered():
    spec = build_openapi_spec()

    path = spec["paths"]["/api/business-services/{business_service_id}/manual-status"]

    assert "post" in path
    assert "delete" in path

    post = path["post"]
    delete = path["delete"]

    assert post["requestBody"]["content"]["application/json"]["schema"]["required"] == ["status"]
    assert post["responses"]["200"]["content"]["application/json"]["schema"]["properties"]["manual_status"]
    assert delete["responses"]["200"]["content"]["application/json"]["schema"]["properties"]["manual_status_active"]
