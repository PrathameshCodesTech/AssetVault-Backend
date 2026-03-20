"""
Serializers for superadmin verification cycle management APIs.
"""
from rest_framework import serializers

from verification.models import VerificationCycle


class AdminVerificationCycleSerializer(serializers.ModelSerializer):
    created_by_email = serializers.SerializerMethodField(read_only=True)
    request_count = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = VerificationCycle
        fields = [
            "id",
            "name",
            "code",
            "description",
            "start_date",
            "end_date",
            "status",
            "created_by_id",
            "created_by_email",
            "created_at",
            "updated_at",
            "request_count",
        ]
        read_only_fields = [
            "id",
            "status",
            "created_by_id",
            "created_by_email",
            "created_at",
            "updated_at",
            "request_count",
        ]

    def get_created_by_email(self, obj):
        if obj.created_by_id:
            return obj.created_by.email
        return None

    def get_request_count(self, obj):
        return obj.requests.count()


class AdminVerificationCycleCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=200)
    code = serializers.CharField(max_length=100)
    description = serializers.CharField(required=False, allow_blank=True, default="")
    start_date = serializers.DateField()
    end_date = serializers.DateField()

    def validate_code(self, value):
        if VerificationCycle.objects.filter(code=value).exists():
            raise serializers.ValidationError("A verification cycle with this code already exists.")
        return value

    def validate(self, data):
        if data.get("start_date") and data.get("end_date"):
            if data["end_date"] < data["start_date"]:
                raise serializers.ValidationError("end_date must be on or after start_date.")
        return data
