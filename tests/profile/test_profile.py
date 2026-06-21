def test_update_profile_can_disable_oncall_shift_email_notifications(client, auth_headers):
    response = client.put(
        "/api/profile",
        json={
            "notify_oncall_shift_start_email": False,
            "notify_oncall_shift_end_email": False,
        },
        headers=auth_headers,
    )

    assert response.status_code == 200
    data = response.get_json()
    assert data["notify_oncall_shift_start_email"] is False
    assert data["notify_oncall_shift_end_email"] is False
