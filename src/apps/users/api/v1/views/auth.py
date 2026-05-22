from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from drf_spectacular.utils import extend_schema, OpenApiResponse
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenRefreshView

from apps.users.api.v1.serializers import (
    LoginSerializer,
    UserSerializer,
    TokenResponseSerializer,
    LogoutSerializer,
    RegisterSerializer,
    VerifyEmailSerializer,
    ResendVerificationSerializer,
    ChangePasswordSerializer,
)

User = get_user_model()


class LoginView(APIView):
    """Login view using email and password."""

    permission_classes = [AllowAny]
    serializer_class = LoginSerializer
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login"

    @extend_schema(
        request=LoginSerializer,
        responses={
            200: TokenResponseSerializer,
            400: OpenApiResponse(description="Invalid credentials"),
        },
        tags=["Auth"],
        summary="Login",
        description="Login using email and password",
    )
    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = serializer.validated_data["user"]
        tokens = user.tokens()

        return Response(
            {
                "access": tokens["access"],
                "refresh": tokens["refresh"],
                "user": UserSerializer(user).data,
            },
            status=status.HTTP_200_OK,
        )


class LogoutView(APIView):
    """Logout view to blacklist refresh token."""

    permission_classes = [IsAuthenticated]
    serializer_class = LogoutSerializer

    @extend_schema(
        request=LogoutSerializer,
        responses={
            200: OpenApiResponse(description="Successfully logged out"),
            400: OpenApiResponse(description="Invalid token"),
        },
        tags=["Auth"],
        summary="Logout",
        description="Logout and blacklist refresh token",
    )
    def post(self, request):
        serializer = LogoutSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            refresh_token = serializer.validated_data["refresh"]
            token = RefreshToken(refresh_token)
            token.blacklist()
            return Response(
                {"detail": "Muvaffaqiyatli chiqildi."},
                status=status.HTTP_200_OK,
            )
        except Exception:
            return Response(
                {"detail": "Token yaroqsiz yoki muddati tugagan."},
                status=status.HTTP_400_BAD_REQUEST,
            )


class RefreshTokenView(TokenRefreshView):
    """Refresh token view."""

    @extend_schema(
        tags=["Auth"],
        summary="Refresh Token",
        description="Get new access token using refresh token",
    )
    def post(self, request, *args, **kwargs):
        return super().post(request, *args, **kwargs)


class MeView(APIView):
    """Get current user profile."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        responses={200: UserSerializer},
        tags=["Auth"],
        summary="Current User",
        description="Get current authenticated user profile",
    )
    def get(self, request):
        serializer = UserSerializer(request.user)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(
        request=UserSerializer,
        responses={200: UserSerializer},
        tags=["Auth"],
        summary="Update Profile",
        description="Update current authenticated user profile",
    )
    def patch(self, request):
        serializer = UserSerializer(request.user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_200_OK)


class RegisterView(APIView):
    """User registration view."""

    permission_classes = [AllowAny]
    serializer_class = RegisterSerializer
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login"

    @extend_schema(
        request=RegisterSerializer,
        responses={
            201: OpenApiResponse(description="User registered successfully"),
            400: OpenApiResponse(description="Validation error"),
        },
        tags=["Auth"],
        summary="Register",
        description="Register new user with email, password, and organization name",
    )
    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()

        # Send verification email
        from apps.users.utils import send_verification_email
        send_verification_email(user.email, user.verification_token)

        response_data = {
            "detail": "Ro'yxatdan o'tish muvaffaqiyatli. Email tasdiqlash havolasi yuborildi.",
            "email": user.email,
            "verification_required": True,
        }

        # Only include token in DEBUG mode
        from django.conf import settings
        if settings.DEBUG:
            response_data["verification_token"] = user.verification_token

        return Response(response_data, status=status.HTTP_201_CREATED)


class VerifyEmailView(APIView):
    """Email verification view."""

    permission_classes = [AllowAny]
    serializer_class = VerifyEmailSerializer

    @extend_schema(
        request=VerifyEmailSerializer,
        responses={
            200: TokenResponseSerializer,
            400: OpenApiResponse(description="Invalid or expired token"),
        },
        tags=["Auth"],
        summary="Verify Email",
        description="Verify email with token and get access tokens",
    )
    def post(self, request):
        serializer = VerifyEmailSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = serializer.validated_data["user"]
        tokens = user.tokens()

        return Response(
            {
                "detail": "Email muvaffaqiyatli tasdiqlandi.",
                "access": tokens["access"],
                "refresh": tokens["refresh"],
                "user": UserSerializer(user).data,
            },
            status=status.HTTP_200_OK,
        )


class ResendVerificationView(APIView):
    """Resend verification email view."""

    permission_classes = [AllowAny]
    serializer_class = ResendVerificationSerializer
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "resend_verification"

    @extend_schema(
        request=ResendVerificationSerializer,
        responses={
            200: OpenApiResponse(description="Verification email sent"),
            400: OpenApiResponse(description="Validation error"),
        },
        tags=["Auth"],
        summary="Resend Verification",
        description="Resend verification email",
    )
    def post(self, request):
        serializer = ResendVerificationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = getattr(serializer, '_user', None)
        if user:
            user.resend_verification_token()
            from apps.users.utils import send_verification_email
            send_verification_email(user.email, user.verification_token)

        return Response(
            {"detail": "Agar email mavjud bo'lsa, tasdiqlash havolasi yuborildi."},
            status=status.HTTP_200_OK,
        )


class ChangePasswordView(APIView):
    """Change password view."""

    permission_classes = [IsAuthenticated]
    serializer_class = ChangePasswordSerializer

    @extend_schema(
        request=ChangePasswordSerializer,
        responses={
            200: OpenApiResponse(description="Password changed successfully"),
            400: OpenApiResponse(description="Validation error"),
        },
        tags=["Auth"],
        summary="Change Password",
        description="Change current user password",
    )
    def post(self, request):
        serializer = ChangePasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = request.user
        old_password = serializer.validated_data["old_password"]
        new_password = serializer.validated_data["new_password"]

        # Check old password
        if not user.check_password(old_password):
            return Response(
                {"old_password": ["Joriy parol noto'g'ri."]},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Validate new password against Django validators
        try:
            validate_password(new_password, user)
        except DjangoValidationError as e:
            return Response(
                {"new_password": e.messages},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Set new password
        user.set_password(new_password)
        user.save()

        return Response(
            {"detail": "Parol muvaffaqiyatli yangilandi."},
            status=status.HTTP_200_OK,
        )
