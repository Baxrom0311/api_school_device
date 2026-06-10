from django.urls import path

from apps.users.api.v1.views import (
    AdminSetUserPasswordView,
    AdminUserDetailView,
    AdminUserListView,
    AdminUserStatsView,
    ChangePasswordView,
    ForgotPasswordView,
    LoginView,
    LogoutView,
    MeView,
    RefreshTokenView,
    RegisterView,
    ResendVerificationView,
    ResetPasswordView,
    VerifyEmailView,
)

urlpatterns = [
    # Auth endpoints
    path("api/v1/auth/login/", LoginView.as_view(), name="login"),
    path("api/v1/auth/logout/", LogoutView.as_view(), name="logout"),
    path("api/v1/auth/refresh/", RefreshTokenView.as_view(), name="token_refresh"),
    path("api/v1/auth/me/", MeView.as_view(), name="me"),
    path("api/v1/auth/register/", RegisterView.as_view(), name="register"),
    path("api/v1/auth/verify-email/", VerifyEmailView.as_view(), name="verify_email"),
    path("api/v1/auth/resend-verification/", ResendVerificationView.as_view(), name="resend_verification"),
    path("api/v1/auth/change-password/", ChangePasswordView.as_view(), name="change_password"),
    path("api/v1/auth/forgot-password/", ForgotPasswordView.as_view(), name="forgot_password"),
    path("api/v1/auth/reset-password/", ResetPasswordView.as_view(), name="reset_password"),
    # Admin user management endpoints
    path("api/v1/admin/users/", AdminUserListView.as_view(), name="admin_user_list"),
    path("api/v1/admin/users/stats/", AdminUserStatsView.as_view(), name="admin_user_stats"),
    path("api/v1/admin/users/<uuid:pk>/", AdminUserDetailView.as_view(), name="admin_user_detail"),
    path(
        "api/v1/admin/users/<uuid:pk>/set-password/", AdminSetUserPasswordView.as_view(), name="admin_set_user_password"
    ),
    # Member endpoints
    path("api/v1/member/me/", MeView.as_view(), name="member_me"),
    path("api/v1/member/change-password/", ChangePasswordView.as_view(), name="member_change_password"),
]
