import secrets
import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def _generate_public_token():
    return secrets.token_urlsafe(32)


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("accounts", "0001_initial"),
        ("assets", "0001_initial"),
        ("locations", "0001_initial"),
    ]

    operations = [
        # ---------------------------------------------------------------
        # VerificationCycle
        # ---------------------------------------------------------------
        migrations.CreateModel(
            name="VerificationCycle",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("name", models.CharField(max_length=200)),
                ("code", models.CharField(max_length=100, unique=True)),
                ("description", models.TextField(blank=True, null=True)),
                ("start_date", models.DateField()),
                ("end_date", models.DateField()),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("draft", "Draft"),
                            ("active", "Active"),
                            ("closed", "Closed"),
                        ],
                        db_index=True,
                        default="draft",
                        max_length=20,
                    ),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="created_verification_cycles",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "verification_cycle",
                "ordering": ("-start_date",),
            },
        ),
        # ---------------------------------------------------------------
        # VerificationRequest
        # ---------------------------------------------------------------
        migrations.CreateModel(
            name="VerificationRequest",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "cycle",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="requests",
                        to="verification.verificationcycle",
                    ),
                ),
                (
                    "employee",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="verification_requests",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "requested_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="sent_verification_requests",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "location_scope",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="verification_requests",
                        to="locations.locationnode",
                    ),
                ),
                (
                    "public_token",
                    models.CharField(
                        db_index=True,
                        default=_generate_public_token,
                        max_length=200,
                        unique=True,
                    ),
                ),
                (
                    "reference_code",
                    models.CharField(max_length=100, unique=True),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("opened", "Opened"),
                            ("otp_verified", "OTP Verified"),
                            ("submitted", "Submitted"),
                            ("expired", "Expired"),
                            ("cancelled", "Cancelled"),
                        ],
                        db_index=True,
                        default="pending",
                        max_length=20,
                    ),
                ),
                ("sent_at", models.DateTimeField(blank=True, null=True)),
                ("opened_at", models.DateTimeField(blank=True, null=True)),
                ("otp_verified_at", models.DateTimeField(blank=True, null=True)),
                ("submitted_at", models.DateTimeField(blank=True, null=True)),
                ("expires_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "verification_request",
            },
        ),
        migrations.AddIndex(
            model_name="verificationrequest",
            index=models.Index(
                fields=["cycle", "employee"], name="verif_req_cycle_emp_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="verificationrequest",
            index=models.Index(
                fields=["employee"], name="verif_req_employee_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="verificationrequest",
            index=models.Index(fields=["status"], name="verif_req_status_idx"),
        ),
        migrations.AddIndex(
            model_name="verificationrequest",
            index=models.Index(
                fields=["expires_at"], name="verif_req_expires_at_idx"
            ),
        ),
        # ---------------------------------------------------------------
        # VerificationRequestAsset
        # ---------------------------------------------------------------
        migrations.CreateModel(
            name="VerificationRequestAsset",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "verification_request",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="request_assets",
                        to="verification.verificationrequest",
                    ),
                ),
                (
                    "asset",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="verification_snapshots",
                        to="assets.asset",
                    ),
                ),
                ("snapshot_asset_id", models.CharField(max_length=100)),
                ("snapshot_name", models.CharField(max_length=300)),
                (
                    "snapshot_serial_number",
                    models.CharField(blank=True, max_length=200, null=True),
                ),
                (
                    "snapshot_category_name",
                    models.CharField(blank=True, max_length=200, null=True),
                ),
                (
                    "snapshot_location_name",
                    models.CharField(blank=True, max_length=300, null=True),
                ),
                ("snapshot_payload", models.JSONField(blank=True, default=dict)),
                ("sort_order", models.PositiveIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "db_table": "verification_request_asset",
                "ordering": ("sort_order",),
            },
        ),
        migrations.AlterUniqueTogether(
            name="verificationrequestasset",
            unique_together={("verification_request", "asset")},
        ),
        migrations.AddIndex(
            model_name="verificationrequestasset",
            index=models.Index(
                fields=["verification_request"],
                name="verif_rqa_request_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="verificationrequestasset",
            index=models.Index(
                fields=["asset"], name="verif_rqa_asset_idx"
            ),
        ),
        # ---------------------------------------------------------------
        # AssetVerificationResponse
        # ---------------------------------------------------------------
        migrations.CreateModel(
            name="AssetVerificationResponse",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "request_asset",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="response",
                        to="verification.verificationrequestasset",
                    ),
                ),
                (
                    "response",
                    models.CharField(
                        choices=[
                            ("verified", "Verified"),
                            ("issue_reported", "Issue Reported"),
                        ],
                        db_index=True,
                        max_length=20,
                    ),
                ),
                ("remarks", models.TextField(blank=True, null=True)),
                ("responded_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "verification_asset_response",
            },
        ),
        # ---------------------------------------------------------------
        # VerificationIssue
        # ---------------------------------------------------------------
        migrations.CreateModel(
            name="VerificationIssue",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "asset_response",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="issue",
                        to="verification.assetverificationresponse",
                    ),
                ),
                (
                    "issue_type",
                    models.CharField(
                        choices=[
                            ("missing", "Missing"),
                            ("damaged", "Damaged"),
                            ("wrong_serial", "Wrong Serial Number"),
                            ("not_in_possession", "Not In Possession"),
                            ("other", "Other"),
                        ],
                        max_length=30,
                    ),
                ),
                ("description", models.TextField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "verification_issue",
            },
        ),
        # ---------------------------------------------------------------
        # VerificationDeclaration
        # ---------------------------------------------------------------
        migrations.CreateModel(
            name="VerificationDeclaration",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "verification_request",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="declaration",
                        to="verification.verificationrequest",
                    ),
                ),
                (
                    "consent_text_version",
                    models.CharField(blank=True, max_length=50, null=True),
                ),
                ("declared_by_name", models.CharField(max_length=200)),
                ("declared_by_email", models.EmailField(max_length=254)),
                ("consented_at", models.DateTimeField()),
                (
                    "ip_address",
                    models.GenericIPAddressField(blank=True, null=True),
                ),
                ("user_agent", models.TextField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "verification_declaration",
            },
        ),
    ]
