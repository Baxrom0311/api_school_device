from django.contrib.auth import get_user_model
from django.db.models import Count, Q
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiResponse
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.pagination import PageNumberPagination

from apps.shared.permissions import IsAdminRole
from apps.users.api.v1.serializers.users import (
    AdminUserListSerializer,
    AdminUserDetailSerializer,
    AdminUserUpdateSerializer,
    AdminSetPasswordSerializer,
)

User = get_user_model()


class AdminUserPagination(PageNumberPagination):
    """Pagination for admin user list."""
    page_size = 10
    page_size_query_param = 'page_size'
    max_page_size = 100


class AdminUserListView(APIView):
    """Admin view for listing and searching users."""
    
    permission_classes = [IsAuthenticated, IsAdminRole]
    pagination_class = AdminUserPagination

    @extend_schema(
        parameters=[
            OpenApiParameter(name='search', description='Search by email, username, or organization', type=str),
            OpenApiParameter(name='role', description='Filter by role (ADMIN, USER)', type=str),
            OpenApiParameter(name='is_active', description='Filter by active status', type=bool),
            OpenApiParameter(name='is_verified', description='Filter by verification status', type=bool),
            OpenApiParameter(name='page', description='Page number', type=int),
            OpenApiParameter(name='page_size', description='Page size (max 100)', type=int),
            OpenApiParameter(name='ordering', description='Order by field (e.g., -created_at, email)', type=str),
        ],
        responses={200: AdminUserListSerializer(many=True)},
        tags=["Admin - Users"],
        summary="List Users",
        description="List all users with pagination, search, and filters (Admin only)",
    )
    def get(self, request):
        queryset = User.objects.annotate(devices_count=Count('devices'))
        
        # Search filter
        search = request.query_params.get('search', '').strip()
        if search:
            queryset = queryset.filter(
                Q(email__icontains=search) |
                Q(username__icontains=search) |
                Q(first_name__icontains=search) |
                Q(last_name__icontains=search) |
                Q(organization_name__icontains=search)
            )
        
        # Role filter
        role = request.query_params.get('role', '').strip().upper()
        if role in ['ADMIN', 'USER']:
            queryset = queryset.filter(role=role)
        
        # Active status filter
        is_active = request.query_params.get('is_active')
        if is_active is not None:
            queryset = queryset.filter(is_active=is_active.lower() == 'true')
        
        # Verification status filter
        is_verified = request.query_params.get('is_verified')
        if is_verified is not None:
            queryset = queryset.filter(is_verified=is_verified.lower() == 'true')
        
        # Ordering
        ordering = request.query_params.get('ordering', '-created_at')
        allowed_ordering = ['created_at', '-created_at', 'email', '-email', 'username', '-username', 'organization_name', '-organization_name']
        if ordering in allowed_ordering:
            queryset = queryset.order_by(ordering)
        else:
            queryset = queryset.order_by('-created_at')
        
        # Pagination
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(queryset, request)
        
        if page is not None:
            serializer = AdminUserListSerializer(page, many=True)
            return paginator.get_paginated_response(serializer.data)
        
        serializer = AdminUserListSerializer(queryset, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


class AdminUserDetailView(APIView):
    """Admin view for user detail, update, and delete."""
    
    permission_classes = [IsAuthenticated, IsAdminRole]

    def get_object(self, pk):
        try:
            return User.objects.prefetch_related('devices').get(pk=pk)
        except User.DoesNotExist:
            return None

    @extend_schema(
        responses={
            200: AdminUserDetailSerializer,
            404: OpenApiResponse(description="User not found"),
        },
        tags=["Admin - Users"],
        summary="Get User Detail",
        description="Get detailed user information including devices (Admin only)",
    )
    def get(self, request, pk):
        user = self.get_object(pk)
        if not user:
            return Response(
                {"detail": "Foydalanuvchi topilmadi."},
                status=status.HTTP_404_NOT_FOUND,
            )
        
        serializer = AdminUserDetailSerializer(user)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(
        request=AdminUserUpdateSerializer,
        responses={
            200: AdminUserDetailSerializer,
            404: OpenApiResponse(description="User not found"),
        },
        tags=["Admin - Users"],
        summary="Update User",
        description="Update user information (Admin only)",
    )
    def patch(self, request, pk):
        user = self.get_object(pk)
        if not user:
            return Response(
                {"detail": "Foydalanuvchi topilmadi."},
                status=status.HTTP_404_NOT_FOUND,
            )
        
        serializer = AdminUserUpdateSerializer(user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        
        return Response(
            AdminUserDetailSerializer(user).data,
            status=status.HTTP_200_OK,
        )

    @extend_schema(
        responses={
            204: OpenApiResponse(description="User deleted"),
            404: OpenApiResponse(description="User not found"),
            400: OpenApiResponse(description="Cannot delete yourself"),
        },
        tags=["Admin - Users"],
        summary="Delete User",
        description="Delete a user (Admin only). Cannot delete yourself.",
    )
    def delete(self, request, pk):
        user = self.get_object(pk)
        if not user:
            return Response(
                {"detail": "Foydalanuvchi topilmadi."},
                status=status.HTTP_404_NOT_FOUND,
            )
        
        # Cannot delete yourself
        if user.id == request.user.id:
            return Response(
                {"detail": "O'zingizni o'chira olmaysiz."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        
        user.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class AdminSetUserPasswordView(APIView):
    """Admin view for setting user password."""
    
    permission_classes = [IsAuthenticated, IsAdminRole]

    @extend_schema(
        request=AdminSetPasswordSerializer,
        responses={
            200: OpenApiResponse(description="Password changed successfully"),
            404: OpenApiResponse(description="User not found"),
            400: OpenApiResponse(description="Validation error"),
        },
        tags=["Admin - Users"],
        summary="Set User Password",
        description="Admin sets a new password for a user",
    )
    def post(self, request, pk):
        try:
            user = User.objects.get(pk=pk)
        except User.DoesNotExist:
            return Response(
                {"detail": "Foydalanuvchi topilmadi."},
                status=status.HTTP_404_NOT_FOUND,
            )
        
        serializer = AdminSetPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        user.set_password(serializer.validated_data["new_password"])
        user.save()
        
        return Response(
            {"detail": "Parol muvaffaqiyatli yangilandi."},
            status=status.HTTP_200_OK,
        )


class AdminUserStatsView(APIView):
    """Admin view for user statistics."""
    
    permission_classes = [IsAuthenticated, IsAdminRole]

    @extend_schema(
        responses={
            200: OpenApiResponse(description="User statistics"),
        },
        tags=["Admin - Users"],
        summary="User Statistics",
        description="Get user statistics (total, active, verified, admins, etc.)",
    )
    def get(self, request):
        total = User.objects.count()
        active = User.objects.filter(is_active=True).count()
        verified = User.objects.filter(is_verified=True).count()
        admins = User.objects.filter(role='ADMIN').count()
        users = User.objects.filter(role='USER').count()
        with_devices = User.objects.annotate(dc=Count('devices')).filter(dc__gt=0).count()
        
        return Response({
            "total": total,
            "active": active,
            "inactive": total - active,
            "verified": verified,
            "unverified": total - verified,
            "admins": admins,
            "users": users,
            "with_devices": with_devices,
            "without_devices": total - with_devices,
        }, status=status.HTTP_200_OK)
