"""
Serializers for vendor organization and vendor verification request APIs.
"""
from rest_framework import serializers

from vendors.models import (
    VendorOrganization,
    VendorRequestAssetPhoto,
    VendorUserAssignment,
    VendorVerificationRequest,
    VendorVerificationRequestAsset,
)


class VendorOrganizationSerializer(serializers.ModelSerializer):
    user_count = serializers.SerializerMethodField(read_only=True)
    request_count = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = VendorOrganization
        fields = [
            "id", "code", "name", "contact_email", "contact_phone",
            "notes", "is_active", "user_count", "request_count", "created_at",
        ]
        read_only_fields = ["id", "created_at", "user_count", "request_count"]

    def get_user_count(self, obj):
        return obj.user_assignments.filter(is_active=True).count()

    def get_request_count(self, obj):
        return obj.verification_requests.count()


class VendorUserAssignmentSerializer(serializers.ModelSerializer):
    user_email = serializers.EmailField(source="user.email", read_only=True)
    user_name = serializers.SerializerMethodField(read_only=True)
    vendor_name = serializers.CharField(source="vendor.name", read_only=True)

    class Meta:
        model = VendorUserAssignment
        fields = ["id", "vendor_id", "vendor_name", "user_id", "user_email", "user_name", "is_active", "created_at"]
        read_only_fields = ["id", "vendor_name", "user_email", "user_name", "created_at"]

    def get_user_name(self, obj):
        return obj.user.get_full_name() or obj.user.email


class VendorRequestAssetPhotoSerializer(serializers.ModelSerializer):
    image_url = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = VendorRequestAssetPhoto
        fields = ["id", "image_url", "uploaded_at"]

    def get_image_url(self, obj):
        request = self.context.get("request")
        if obj.image and request:
            return request.build_absolute_uri(obj.image.url)
        return None


class VendorVerificationRequestAssetSerializer(serializers.ModelSerializer):
    photos = VendorRequestAssetPhotoSerializer(many=True, read_only=True)
    observed_location_name = serializers.CharField(
        source="observed_location.name", read_only=True, default=None
    )

    class Meta:
        model = VendorVerificationRequestAsset
        fields = [
            "id",
            "asset_id",
            "asset_id_snapshot",
            "asset_name_snapshot",
            "asset_location_snapshot",
            "response_status",
            "response_notes",
            "observed_location_id",
            "observed_location_name",
            "responded_at",
            "admin_decision",
            "photos",
        ]
        read_only_fields = [
            "id", "asset_id", "asset_id_snapshot", "asset_name_snapshot",
            "asset_location_snapshot", "responded_at", "admin_decision", "photos",
            "observed_location_name",
        ]


class VendorVerificationRequestSerializer(serializers.ModelSerializer):
    vendor_name = serializers.CharField(source="vendor.name", read_only=True)
    requested_by_email = serializers.EmailField(source="requested_by.email", read_only=True)
    asset_count = serializers.SerializerMethodField(read_only=True)
    pending_count = serializers.SerializerMethodField(read_only=True)
    approved_count = serializers.SerializerMethodField(read_only=True)
    correction_count = serializers.SerializerMethodField(read_only=True)
    pending_review_count = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = VendorVerificationRequest
        fields = [
            "id", "reference_code", "vendor_id", "vendor_name",
            "requested_by_id", "requested_by_email",
            "location_scope_id", "status", "notes", "review_notes",
            "sent_at", "submitted_at", "reviewed_at",
            "asset_count", "pending_count",
            "approved_count", "correction_count", "pending_review_count",
            "created_at",
        ]
        read_only_fields = [
            "id", "reference_code", "vendor_name", "requested_by_id", "requested_by_email",
            "sent_at", "submitted_at", "reviewed_at",
            "asset_count", "pending_count", "approved_count", "correction_count", "pending_review_count",
            "created_at",
        ]

    def get_asset_count(self, obj):
        return obj.request_assets.count()

    def get_pending_count(self, obj):
        return obj.request_assets.filter(
            response_status=VendorVerificationRequestAsset.ResponseStatus.PENDING
        ).count()

    def get_approved_count(self, obj):
        return obj.request_assets.filter(
            admin_decision=VendorVerificationRequestAsset.AdminDecision.APPROVED
        ).count()

    def get_correction_count(self, obj):
        return obj.request_assets.filter(
            admin_decision=VendorVerificationRequestAsset.AdminDecision.CORRECTION_REQUIRED
        ).count()

    def get_pending_review_count(self, obj):
        return obj.request_assets.filter(
            admin_decision=VendorVerificationRequestAsset.AdminDecision.PENDING_REVIEW
        ).count()


class VendorVerificationRequestDetailSerializer(VendorVerificationRequestSerializer):
    request_assets = VendorVerificationRequestAssetSerializer(many=True, read_only=True)

    class Meta(VendorVerificationRequestSerializer.Meta):
        fields = VendorVerificationRequestSerializer.Meta.fields + ["request_assets"]
        read_only_fields = VendorVerificationRequestSerializer.Meta.read_only_fields + ["request_assets"]
