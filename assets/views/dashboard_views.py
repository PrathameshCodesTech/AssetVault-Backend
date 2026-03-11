from decimal import Decimal

from django.db.models import Count, Q, Sum
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from access.helpers import filter_by_location_scope, get_user_scope
from access.permissions import permission_required
from assets.models import Asset, AssetEvent
from assets.serializers import AssetEventSerializer


class DashboardSummaryView(APIView):
    """GET /api/dashboard/summary — dashboard overview stats."""

    permission_classes = [IsAuthenticated, permission_required("dashboard.view")]

    def get(self, request):
        base_qs = Asset.objects.all()
        base_qs = filter_by_location_scope(base_qs, request.user)

        total_assets = base_qs.count()
        pending_reconciliation = base_qs.filter(
            reconciliation_status=Asset.ReconciliationStatus.PENDING
        ).count()
        verified_assets = base_qs.filter(
            reconciliation_status=Asset.ReconciliationStatus.VERIFIED
        ).count()
        discrepancies = base_qs.filter(
            reconciliation_status=Asset.ReconciliationStatus.DISCREPANCY
        ).count()

        reconciliation_progress = 0.0
        if total_assets > 0:
            reconciliation_progress = round(
                (verified_assets / total_assets) * 100, 1
            )

        # Assets assigned to current user
        assigned_to_me = base_qs.filter(assigned_to=request.user).count()

        # Total purchase value
        total_value = base_qs.aggregate(total=Sum("purchase_value"))["total"] or Decimal("0")

        # Category breakdown
        category_breakdown = list(
            base_qs.values("category__name")
            .annotate(count=Count("id"))
            .order_by("-count")[:10]
        )
        category_breakdown = [
            {"categoryName": item["category__name"], "count": item["count"]}
            for item in category_breakdown
        ]

        # Location breakdown
        location_breakdown = list(
            base_qs.values("current_location__name")
            .annotate(
                total=Count("id"),
                verified=Count(
                    "id",
                    filter=Q(
                        reconciliation_status=Asset.ReconciliationStatus.VERIFIED
                    ),
                ),
            )
            .order_by("-total")[:10]
        )
        location_breakdown = [
            {
                "locationName": item["current_location__name"],
                "total": item["total"],
                "verified": item["verified"],
            }
            for item in location_breakdown
        ]

        # Recent activity
        event_qs = AssetEvent.objects.select_related(
            "actor", "from_location", "to_location"
        ).order_by("-created_at")

        # Scope events to user's locations
        scope = get_user_scope(request.user)
        if not scope["is_global"] and scope["location_ids"]:
            event_qs = event_qs.filter(
                asset__current_location_id__in=scope["location_ids"]
            )
        elif not scope["is_global"] and not scope["location_ids"]:
            event_qs = event_qs.none()

        recent_events = event_qs[:10]
        recent_activity = AssetEventSerializer(recent_events, many=True).data

        return Response(
            {
                "totalAssets": total_assets,
                "pendingReconciliation": pending_reconciliation,
                "verifiedAssets": verified_assets,
                "discrepancies": discrepancies,
                "reconciliationProgress": reconciliation_progress,
                "recentActivity": recent_activity,
                "locationBreakdown": location_breakdown,
                "assignedToMe": assigned_to_me,
                "categoryBreakdown": category_breakdown,
                "totalValue": float(total_value),
            }
        )
