"""
Serializers for superadmin location management APIs.
"""
from rest_framework import serializers

from locations.models import LocationNode, LocationType, LocationTypeRule


class LocationTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = LocationType
        fields = ["id", "code", "name", "sort_order", "can_hold_assets", "is_active"]
        read_only_fields = ["id"]


class AdminLocationNodeSerializer(serializers.ModelSerializer):
    location_type_id = serializers.UUIDField(source="location_type.id", read_only=True)
    location_type_code = serializers.CharField(source="location_type.code", read_only=True)
    location_type_name = serializers.CharField(source="location_type.name", read_only=True)
    parent_name = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = LocationNode
        fields = [
            "id",
            "location_type_id",
            "location_type_code",
            "location_type_name",
            "parent_id",
            "parent_name",
            "code",
            "name",
            "depth",
            "path",
            "is_active",
        ]
        read_only_fields = [
            "id",
            "location_type_id",
            "location_type_code",
            "location_type_name",
            "parent_name",
            "depth",
            "path",
        ]

    def get_parent_name(self, obj):
        if obj.parent_id:
            return obj.parent.name
        return None


class AdminLocationNodeCreateSerializer(serializers.Serializer):
    location_type_id = serializers.UUIDField()
    parent_id = serializers.UUIDField(required=False, allow_null=True)
    code = serializers.CharField(max_length=100)
    name = serializers.CharField(max_length=255)

    def validate(self, data):
        from django.shortcuts import get_object_or_404

        location_type = LocationType.objects.filter(pk=data["location_type_id"]).first()
        if not location_type:
            raise serializers.ValidationError({"location_type_id": "Location type not found."})

        parent_id = data.get("parent_id")
        parent = None
        if parent_id:
            parent = LocationNode.objects.filter(pk=parent_id).first()
            if not parent:
                raise serializers.ValidationError({"parent_id": "Parent location not found."})
            rule_exists = LocationTypeRule.objects.filter(
                parent_type=parent.location_type,
                child_type=location_type,
                is_active=True,
            ).exists()
            if not rule_exists:
                raise serializers.ValidationError(
                    {
                        "location_type_id": (
                            f"Location type '{location_type.code}' cannot be placed under "
                            f"'{parent.location_type.code}' — no active LocationTypeRule exists."
                        )
                    }
                )

        data["_location_type"] = location_type
        data["_parent"] = parent
        return data
