from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenRefreshSerializer

User = get_user_model()


class LoginSerializer(serializers.Serializer):
    """Login serializer with email and password."""

    email = serializers.EmailField(required=True)
    password = serializers.CharField(required=True, write_only=True)

    def validate(self, attrs):
        email = attrs.get("email")
        password = attrs.get("password")

        if not email or not password:
            raise serializers.ValidationError("Email va parol kiritilishi shart.")

        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist as exc:
            raise serializers.ValidationError("Email yoki parol noto'g'ri.") from exc

        if not user.check_password(password):
            raise serializers.ValidationError("Email yoki parol noto'g'ri.")

        if not user.is_active:
            raise serializers.ValidationError("Email yoki parol noto'g'ri.")

        if not user.is_verified:
            raise serializers.ValidationError("Email tasdiqlanmagan. Iltimos, emailingizni tasdiqlang.")

        attrs["user"] = user
        return attrs


class UserSerializer(serializers.ModelSerializer):
    """User profile serializer."""

    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "username",
            "first_name",
            "last_name",
            "avatar",
            "role",
            "is_active",
            "is_verified",
            "organization_name",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "email", "created_at", "updated_at", "is_verified", "role", "is_active"]


class RegisterSerializer(serializers.Serializer):
    """Registration serializer with email, password, and organization."""

    email = serializers.EmailField(required=True)
    password = serializers.CharField(required=True, write_only=True, min_length=7)
    confirm_password = serializers.CharField(required=True, write_only=True)
    username = serializers.CharField(required=True, max_length=100)
    organization_name = serializers.CharField(required=False, max_length=255, allow_blank=True)
    first_name = serializers.CharField(required=False, max_length=150, allow_blank=True)
    last_name = serializers.CharField(required=False, max_length=150, allow_blank=True)

    def validate_email(self, value):
        """Check if email already exists."""
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError("Bu email allaqachon ro'yxatdan o'tgan.")
        return value

    def validate_username(self, value):
        """Check if username already exists."""
        if User.objects.filter(username=value).exists():
            raise serializers.ValidationError("Bu username allaqachon band.")
        return value

    def validate(self, attrs):
        """Validate passwords match and meet strength requirements."""
        if attrs.get("password") != attrs.get("confirm_password"):
            raise serializers.ValidationError({"confirm_password": "Parollar mos kelmaydi."})

        try:
            validate_password(attrs["password"])
        except DjangoValidationError as e:
            raise serializers.ValidationError({"password": list(e.messages)}) from e

        return attrs

    def create(self, validated_data):
        """Create new user."""
        validated_data.pop("confirm_password")
        password = validated_data.pop("password")

        user = User.objects.create_user(
            email=validated_data["email"],
            username=validated_data["username"],
            password=password,
            organization_name=validated_data.get("organization_name", ""),
            first_name=validated_data.get("first_name", ""),
            last_name=validated_data.get("last_name", ""),
            is_verified=False,
        )

        # Generate verification token
        user.generate_verification_token()

        return user


class VerifyEmailSerializer(serializers.Serializer):
    """Email verification serializer."""

    email = serializers.EmailField(required=True)
    token = serializers.CharField(required=True)

    def validate(self, attrs):
        """Validate token."""
        email = attrs.get("email")
        token = attrs.get("token")

        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist as exc:
            raise serializers.ValidationError("Token yaroqsiz yoki muddati tugagan.") from exc

        if user.is_verified:
            raise serializers.ValidationError("Token yaroqsiz yoki muddati tugagan.")

        if not user.verify_email(token):
            raise serializers.ValidationError("Token yaroqsiz yoki muddati tugagan.")

        attrs["user"] = user
        return attrs


class ResendVerificationSerializer(serializers.Serializer):
    """Resend verification email serializer."""

    email = serializers.EmailField(required=True)

    def validate_email(self, value):
        """Validate email without revealing existence."""
        # Store for later use but don't reveal if user exists
        self._user = None
        try:
            user = User.objects.get(email=value)
            if not user.is_verified:
                self._user = user
        except User.DoesNotExist:
            pass
        return value


class TokenResponseSerializer(serializers.Serializer):
    """Token response serializer."""

    access = serializers.CharField(read_only=True)
    refresh = serializers.CharField(read_only=True)
    user = UserSerializer(read_only=True)


class RefreshTokenSerializer(TokenRefreshSerializer):
    """Refresh token serializer."""

    pass


class LogoutSerializer(serializers.Serializer):
    """Logout serializer."""

    refresh = serializers.CharField(required=True)


class ChangePasswordSerializer(serializers.Serializer):
    """Change password serializer."""

    old_password = serializers.CharField(required=True, write_only=True)
    new_password = serializers.CharField(required=True, write_only=True, min_length=7)
    confirm_password = serializers.CharField(required=True, write_only=True)

    def validate(self, attrs):
        """Validate passwords."""
        if attrs.get("new_password") != attrs.get("confirm_password"):
            raise serializers.ValidationError({"confirm_password": "Parollar mos kelmaydi."})

        if attrs.get("old_password") == attrs.get("new_password"):
            raise serializers.ValidationError({"new_password": "Yangi parol eski paroldan farqli bo'lishi kerak."})

        return attrs
