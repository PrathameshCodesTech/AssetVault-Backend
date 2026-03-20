import uuid

import django.db.models.deletion
import vendors.models
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("assets", "0001_initial"),
        ("locations", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # ------------------------------------------------------------------
        # VendorOrganization
        # ------------------------------------------------------------------
        migrations.CreateModel(
            name="VendorOrganization",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("code", models.CharField(max_length=100, unique=True)),
                ("name", models.CharField(max_length=300)),
                ("contact_email", models.EmailField(blank=True, null=True)),
                ("contact_phone", models.CharField(blank=True, max_length=30, null=True)),
                ("notes", models.TextField(blank=True, null=True)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"db_table": "vendors_vendor_organization", "ordering": ("name",)},
        ),
        # ------------------------------------------------------------------
        # VendorUserAssignment
        # ------------------------------------------------------------------
        migrations.CreateModel(
            name="VendorUserAssignment",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "vendor",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="user_assignments",
                        to="vendors.vendororganization",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="vendor_assignments",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={"db_table": "vendors_vendor_user_assignment"},
        ),
        migrations.AlterUniqueTogether(
            name="vendoruserassignment",
            unique_together={("vendor", "user")},
        ),
        # ------------------------------------------------------------------
        # VendorVerificationRequest
        # ------------------------------------------------------------------
        migrations.CreateModel(
            name="VendorVerificationRequest",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("reference_code", models.CharField(max_length=100, unique=True)),
                (
                    "vendor",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="verification_requests",
                        to="vendors.vendororganization",
                    ),
                ),
                (
                    "requested_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="created_vendor_requests",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "location_scope",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="vendor_requests",
                        to="locations.locationnode",
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("draft", "Draft"),
                            ("sent", "Sent to Vendor"),
                            ("in_progress", "In Progress"),
                            ("submitted", "Submitted by Vendor"),
                            ("correction_requested", "Correction Requested"),
                            ("approved", "Approved"),
                            ("cancelled", "Cancelled"),
                        ],
                        db_index=True,
                        default="draft",
                        max_length=25,
                    ),
                ),
                ("notes", models.TextField(blank=True, null=True)),
                ("review_notes", models.TextField(blank=True, null=True)),
                ("sent_at", models.DateTimeField(blank=True, null=True)),
                ("submitted_at", models.DateTimeField(blank=True, null=True)),
                ("reviewed_at", models.DateTimeField(blank=True, null=True)),
                (
                    "reviewed_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="reviewed_vendor_requests",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "vendors_vendor_verification_request",
                "ordering": ("-created_at",),
            },
        ),
        migrations.AddIndex(
            model_name="vendorverificationrequest",
            index=models.Index(fields=["vendor"], name="vendors_vvr_vendor_idx"),
        ),
        migrations.AddIndex(
            model_name="vendorverificationrequest",
            index=models.Index(fields=["status"], name="vendors_vvr_status_idx"),
        ),
        migrations.AddIndex(
            model_name="vendorverificationrequest",
            index=models.Index(fields=["created_at"], name="vendors_vvr_created_at_idx"),
        ),
        # ------------------------------------------------------------------
        # VendorVerificationRequestAsset
        # ------------------------------------------------------------------
        migrations.CreateModel(
            name="VendorVerificationRequestAsset",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                (
                    "request",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="request_assets",
                        to="vendors.vendorverificationrequest",
                    ),
                ),
                (
                    "asset",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="vendor_request_assets",
                        to="assets.asset",
                    ),
                ),
                ("asset_id_snapshot", models.CharField(max_length=100)),
                ("asset_name_snapshot", models.CharField(max_length=300)),
                ("asset_location_snapshot", models.CharField(blank=True, max_length=500)),
                (
                    "response_status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("confirmed", "Confirmed Present"),
                            ("issue_reported", "Issue Reported"),
                        ],
                        db_index=True,
                        default="pending",
                        max_length=20,
                    ),
                ),
                ("response_notes", models.TextField(blank=True, null=True)),
                (
                    "observed_location",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="vendor_observations",
                        to="locations.locationnode",
                    ),
                ),
                ("responded_at", models.DateTimeField(blank=True, null=True)),
                (
                    "admin_decision",
                    models.CharField(
                        choices=[
                            ("pending_review", "Pending Review"),
                            ("approved", "Approved"),
                            ("correction_required", "Correction Required"),
                        ],
                        db_index=True,
                        default="pending_review",
                        max_length=20,
                    ),
                ),
            ],
            options={"db_table": "vendors_vendor_request_asset"},
        ),
        migrations.AlterUniqueTogether(
            name="vendorverificationrequestasset",
            unique_together={("request", "asset")},
        ),
        # ------------------------------------------------------------------
        # VendorRequestAssetPhoto
        # ------------------------------------------------------------------
        migrations.CreateModel(
            name="VendorRequestAssetPhoto",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                (
                    "request_asset",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="photos",
                        to="vendors.vendorverificationrequestasset",
                    ),
                ),
                ("image", models.ImageField(upload_to=vendors.models._asset_photo_upload_path)),
                ("uploaded_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"db_table": "vendors_request_asset_photo"},
        ),
    ]
