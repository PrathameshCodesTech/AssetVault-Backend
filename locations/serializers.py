from rest_framework import serializers

from locations.models import LocationClosure, LocationNode, LocationType


class LocationTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = LocationType
        fields = ["id", "code", "name", "sort_order", "can_hold_assets", "is_active"]


class LocationNodeSerializer(serializers.ModelSerializer):
    """Flat representation of a location node."""

    level = serializers.CharField(source="location_type.code", read_only=True)
    parentId = serializers.UUIDField(source="parent_id", read_only=True)
    locationType = serializers.CharField(source="location_type.name", read_only=True)

    class Meta:
        model = LocationNode
        fields = [
            "id",
            "name",
            "code",
            "level",
            "locationType",
            "parentId",
            "depth",
            "path",
            "is_active",
        ]


class LocationNodeTreeSerializer(serializers.ModelSerializer):
    """Nested tree representation with children."""

    level = serializers.CharField(source="location_type.code", read_only=True)
    parentId = serializers.UUIDField(source="parent_id", read_only=True)
    children = serializers.SerializerMethodField()

    class Meta:
        model = LocationNode
        fields = ["id", "name", "code", "level", "parentId", "depth", "children"]

    def get_children(self, obj):
        # children are pre-loaded via _children_cache
        children = getattr(obj, "_children_cache", [])
        return LocationNodeTreeSerializer(children, many=True).data


def build_location_tree(queryset=None):
    """
    Build a nested location tree from all active LocationNodes.
    Returns a list of root-level serialized nodes with nested children.
    """
    if queryset is None:
        queryset = LocationNode.objects.filter(is_active=True)

    nodes = list(
        queryset.select_related("location_type").order_by("depth", "name")
    )

    node_map = {node.pk: node for node in nodes}

    # Initialize children cache
    for node in nodes:
        node._children_cache = []

    roots = []
    for node in nodes:
        if node.parent_id and node.parent_id in node_map:
            node_map[node.parent_id]._children_cache.append(node)
        elif node.parent_id is None:
            roots.append(node)
        else:
            # Parent not in queryset (possibly filtered out) - treat as root
            roots.append(node)

    return LocationNodeTreeSerializer(roots, many=True).data


def get_location_breadcrumb(location_node):
    """
    Return a list of ancestor dicts [{id, name, level}] ordered from root to leaf.
    """
    if location_node is None:
        return []

    ancestors = (
        LocationClosure.objects.filter(descendant=location_node)
        .select_related("ancestor__location_type")
        .order_by("depth")  # descending depth = root first
    )

    # depth=0 is self, higher depth is further ancestor
    # We want root-first ordering so we reverse
    breadcrumb = []
    for closure in ancestors:
        breadcrumb.append(
            {
                "id": str(closure.ancestor_id),
                "name": closure.ancestor.name,
                "level": closure.ancestor.location_type.code,
            }
        )

    # Reverse so root is first (highest depth first)
    breadcrumb.reverse()
    return breadcrumb
