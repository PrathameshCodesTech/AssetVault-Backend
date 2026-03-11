import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("accounts", "0001_initial"),
        ("locations", "0001_initial"),
    ]

    operations = [
        # ---------------------------------------------------------------
        # Lookup / reference models
        # ---------------------------------------------------------------
        migrations.CreateModel(
            name="BusinessEntity",
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
                ("code", models.CharField(max_length=50, unique=True)),
                ("name", models.CharField(max_length=200)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "assets_business_entity",
                "ordering": ("name",),
            },
        ),
        migrations.CreateModel(
            name="AssetCategory",
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
                ("code", models.CharField(max_length=50, unique=True)),
                ("name", models.CharField(max_length=200)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "assets_asset_category",
                "ordering": ("name",),
                "verbose_name": "asset category",
                "verbose_name_plural": "asset categories",
            },
        ),
        migrations.CreateModel(
            name="AssetSubType",
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
                    "category",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="sub_types",
                        to="assets.assetcategory",
                    ),
                ),
                ("code", models.CharField(max_length=50)),
                ("name", models.CharField(max_length=200)),
                ("is_active", models.BooleanField(default=True)),
            ],
            options={
                "db_table": "assets_asset_sub_type",
                "ordering": ("category", "name"),
            },
        ),
        migrations.AlterUniqueTogether(
            name="assetsubtype",
            unique_together={("category", "code")},
        ),
        migrations.CreateModel(
            name="Supplier",
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
                    "code",
                    models.CharField(
                        blank=True, max_length=50, null=True, unique=True
                    ),
                ),
                ("name", models.CharField(max_length=300)),
                ("email", models.EmailField(blank=True, max_length=254, null=True)),
                ("phone", models.CharField(blank=True, max_length=30, null=True)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "assets_supplier",
                "ordering": ("name",),
            },
        ),
        migrations.CreateModel(
            name="CostCenter",
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
                ("code", models.CharField(max_length=50, unique=True)),
                ("name", models.CharField(max_length=200)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "assets_cost_center",
                "ordering": ("code",),
            },
        ),
        # ---------------------------------------------------------------
        # Main Asset model
        # ---------------------------------------------------------------
        migrations.CreateModel(
            name="Asset",
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
                ("asset_id", models.CharField(max_length=100, unique=True)),
                (
                    "qr_uid",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, unique=True
                    ),
                ),
                (
                    "tag_number",
                    models.CharField(
                        blank=True, max_length=100, null=True, unique=True
                    ),
                ),
                (
                    "serial_number",
                    models.CharField(
                        blank=True, db_index=True, max_length=200, null=True
                    ),
                ),
                (
                    "business_entity",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="assets",
                        to="assets.businessentity",
                    ),
                ),
                (
                    "category",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="assets",
                        to="assets.assetcategory",
                    ),
                ),
                (
                    "sub_type",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="assets",
                        to="assets.assetsubtype",
                    ),
                ),
                (
                    "asset_class",
                    models.CharField(blank=True, max_length=100, null=True),
                ),
                ("name", models.CharField(max_length=300)),
                ("description", models.TextField(blank=True, null=True)),
                (
                    "current_location",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="assets",
                        to="locations.locationnode",
                    ),
                ),
                (
                    "sub_location_text",
                    models.CharField(blank=True, max_length=300, null=True),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("active", "Active"),
                            ("in_transit", "In Transit"),
                            ("disposed", "Disposed"),
                            ("missing", "Missing"),
                            ("pending_verification", "Pending Verification"),
                        ],
                        db_index=True,
                        default="active",
                        max_length=30,
                    ),
                ),
                (
                    "reconciliation_status",
                    models.CharField(
                        choices=[
                            ("verified", "Verified"),
                            ("pending", "Pending"),
                            ("discrepancy", "Discrepancy"),
                        ],
                        db_index=True,
                        default="pending",
                        max_length=20,
                    ),
                ),
                (
                    "assigned_to",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="assigned_assets",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "currency_code",
                    models.CharField(blank=True, max_length=10, null=True),
                ),
                (
                    "purchase_value",
                    models.DecimalField(
                        blank=True, decimal_places=2, max_digits=20, null=True
                    ),
                ),
                ("capitalized_on", models.DateField(blank=True, null=True)),
                ("is_wfh_asset", models.BooleanField(default=False)),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="created_assets",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "updated_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="updated_assets",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "assets_asset",
            },
        ),
        migrations.AddIndex(
            model_name="asset",
            index=models.Index(fields=["asset_id"], name="assets_a_asset_id_idx"),
        ),
        migrations.AddIndex(
            model_name="asset",
            index=models.Index(
                fields=["serial_number"], name="assets_a_serial_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="asset",
            index=models.Index(
                fields=["tag_number"], name="assets_a_tag_number_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="asset",
            index=models.Index(
                fields=["current_location"], name="assets_a_cur_loc_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="asset",
            index=models.Index(
                fields=["assigned_to"], name="assets_a_assigned_to_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="asset",
            index=models.Index(fields=["status"], name="assets_a_status_idx"),
        ),
        migrations.AddIndex(
            model_name="asset",
            index=models.Index(
                fields=["reconciliation_status"], name="assets_a_recon_status_idx"
            ),
        ),
        # ---------------------------------------------------------------
        # Asset detail tables
        # ---------------------------------------------------------------
        migrations.CreateModel(
            name="AssetFinancialDetail",
            fields=[
                (
                    "asset",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        primary_key=True,
                        related_name="financial_detail",
                        serialize=False,
                        to="assets.asset",
                    ),
                ),
                (
                    "sub_number",
                    models.CharField(blank=True, max_length=50, null=True),
                ),
                (
                    "cost_center",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="asset_financial_details",
                        to="assets.costcenter",
                    ),
                ),
                (
                    "internal_order",
                    models.CharField(blank=True, max_length=100, null=True),
                ),
                (
                    "supplier",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="asset_financial_details",
                        to="assets.supplier",
                    ),
                ),
                (
                    "useful_life",
                    models.CharField(blank=True, max_length=50, null=True),
                ),
                (
                    "useful_life_in_periods",
                    models.PositiveSmallIntegerField(blank=True, null=True),
                ),
                (
                    "apc_fy_start",
                    models.DecimalField(
                        blank=True, decimal_places=2, max_digits=20, null=True
                    ),
                ),
                (
                    "acquisition_amount",
                    models.DecimalField(
                        blank=True, decimal_places=2, max_digits=20, null=True
                    ),
                ),
                (
                    "retirement_amount",
                    models.DecimalField(
                        blank=True, decimal_places=2, max_digits=20, null=True
                    ),
                ),
                (
                    "transfer_amount",
                    models.DecimalField(
                        blank=True, decimal_places=2, max_digits=20, null=True
                    ),
                ),
                (
                    "post_capitalization_amount",
                    models.DecimalField(
                        blank=True, decimal_places=2, max_digits=20, null=True
                    ),
                ),
                (
                    "current_apc_amount",
                    models.DecimalField(
                        blank=True, decimal_places=2, max_digits=20, null=True
                    ),
                ),
                (
                    "dep_fy_start",
                    models.DecimalField(
                        blank=True, decimal_places=2, max_digits=20, null=True
                    ),
                ),
                (
                    "dep_for_year",
                    models.DecimalField(
                        blank=True, decimal_places=2, max_digits=20, null=True
                    ),
                ),
                (
                    "dep_retirement_amount",
                    models.DecimalField(
                        blank=True, decimal_places=2, max_digits=20, null=True
                    ),
                ),
                (
                    "dep_transfer_amount",
                    models.DecimalField(
                        blank=True, decimal_places=2, max_digits=20, null=True
                    ),
                ),
                (
                    "write_ups_amount",
                    models.DecimalField(
                        blank=True, decimal_places=2, max_digits=20, null=True
                    ),
                ),
                (
                    "dep_post_cap_amount",
                    models.DecimalField(
                        blank=True, decimal_places=2, max_digits=20, null=True
                    ),
                ),
                (
                    "accumulated_depreciation_amount",
                    models.DecimalField(
                        blank=True, decimal_places=2, max_digits=20, null=True
                    ),
                ),
                (
                    "book_value_fy_start",
                    models.DecimalField(
                        blank=True, decimal_places=2, max_digits=20, null=True
                    ),
                ),
                (
                    "current_book_value",
                    models.DecimalField(
                        blank=True, decimal_places=2, max_digits=20, null=True
                    ),
                ),
                ("deactivation_on", models.DateField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "assets_asset_financial_detail",
            },
        ),
        migrations.CreateModel(
            name="AssetWFHDetail",
            fields=[
                (
                    "asset",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        primary_key=True,
                        related_name="wfh_detail",
                        serialize=False,
                        to="assets.asset",
                    ),
                ),
                (
                    "wfh_uid",
                    models.CharField(
                        blank=True, max_length=100, null=True, unique=True
                    ),
                ),
                (
                    "user_name",
                    models.CharField(blank=True, max_length=200, null=True),
                ),
                (
                    "user_email",
                    models.EmailField(blank=True, max_length=254, null=True),
                ),
                (
                    "wfh_location_text",
                    models.CharField(blank=True, max_length=500, null=True),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "assets_asset_wfh_detail",
            },
        ),
        # ---------------------------------------------------------------
        # Asset images
        # ---------------------------------------------------------------
        migrations.CreateModel(
            name="AssetImage",
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
                    "asset",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="images",
                        to="assets.asset",
                    ),
                ),
                ("image", models.ImageField(upload_to="")),
                (
                    "image_type",
                    models.CharField(
                        blank=True,
                        choices=[
                            ("primary", "Primary"),
                            ("damage", "Damage"),
                            ("receipt", "Receipt"),
                            ("other", "Other"),
                        ],
                        max_length=20,
                        null=True,
                    ),
                ),
                ("is_primary", models.BooleanField(default=False)),
                (
                    "uploaded_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="uploaded_asset_images",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "db_table": "assets_asset_image",
            },
        ),
        # ---------------------------------------------------------------
        # Assignment history
        # ---------------------------------------------------------------
        migrations.CreateModel(
            name="AssetAssignment",
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
                    "asset",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="assignments",
                        to="assets.asset",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="asset_assignments",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "assigned_location",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="asset_assignments",
                        to="locations.locationnode",
                    ),
                ),
                (
                    "assigned_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="assignments_made",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                ("start_at", models.DateTimeField()),
                ("end_at", models.DateTimeField(blank=True, null=True)),
                ("note", models.TextField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "assets_asset_assignment",
            },
        ),
        migrations.AddIndex(
            model_name="assetassignment",
            index=models.Index(fields=["asset"], name="assets_aa_asset_idx"),
        ),
        migrations.AddIndex(
            model_name="assetassignment",
            index=models.Index(fields=["user"], name="assets_aa_user_idx"),
        ),
        migrations.AddIndex(
            model_name="assetassignment",
            index=models.Index(fields=["start_at"], name="assets_aa_start_at_idx"),
        ),
        # ---------------------------------------------------------------
        # Asset event / audit timeline
        # ---------------------------------------------------------------
        migrations.CreateModel(
            name="AssetEvent",
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
                    "asset",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="events",
                        to="assets.asset",
                    ),
                ),
                (
                    "event_type",
                    models.CharField(
                        choices=[
                            ("registered", "Registered"),
                            ("moved", "Moved"),
                            ("reassigned", "Reassigned"),
                            ("verified", "Verified"),
                            ("updated", "Updated"),
                            ("disposed", "Disposed"),
                        ],
                        db_index=True,
                        max_length=30,
                    ),
                ),
                (
                    "actor",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="asset_events",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "from_location",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="asset_events_from",
                        to="locations.locationnode",
                    ),
                ),
                (
                    "to_location",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="asset_events_to",
                        to="locations.locationnode",
                    ),
                ),
                ("description", models.TextField()),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "db_table": "assets_asset_event",
                "ordering": ("-created_at",),
            },
        ),
        migrations.AddIndex(
            model_name="assetevent",
            index=models.Index(fields=["asset"], name="assets_ae_asset_idx"),
        ),
        migrations.AddIndex(
            model_name="assetevent",
            index=models.Index(
                fields=["event_type"], name="assets_ae_event_type_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="assetevent",
            index=models.Index(
                fields=["created_at"], name="assets_ae_created_at_idx"
            ),
        ),
        # ---------------------------------------------------------------
        # Bulk import
        # ---------------------------------------------------------------
        migrations.CreateModel(
            name="AssetImportJob",
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
                    "uploaded_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="asset_import_jobs",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                ("source_file", models.FileField(upload_to="imports/assets/")),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("uploaded", "Uploaded"),
                            ("validating", "Validating"),
                            ("processed", "Processed"),
                            ("failed", "Failed"),
                        ],
                        db_index=True,
                        default="uploaded",
                        max_length=20,
                    ),
                ),
                ("total_rows", models.PositiveIntegerField(default=0)),
                ("success_rows", models.PositiveIntegerField(default=0)),
                ("failed_rows", models.PositiveIntegerField(default=0)),
                ("started_at", models.DateTimeField(blank=True, null=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "assets_import_job",
                "ordering": ("-created_at",),
            },
        ),
        migrations.CreateModel(
            name="AssetImportRow",
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
                    "job",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="rows",
                        to="assets.assetimportjob",
                    ),
                ),
                ("row_number", models.PositiveIntegerField()),
                ("raw_data", models.JSONField(blank=True, default=dict)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("valid", "Valid"),
                            ("invalid", "Invalid"),
                            ("imported", "Imported"),
                            ("skipped", "Skipped"),
                        ],
                        db_index=True,
                        default="pending",
                        max_length=20,
                    ),
                ),
                ("error_message", models.TextField(blank=True, null=True)),
                (
                    "asset",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="import_rows",
                        to="assets.asset",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "assets_import_row",
            },
        ),
        migrations.AlterUniqueTogether(
            name="assetimportrow",
            unique_together={("job", "row_number")},
        ),
        migrations.AddIndex(
            model_name="assetimportrow",
            index=models.Index(fields=["job"], name="assets_air_job_idx"),
        ),
        migrations.AddIndex(
            model_name="assetimportrow",
            index=models.Index(fields=["status"], name="assets_air_status_idx"),
        ),
    ]
