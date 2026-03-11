import csv
import io

from django.db.models import Count, Q
from django.http import StreamingHttpResponse
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from access.helpers import filter_by_location_scope
from access.permissions import permission_required
from assets.models import Asset, AssetEvent
from assets.serializers import AssetEventSerializer, AssetListSerializer


class ReconciliationReportView(APIView):
    """GET /api/reports/reconciliation — reconciliation status grouped by location."""

    permission_classes = [IsAuthenticated, permission_required("report.view")]

    def get(self, request):
        qs = Asset.objects.all()
        qs = filter_by_location_scope(qs, request.user)

        location_id = request.query_params.get("location_id")
        if location_id:
            qs = qs.filter(current_location_id=location_id)

        breakdown = list(
            qs.values("current_location__name", "current_location_id")
            .annotate(
                total=Count("id"),
                verified=Count(
                    "id",
                    filter=Q(
                        reconciliation_status=Asset.ReconciliationStatus.VERIFIED
                    ),
                ),
                pending=Count(
                    "id",
                    filter=Q(
                        reconciliation_status=Asset.ReconciliationStatus.PENDING
                    ),
                ),
                discrepancy=Count(
                    "id",
                    filter=Q(
                        reconciliation_status=Asset.ReconciliationStatus.DISCREPANCY
                    ),
                ),
            )
            .order_by("current_location__name")
        )

        data = [
            {
                "locationId": str(item["current_location_id"]),
                "locationName": item["current_location__name"],
                "total": item["total"],
                "verified": item["verified"],
                "pending": item["pending"],
                "discrepancy": item["discrepancy"],
            }
            for item in breakdown
        ]

        if request.query_params.get("export") == "csv":
            return self._export_csv(data)

        return Response(data)

    def _export_csv(self, data):
        def generate():
            writer_buf = io.StringIO()
            writer = csv.writer(writer_buf)
            writer.writerow(
                ["Location", "Total", "Verified", "Pending", "Discrepancy"]
            )
            writer_buf.seek(0)
            yield writer_buf.read()

            for row in data:
                writer_buf = io.StringIO()
                writer = csv.writer(writer_buf)
                writer.writerow(
                    [
                        row["locationName"],
                        row["total"],
                        row["verified"],
                        row["pending"],
                        row["discrepancy"],
                    ]
                )
                writer_buf.seek(0)
                yield writer_buf.read()

        response = StreamingHttpResponse(generate(), content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="reconciliation_report.csv"'
        return response


class DiscrepancyReportView(APIView):
    """GET /api/reports/discrepancy — assets with discrepancy status."""

    permission_classes = [IsAuthenticated, permission_required("report.view")]

    def get(self, request):
        qs = Asset.objects.filter(
            reconciliation_status=Asset.ReconciliationStatus.DISCREPANCY
        ).select_related(
            "category",
            "sub_type",
            "business_entity",
            "current_location",
            "current_location__location_type",
            "assigned_to",
        )
        qs = filter_by_location_scope(qs, request.user)

        location_id = request.query_params.get("location_id")
        if location_id:
            qs = qs.filter(current_location_id=location_id)

        date_from = request.query_params.get("date_from")
        if date_from:
            qs = qs.filter(updated_at__date__gte=date_from)

        date_to = request.query_params.get("date_to")
        if date_to:
            qs = qs.filter(updated_at__date__lte=date_to)

        qs = qs.order_by("-updated_at")

        if request.query_params.get("export") == "csv":
            return self._export_csv(qs)

        from rest_framework.pagination import PageNumberPagination

        paginator = PageNumberPagination()
        paginator.page_size = int(request.query_params.get("page_size", 25))
        page = paginator.paginate_queryset(qs, request)
        serializer = AssetListSerializer(page, many=True, context={"request": request})
        return paginator.get_paginated_response(serializer.data)

    def _export_csv(self, qs):
        def generate():
            buf = io.StringIO()
            writer = csv.writer(buf)
            writer.writerow(
                ["Asset ID", "Name", "Category", "Location", "Status", "Reconciliation"]
            )
            buf.seek(0)
            yield buf.read()

            for asset in qs.iterator():
                buf = io.StringIO()
                writer = csv.writer(buf)
                writer.writerow(
                    [
                        asset.asset_id,
                        asset.name,
                        asset.category.name if asset.category_id else "",
                        asset.current_location.name if asset.current_location_id else "",
                        asset.status,
                        asset.reconciliation_status,
                    ]
                )
                buf.seek(0)
                yield buf.read()

        response = StreamingHttpResponse(generate(), content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="discrepancy_report.csv"'
        return response


class AuditReportView(APIView):
    """GET /api/reports/audit — asset events timeline."""

    permission_classes = [IsAuthenticated, permission_required("report.view")]

    def get(self, request):
        qs = AssetEvent.objects.select_related(
            "actor", "from_location", "to_location", "asset"
        )

        # Apply location scope via asset
        from access.helpers import get_user_scope

        scope = get_user_scope(request.user)
        if not scope["is_global"] and scope["location_ids"]:
            qs = qs.filter(asset__current_location_id__in=scope["location_ids"])
        elif not scope["is_global"] and not scope["location_ids"]:
            qs = qs.none()

        location_id = request.query_params.get("location_id")
        if location_id:
            qs = qs.filter(
                Q(from_location_id=location_id)
                | Q(to_location_id=location_id)
                | Q(asset__current_location_id=location_id)
            )

        date_from = request.query_params.get("date_from")
        if date_from:
            qs = qs.filter(created_at__date__gte=date_from)

        date_to = request.query_params.get("date_to")
        if date_to:
            qs = qs.filter(created_at__date__lte=date_to)

        event_type = request.query_params.get("event_type")
        if event_type:
            qs = qs.filter(event_type=event_type)

        qs = qs.order_by("-created_at")

        if request.query_params.get("export") == "csv":
            return self._export_csv(qs)

        from rest_framework.pagination import PageNumberPagination

        paginator = PageNumberPagination()
        paginator.page_size = int(request.query_params.get("page_size", 25))
        page = paginator.paginate_queryset(qs, request)
        serializer = AssetEventSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)

    def _export_csv(self, qs):
        def generate():
            buf = io.StringIO()
            writer = csv.writer(buf)
            writer.writerow(
                ["Timestamp", "Event Type", "Asset ID", "Description", "Actor", "From", "To"]
            )
            buf.seek(0)
            yield buf.read()

            for event in qs.iterator():
                buf = io.StringIO()
                writer = csv.writer(buf)
                writer.writerow(
                    [
                        event.created_at.isoformat(),
                        event.event_type,
                        event.asset.asset_id if event.asset_id else "",
                        event.description,
                        event.actor.get_full_name() if event.actor_id else "",
                        event.from_location.name if event.from_location_id else "",
                        event.to_location.name if event.to_location_id else "",
                    ]
                )
                buf.seek(0)
                yield buf.read()

        response = StreamingHttpResponse(generate(), content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="audit_report.csv"'
        return response
