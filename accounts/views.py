from django.conf import settings
from django.db.models import Q
from access.permissions import permission_required
from rest_framework import status
from rest_framework.generics import ListAPIView, RetrieveAPIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import OtpChallenge, User
from accounts.serializers import SendOtpSerializer, UserOptionSerializer, UserSerializer, VerifyOtpSerializer
from accounts.services.email_service import send_tracked_email
from accounts.services.otp_service import (
    check_resend_throttle,
    create_otp_challenge,
    mark_otp_consumed,
    verify_otp,
)


class SendOtpView(APIView):
    """POST /api/auth/send-otp — request an OTP for login."""

    permission_classes = [AllowAny]

    def post(self, request):
        serializer = SendOtpSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data["email"].lower().strip()

        try:
            user = User.objects.get(email__iexact=email, is_active=True)
        except User.DoesNotExist:
            return Response(
                {"detail": "No active account found for this email."},
                status=status.HTTP_404_NOT_FOUND,
            )

        try:
            check_resend_throttle(email, OtpChallenge.Purpose.LOGIN)
        except ValueError as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        challenge, raw_code = create_otp_challenge(
            email=email,
            purpose=OtpChallenge.Purpose.LOGIN,
            user=user,
        )

        _record, sent_ok = send_tracked_email(
            to_email=email,
            subject="Your Asset Vault login code",
            body=(
                f"Your login code is: {raw_code}\n\n"
                f"This code expires in 10 minutes.\n"
                f"If you did not request this, please ignore this message."
            ),
            template_code="login_otp",
            related_object_type="OtpChallenge",
            related_object_id=str(challenge.pk),
        )

        if not sent_ok:
            challenge.delete()
            return Response(
                {"detail": "Unable to send OTP email. Please try again shortly."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        response_data = {"challenge_id": str(challenge.pk)}
        if settings.DEBUG:
            response_data["debug_otp"] = raw_code

        return Response(response_data, status=status.HTTP_200_OK)


class VerifyOtpView(APIView):
    """POST /api/auth/verify-otp — verify OTP and get JWT tokens."""

    permission_classes = [AllowAny]

    def post(self, request):
        serializer = VerifyOtpSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        challenge_id = serializer.validated_data["challenge_id"]
        email = serializer.validated_data["email"].lower().strip()
        otp = serializer.validated_data["otp"]

        try:
            challenge = OtpChallenge.objects.get(
                pk=challenge_id,
                email__iexact=email,
                purpose=OtpChallenge.Purpose.LOGIN,
            )
        except OtpChallenge.DoesNotExist:
            return Response(
                {"detail": "Invalid challenge."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            verify_otp(challenge, otp)
        except ValueError as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        mark_otp_consumed(challenge)

        try:
            user = User.objects.get(email__iexact=email, is_active=True)
        except User.DoesNotExist:
            return Response(
                {"detail": "User account not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Generate JWT tokens
        refresh = RefreshToken.for_user(user)

        user_data = UserSerializer(user).data

        return Response(
            {
                "access": str(refresh.access_token),
                "refresh": str(refresh),
                "user": user_data,
            },
            status=status.HTTP_200_OK,
        )


class LogoutView(APIView):
    """POST /api/auth/logout — blacklist the refresh token."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        refresh_token = request.data.get("refresh")
        if not refresh_token:
            return Response(
                {"detail": "Refresh token is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            token = RefreshToken(refresh_token)
            token.blacklist()
        except Exception:
            return Response(
                {"detail": "Invalid or already blacklisted token."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response({"detail": "Logged out."}, status=status.HTTP_200_OK)


class MeView(RetrieveAPIView):
    """GET /api/auth/me — return current user with RBAC data."""

    permission_classes = [IsAuthenticated]
    serializer_class = UserSerializer

    def get_object(self):
        return self.request.user


class UserListView(ListAPIView):
    """
    GET /api/auth/users/ — list active users for employee selection.

    Supports ?search=<str> to filter by email, first_name, or last_name.
    """

    permission_classes = [IsAuthenticated, permission_required("asset.create", "verification.request")]
    serializer_class = UserOptionSerializer

    def get_queryset(self):
        qs = User.objects.filter(is_active=True).order_by("first_name", "email")

        role = self.request.query_params.get("role", "").strip()
        if role:
            from access.models import UserRoleAssignment
            user_ids = UserRoleAssignment.objects.filter(
                role__code=role, is_active=True
            ).values_list("user_id", flat=True)
            qs = qs.filter(pk__in=user_ids)

        search = self.request.query_params.get("search", "").strip()
        if search:
            qs = qs.filter(
                Q(email__icontains=search)
                | Q(first_name__icontains=search)
                | Q(last_name__icontains=search)
            )
        return qs


class LocationAdminListView(ListAPIView):
    """
    GET /api/auth/location-admins/ — list users with active location_admin role.

    Returns id, name, email and their assigned location name(s).
    Only accessible by super_admin.
    """

    permission_classes = [IsAuthenticated]
    pagination_class = None

    def get(self, request):
        from access.helpers import get_user_scope
        from access.models import UserRoleAssignment

        scope = get_user_scope(request.user)
        if scope.get("primary_role_code") != "super_admin":
            from rest_framework.response import Response as _Response
            return _Response({"detail": "Forbidden."}, status=403)

        search = request.query_params.get("search", "").strip()

        assignments = (
            UserRoleAssignment.objects.filter(is_active=True, role__code="location_admin")
            .select_related("user", "location")
            .order_by("user__first_name", "user__email")
        )

        if search:
            assignments = assignments.filter(
                Q(user__first_name__icontains=search)
                | Q(user__last_name__icontains=search)
                | Q(user__email__icontains=search)
                | Q(location__name__icontains=search)
            )

        # Deduplicate users, collecting all their location assignments
        seen = {}
        for a in assignments:
            uid = str(a.user_id)
            if uid not in seen:
                seen[uid] = {
                    "id": uid,
                    "name": a.user.get_full_name() or a.user.email,
                    "email": a.user.email,
                    "locations": [],
                }
            if a.location_id:
                seen[uid]["locations"].append({"id": str(a.location_id), "name": a.location.name})

        from rest_framework.response import Response as _Response
        return _Response(list(seen.values()))
