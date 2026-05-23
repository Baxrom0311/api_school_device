import hmac
import secrets
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils import timezone
from drf_spectacular.utils import extend_schema, OpenApiResponse
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.users.utils import send_password_reset_email

User = get_user_model()


class ForgotPasswordView(APIView):
    """Request password reset token."""

    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "forgot_password"

    @extend_schema(
        request={"application/json": {"type": "object", "properties": {"email": {"type": "string"}}}},
        responses={200: OpenApiResponse(description="Reset email sent")},
        tags=["Auth"],
        summary="Forgot Password",
    )
    def post(self, request):
        email = request.data.get("email")
        if not email:
            return Response({"detail": "Email kiritilishi shart."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            # Don't reveal whether email exists
            return Response({"detail": "Agar email mavjud bo'lsa, tiklash havolasi yuborildi."})

        # Generate dedicated password reset token
        user.password_reset_token = secrets.token_urlsafe(32)
        user.password_reset_token_expires = timezone.now() + timedelta(hours=1)
        user.save(update_fields=["password_reset_token", "password_reset_token_expires"])

        send_password_reset_email(user.email, user.password_reset_token)

        return Response({"detail": "Agar email mavjud bo'lsa, tiklash havolasi yuborildi."})


class ResetPasswordView(APIView):
    """Reset password with token."""

    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "reset_password"

    @extend_schema(
        request={"application/json": {"type": "object", "properties": {
            "email": {"type": "string"},
            "token": {"type": "string"},
            "new_password": {"type": "string"},
        }}},
        responses={
            200: OpenApiResponse(description="Password reset successful"),
            400: OpenApiResponse(description="Invalid or expired token"),
        },
        tags=["Auth"],
        summary="Reset Password",
    )
    def post(self, request):
        email = request.data.get("email")
        token = request.data.get("token")
        new_password = request.data.get("new_password")

        if not all([email, token, new_password]):
            return Response(
                {"detail": "email, token va new_password kiritilishi shart."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            return Response({"detail": "Token yaroqsiz yoki muddati tugagan."}, status=status.HTTP_400_BAD_REQUEST)

        if not user.password_reset_token or not hmac.compare_digest(user.password_reset_token, token):
            return Response({"detail": "Token yaroqsiz yoki muddati tugagan."}, status=status.HTTP_400_BAD_REQUEST)

        if user.password_reset_token_expires and user.password_reset_token_expires < timezone.now():
            return Response({"detail": "Token muddati tugagan."}, status=status.HTTP_400_BAD_REQUEST)

        # Validate password against Django validators
        try:
            validate_password(new_password, user)
        except DjangoValidationError as e:
            return Response(
                {"new_password": e.messages},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user.set_password(new_password)
        user.password_reset_token = None
        user.password_reset_token_expires = None
        user.save(update_fields=["password", "password_reset_token", "password_reset_token_expires"])

        return Response({"detail": "Parol muvaffaqiyatli yangilandi."})
