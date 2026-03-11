from django.urls import path

from locations.views import (
    LocationByLevelView,
    LocationDetailView,
    LocationHierarchyView,
    LocationNodeListView,
    LocationTreeView,
    LocationTypeListView,
)

app_name = "locations"

# Level codes that the frontend expects as dedicated endpoints
LEVEL_CODES = [
    "companies",
    "countries",
    "regions",
    "zones",
    "sites",
    "entities",
    "buildings",
    "wings",
    "areas",
    "floors",
    "units",
    "rooms",
]

# Map plural URL segment -> singular location_type.code
_LEVEL_MAP = {
    "companies": "company",
    "countries": "country",
    "regions": "region",
    "zones": "zone",
    "sites": "site",
    "entities": "entity",
    "buildings": "building",
    "wings": "wing",
    "areas": "area",
    "floors": "floor",
    "units": "unit",
    "rooms": "room",
}

urlpatterns = [
    path("types/", LocationTypeListView.as_view(), name="types"),
    path("nodes/", LocationNodeListView.as_view(), name="nodes"),
    path("tree/", LocationTreeView.as_view(), name="tree"),
    path("hierarchy", LocationHierarchyView.as_view(), name="hierarchy"),
    path("<uuid:pk>/", LocationDetailView.as_view(), name="detail"),
]

# Add per-level endpoints: /api/locations/buildings/, /api/locations/floors/, etc.
for plural, singular in _LEVEL_MAP.items():
    urlpatterns.append(
        path(
            f"{plural}/",
            LocationByLevelView.as_view(),
            kwargs={"level_code": singular},
            name=f"by-level-{singular}",
        )
    )
