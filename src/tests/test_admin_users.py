"""Tests for admin user management endpoints."""

import pytest
from django.contrib.auth import get_user_model

User = get_user_model()


@pytest.mark.django_db
class TestAdminUserList:
    def test_admin_can_list_users(self, admin_client, regular_user):
        response = admin_client.get("/api/v1/admin/users/")
        assert response.status_code == 200
        assert response.data["count"] >= 2  # admin + regular

    def test_user_cannot_list_users(self, user_client):
        response = user_client.get("/api/v1/admin/users/")
        assert response.status_code == 403

    def test_search_by_email(self, admin_client, regular_user):
        response = admin_client.get("/api/v1/admin/users/?search=user@test")
        assert response.status_code == 200
        assert response.data["count"] == 1
        assert response.data["results"][0]["email"] == "user@test.com"

    def test_filter_by_role(self, admin_client, regular_user):
        response = admin_client.get("/api/v1/admin/users/?role=ADMIN")
        assert response.status_code == 200
        for user in response.data["results"]:
            assert user["role"] == "ADMIN"

    def test_filter_by_school_admin_role(self, admin_client, school_admin_user):
        response = admin_client.get("/api/v1/admin/users/?role=SCHOOL_ADMIN")
        assert response.status_code == 200
        assert response.data["count"] >= 1
        for user in response.data["results"]:
            assert user["role"] == "SCHOOL_ADMIN"

    def test_filter_by_verified(self, admin_client, unverified_user):
        response = admin_client.get("/api/v1/admin/users/?is_verified=false")
        assert response.status_code == 200
        assert response.data["count"] >= 1

    def test_ordering(self, admin_client, regular_user):
        response = admin_client.get("/api/v1/admin/users/?ordering=email")
        assert response.status_code == 200
        emails = [u["email"] for u in response.data["results"]]
        assert emails == sorted(emails)


@pytest.mark.django_db
class TestAdminUserDetail:
    def test_get_user_detail(self, admin_client, regular_user):
        response = admin_client.get(f"/api/v1/admin/users/{regular_user.id}/")
        assert response.status_code == 200
        assert response.data["email"] == "user@test.com"

    def test_update_user(self, admin_client, regular_user):
        response = admin_client.patch(
            f"/api/v1/admin/users/{regular_user.id}/",
            {"is_active": False},
            format="json",
        )
        assert response.status_code == 200
        regular_user.refresh_from_db()
        assert regular_user.is_active is False

    def test_delete_user(self, admin_client, regular_user):
        uid = regular_user.id
        response = admin_client.delete(f"/api/v1/admin/users/{uid}/")
        assert response.status_code == 204
        assert not User.objects.filter(id=uid).exists()

    def test_cannot_delete_self(self, admin_client, admin_user):
        response = admin_client.delete(f"/api/v1/admin/users/{admin_user.id}/")
        assert response.status_code == 400

    def test_nonexistent_user(self, admin_client):
        import uuid

        response = admin_client.get(f"/api/v1/admin/users/{uuid.uuid4()}/")
        assert response.status_code == 404


@pytest.mark.django_db
class TestAdminSetPassword:
    def test_set_password(self, admin_client, regular_user, api_client):
        response = admin_client.post(
            f"/api/v1/admin/users/{regular_user.id}/set-password/",
            {"new_password": "adminsetpass123", "confirm_password": "adminsetpass123"},
            format="json",
        )
        assert response.status_code == 200

        # Verify new password works
        login = api_client.post(
            "/api/v1/auth/login/",
            {
                "email": "user@test.com",
                "password": "adminsetpass123",
            },
        )
        assert login.status_code == 200

    def test_user_cannot_set_password(self, user_client, admin_user):
        response = user_client.post(
            f"/api/v1/admin/users/{admin_user.id}/set-password/",
            {"new_password": "hackerpass"},
            format="json",
        )
        assert response.status_code == 403


@pytest.mark.django_db
class TestAdminUserStats:
    def test_stats_returns_counts(self, admin_client, regular_user, unverified_user):
        response = admin_client.get("/api/v1/admin/users/stats/")
        assert response.status_code == 200
        data = response.data
        assert "total" in data
        assert "active" in data
        assert "verified" in data
        assert "admins" in data
        assert "school_admins" in data
        assert data["total"] >= 3  # admin + regular + unverified

    def test_user_cannot_view_stats(self, user_client):
        response = user_client.get("/api/v1/admin/users/stats/")
        assert response.status_code == 403
