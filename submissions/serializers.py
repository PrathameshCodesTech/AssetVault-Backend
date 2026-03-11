from rest_framework import serializers

from submissions.models import FieldSubmission, FieldSubmissionPhoto, SubmissionReview


class FieldSubmissionPhotoSerializer(serializers.ModelSerializer):
    url = serializers.SerializerMethodField()

    class Meta:
        model = FieldSubmissionPhoto
        fields = ["id", "url", "image_type", "uploaded_at"]

    def get_url(self, obj):
        request = self.context.get("request")
        if obj.image and request:
            return request.build_absolute_uri(obj.image.url)
        elif obj.image:
            return obj.image.url
        return None


class FieldSubmissionSerializer(serializers.ModelSerializer):
    """Maps to frontend ThirdPartySubmission shape."""

    type = serializers.SerializerMethodField()
    assetId = serializers.SerializerMethodField()
    tempRefId = serializers.CharField(source="id")
    assetName = serializers.SerializerMethodField()
    serialNumber = serializers.CharField(source="serial_number")
    assetType = serializers.CharField(source="asset_type_name")
    locationBreadcrumb = serializers.SerializerMethodField()
    locationPath = serializers.JSONField(source="location_snapshot")
    photoUrl = serializers.SerializerMethodField()
    remarks = serializers.CharField()
    submittedBy = serializers.UUIDField(source="submitted_by_id")
    submittedByName = serializers.SerializerMethodField()
    submittedAt = serializers.DateTimeField(source="submitted_at")
    reviewedBy = serializers.SerializerMethodField()
    reviewedByName = serializers.SerializerMethodField()
    reviewedAt = serializers.DateTimeField(source="reviewed_at")
    reviewNotes = serializers.SerializerMethodField()

    class Meta:
        model = FieldSubmission
        fields = [
            "id",
            "type",
            "assetId",
            "tempRefId",
            "assetName",
            "serialNumber",
            "assetType",
            "locationBreadcrumb",
            "locationPath",
            "photoUrl",
            "remarks",
            "status",
            "submittedBy",
            "submittedByName",
            "submittedAt",
            "reviewedBy",
            "reviewedByName",
            "reviewedAt",
            "reviewNotes",
        ]

    def get_type(self, obj):
        if obj.submission_type == FieldSubmission.SubmissionType.VERIFICATION_EXISTING:
            return "verification"
        return "new_asset"

    def get_assetId(self, obj):
        return obj.asset.asset_id if obj.asset_id else None

    def get_assetName(self, obj):
        if obj.asset_id:
            return obj.asset.name
        return obj.asset_name

    def get_locationBreadcrumb(self, obj):
        snap = obj.location_snapshot
        if isinstance(snap, dict):
            return snap.get("name", "")
        return ""

    def get_photoUrl(self, obj):
        photo = obj.photos.first()
        if photo and photo.image:
            return photo.image.url
        return ""

    def get_submittedByName(self, obj):
        return obj.submitted_by.get_full_name() if obj.submitted_by_id else None

    def get_reviewedBy(self, obj):
        review = obj.reviews.first()
        return str(review.reviewed_by_id) if review else None

    def get_reviewedByName(self, obj):
        review = obj.reviews.first()
        return review.reviewed_by.get_full_name() if review else None

    def get_reviewNotes(self, obj):
        review = obj.reviews.first()
        return review.review_notes if review else None


class FieldSubmissionCreateSerializer(serializers.Serializer):
    """For creating a new field submission."""

    submission_type = serializers.ChoiceField(
        choices=FieldSubmission.SubmissionType.choices
    )
    location_id = serializers.UUIDField()
    asset_id = serializers.UUIDField(required=False, allow_null=True)
    asset_name = serializers.CharField(max_length=300, required=False, allow_blank=True)
    serial_number = serializers.CharField(max_length=200, required=False, allow_blank=True)
    asset_type_name = serializers.CharField(max_length=200, required=False, allow_blank=True)
    remarks = serializers.CharField(required=False, allow_blank=True)


class SubmissionReviewSerializer(serializers.ModelSerializer):
    reviewedByName = serializers.SerializerMethodField()

    class Meta:
        model = SubmissionReview
        fields = [
            "id",
            "decision",
            "review_notes",
            "reviewed_by",
            "reviewedByName",
            "created_at",
        ]

    def get_reviewedByName(self, obj):
        return obj.reviewed_by.get_full_name()


class AdminReviewActionSerializer(serializers.Serializer):
    decision = serializers.ChoiceField(choices=SubmissionReview.Decision.choices)
    review_notes = serializers.CharField(required=False, allow_blank=True, default="")


class ConvertToAssetSerializer(serializers.Serializer):
    asset_id = serializers.CharField(max_length=100)
    name = serializers.CharField(max_length=300)
    category_id = serializers.UUIDField()
    location_id = serializers.UUIDField()
    serial_number = serializers.CharField(max_length=200, required=False, allow_blank=True)
    description = serializers.CharField(required=False, allow_blank=True)
