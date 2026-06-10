import pytest
from django.contrib.auth import get_user_model

User = get_user_model()


@pytest.mark.django_db
class TestLogin:
    def test_login_success(self, api_client, regular_user):
        response = api_client.post(
            "/api/v1/auth/login/",
            {
                "email": "user@test.com",
                "password": "testpass123",
            },
        )
        assert response.status_code == 200
        assert "access" in response.data
        assert "refresh" in response.data
        assert response.data["user"]["email"] == "user@test.com"

    def test_login_wrong_password(self, api_client, regular_user):
        response = api_client.post(
            "/api/v1/auth/login/",
            {
                "email": "user@test.com",
                "password": "wrongpass",
            },
        )
        assert response.status_code == 400

    def test_login_unverified_user(self, api_client, unverified_user):
        response = api_client.post(
            "/api/v1/auth/login/",
            {
                "email": "unverified@test.com",
                "password": "testpass123",
            },
        )
        assert response.status_code == 400
        assert "tasdiqlanmagan" in str(response.data).lower() or "verified" in str(response.data).lower()

    def test_login_nonexistent_email(self, api_client):
        response = api_client.post(
            "/api/v1/auth/login/",
            {
                "email": "nobody@test.com",
                "password": "testpass123",
            },
        )
        assert response.status_code == 400


@pytest.mark.django_db
class TestRegister:
    def test_register_success(self, api_client):
        response = api_client.post(
            "/api/v1/auth/register/",
            {
                "email": "new@test.com",
                "username": "newuser",
                "password": "testpass123",
                "confirm_password": "testpass123",
                "organization_name": "Test Org",
            },
        )
        assert response.status_code == 201
        user = User.objects.get(email="new@test.com")
        assert user.is_verified is False
        assert user.verification_token is not None

    def test_register_duplicate_email(self, api_client, regular_user):
        response = api_client.post(
            "/api/v1/auth/register/",
            {
                "email": "user@test.com",
                "username": "another",
                "password": "testpass123",
                "confirm_password": "testpass123",
            },
        )
        assert response.status_code == 400

    def test_register_password_mismatch(self, api_client):
        response = api_client.post(
            "/api/v1/auth/register/",
            {
                "email": "new2@test.com",
                "username": "newuser2",
                "password": "testpass123",
                "confirm_password": "different",
            },
        )
        assert response.status_code == 400


@pytest.mark.django_db
class TestVerifyEmail:
    def test_verify_email_success(self, api_client):
        user = User.objects.create_user(
            email="verify@test.com",
            username="verifyuser",
            password="testpass123",
            is_verified=False,
        )
        token = user.generate_verification_token()

        response = api_client.post(
            "/api/v1/auth/verify-email/",
            {
                "email": "verify@test.com",
                "token": token,
            },
        )
        assert response.status_code == 200
        assert "access" in response.data

        user.refresh_from_db()
        assert user.is_verified is True

    def test_verify_email_invalid_token(self, api_client, unverified_user):
        response = api_client.post(
            "/api/v1/auth/verify-email/",
            {
                "email": "unverified@test.com",
                "token": "invalid-token",
            },
        )
        assert response.status_code == 400


@pytest.mark.django_db
class TestForgotPassword:
    def test_forgot_password_existing_email(self, api_client, regular_user):
        response = api_client.post(
            "/api/v1/auth/forgot-password/",
            {
                "email": "user@test.com",
            },
        )
        assert response.status_code == 200

        regular_user.refresh_from_db()
        assert regular_user.password_reset_token is not None

    def test_forgot_password_nonexistent_email(self, api_client):
        response = api_client.post(
            "/api/v1/auth/forgot-password/",
            {
                "email": "nobody@test.com",
            },
        )
        # Should not reveal whether email exists
        assert response.status_code == 200

    def test_reset_password_success(self, api_client, regular_user):
        # First request reset
        api_client.post("/api/v1/auth/forgot-password/", {"email": "user@test.com"})
        regular_user.refresh_from_db()
        token = regular_user.password_reset_token

        response = api_client.post(
            "/api/v1/auth/reset-password/",
            {
                "email": "user@test.com",
                "token": token,
                "new_password": "newpass123",
            },
        )
        assert response.status_code == 200

        # Verify new password works
        response = api_client.post(
            "/api/v1/auth/login/",
            {
                "email": "user@test.com",
                "password": "newpass123",
            },
        )
        assert response.status_code == 200

    def test_reset_password_invalid_token(self, api_client, regular_user):
        response = api_client.post(
            "/api/v1/auth/reset-password/",
            {
                "email": "user@test.com",
                "token": "bad-token",
                "new_password": "newpass123",
            },
        )
        assert response.status_code == 400


@pytest.mark.django_db
class TestMe:
    def test_me_authenticated(self, user_client, regular_user):
        response = user_client.get("/api/v1/auth/me/")
        assert response.status_code == 200
        assert response.data["email"] == "user@test.com"

    def test_me_unauthenticated(self, api_client):
        response = api_client.get("/api/v1/auth/me/")
        assert response.status_code == 401

    def test_update_profile(self, user_client, regular_user):
        response = user_client.patch(
            "/api/v1/auth/me/",
            {
                "first_name": "Updated",
                "last_name": "Name",
            },
        )
        assert response.status_code == 200
        assert response.data["first_name"] == "Updated"
        assert response.data["last_name"] == "Name"
        regular_user.refresh_from_db()
        assert regular_user.first_name == "Updated"

    def test_update_profile_cannot_change_role(self, user_client, regular_user):
        response = user_client.patch(
            "/api/v1/auth/me/",
            {
                "role": "ADMIN",
            },
        )
        # Role should not change even if sent
        regular_user.refresh_from_db()
        assert regular_user.role == "USER"

    def test_update_profile_unauthenticated(self, api_client):
        response = api_client.patch("/api/v1/auth/me/", {"first_name": "Hacker"})
        assert response.status_code == 401


@pytest.mark.django_db
class TestChangePassword:
    def test_change_password_success(self, user_client, regular_user):
        response = user_client.post(
            "/api/v1/auth/change-password/",
            {
                "old_password": "testpass123",
                "new_password": "newpass456",
                "confirm_password": "newpass456",
            },
        )
        assert response.status_code == 200

    def test_change_password_wrong_old(self, user_client):
        response = user_client.post(
            "/api/v1/auth/change-password/",
            {
                "old_password": "wrongold",
                "new_password": "newpass456",
                "confirm_password": "newpass456",
            },
        )
        assert response.status_code == 400
