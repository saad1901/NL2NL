from django.contrib import admin
from django.contrib.auth.models import User
from django.utils.html import format_html, escape
from django.utils.safestring import mark_safe
from django.urls import reverse
from django.db.models import Count, Q
from django.utils import timezone

from .models import DatabaseConnection, QueryHistory, LLMProvider, LLMModel, DashboardChart


# ── Admin site customisation ───────────────────────────────────────────────────

admin.site.site_header  = "NL2SQL Administration"
admin.site.site_title   = "NL2SQL Admin"
admin.site.index_title  = "Dashboard"


# ── Helpers ────────────────────────────────────────────────────────────────────

def _truncate(text, length=80):
    if not text:
        return "—"
    text = str(text)
    return text if len(text) <= length else text[:length] + "…"


# ── QueryHistory inline (used inside DatabaseConnection) ──────────────────────

class QueryHistoryInline(admin.TabularInline):
    model          = QueryHistory
    extra          = 0
    can_delete     = True
    show_change_link = True
    fields         = ('created_at', 'question_short', 'has_error', 'row_count')
    readonly_fields = ('created_at', 'question_short', 'has_error', 'row_count')
    ordering       = ('-created_at',)
    max_num        = 20  # don't load 1000 rows in the inline

    def question_short(self, obj):
        return _truncate(obj.question, 80)
    question_short.short_description = "Question"

    def has_error(self, obj):
        if obj.error:
            return mark_safe('<span style="color:#ef4444">✗ Error</span>')
        return mark_safe('<span style="color:#22c55e">✓ OK</span>')
    has_error.short_description = "Status"

    def row_count(self, obj):
        n = len(obj.result_rows) if obj.result_rows else 0
        return f"{n} row{'s' if n != 1 else ''}"
    row_count.short_description = "Rows"


# ── LLMModel inline (used inside LLMProvider) ─────────────────────────────────

class LLMModelInline(admin.TabularInline):
    model           = LLMModel
    extra           = 0
    can_delete      = True
    fields          = ('display_name', 'model_id', 'is_default', 'created_at')
    readonly_fields = ('created_at',)


# ── DatabaseConnection ─────────────────────────────────────────────────────────

@admin.register(DatabaseConnection)
class DatabaseConnectionAdmin(admin.ModelAdmin):
    list_display   = ('label', 'user_email', 'db_type_badge', 'store_credentials',
                      'is_file_based', 'has_schema', 'query_count', 'created_at')
    list_filter    = ('db_type', 'store_credentials', 'is_file_based', 'created_at')
    search_fields  = ('label', 'user__email', 'user__first_name', 'db_name', 'host')
    readonly_fields = ('created_at', 'schema_fetched_at', 'schema_preview',
                       'query_count', 'user_link')
    ordering       = ('-created_at',)
    inlines        = [QueryHistoryInline]
    date_hierarchy = 'created_at'

    fieldsets = (
        ('Identity', {
            'fields': ('user_link', 'label', 'db_type', 'is_file_based', 'store_credentials')
        }),
        ('Connection', {
            'fields': ('connection_string', 'host', 'port', 'db_name', 'db_user',
                       'db_password', 'use_ssl', 'sqlite_path'),
            'classes': ('collapse',),
        }),
        ('Schema', {
            'fields': ('schema_description', 'schema_preview', 'schema_fetched_at'),
        }),
        ('Meta', {
            'fields': ('created_at', 'query_count'),
        }),
    )

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.select_related('user').annotate(_query_count=Count('queries'))

    def user_email(self, obj):
        url = reverse('admin:auth_user_change', args=[obj.user_id])
        return format_html('<a href="{}">{}</a>', url, obj.user.email)
    user_email.short_description = "User"
    user_email.admin_order_field = 'user__email'

    def user_link(self, obj):
        url = reverse('admin:auth_user_change', args=[obj.user_id])
        return format_html('<a href="{}">{}</a>', url, obj.user.get_full_name() or obj.user.email)
    user_link.short_description = "User"

    def db_type_badge(self, obj):
        colours = {
            'postgresql': '#3b82f6',
            'mysql':      '#f97316',
            'mssql':      '#ef4444',
            'sqlite':     '#22c55e',
        }
        c = colours.get(obj.db_type, '#6b7280')
        return format_html(
            '<span style="background:{};color:#fff;padding:2px 8px;border-radius:9999px;font-size:11px">{}</span>',
            c, obj.get_db_type_display()
        )
    db_type_badge.short_description = "Type"
    db_type_badge.admin_order_field = 'db_type'

    def has_schema(self, obj):
        if obj.fetched_schema:
            n = len([l for l in obj.fetched_schema.strip().splitlines() if l.strip()])
            return format_html('<span style="color:#22c55e">✓ {} tables</span>', n)
        return mark_safe('<span style="color:#6b7280">—</span>')
    has_schema.short_description = "Schema"

    def schema_preview(self, obj):
        if not obj.fetched_schema:
            return "Not fetched yet."
        lines = [l for l in obj.fetched_schema.strip().splitlines() if l.strip()]
        rows = ''.join(
            f'<tr><td style="padding:4px 12px;border-bottom:1px solid #374151;font-family:monospace;font-size:12px">{escape(l)}</td></tr>'
            for l in lines
        )
        return mark_safe(
            f'<table style="border-collapse:collapse;width:100%;background:#111827;border-radius:8px;overflow:hidden">'
            f'<thead><tr><th style="padding:6px 12px;background:#1f2937;text-align:left;font-size:11px;color:#9ca3af">TABLE (columns…)</th></tr></thead>'
            f'<tbody>{rows}</tbody></table>'
        )
    schema_preview.short_description = "Schema"

    def query_count(self, obj):
        count = getattr(obj, '_query_count', obj.queries.count())
        if count:
            url = (reverse('admin:app_queryhistory_changelist')
                   + f'?database__id__exact={obj.pk}')
            return format_html('<a href="{}">{} quer{}</a>', url, count,
                               'ies' if count != 1 else 'y')
        return "0 queries"
    query_count.short_description = "Queries"
    query_count.admin_order_field = '_query_count'


# ── QueryHistory ───────────────────────────────────────────────────────────────

@admin.register(QueryHistory)
class QueryHistoryAdmin(admin.ModelAdmin):
    list_display   = ('created_at', 'user_email', 'database_label', 'question_preview',
                      'status_badge', 'row_count', 'has_sql')
    list_filter    = ('created_at', 'database__db_type',
                      ('error', admin.EmptyFieldListFilter))
    search_fields  = ('question', 'generated_sql', 'nl_response',
                      'user__email', 'database__label')
    readonly_fields = ('created_at', 'user_link', 'database_link',
                       'question', 'generated_sql_block', 'nl_response_block',
                       'result_table', 'error_block', 'row_count')
    ordering       = ('-created_at',)
    date_hierarchy = 'created_at'
    list_per_page  = 30

    fieldsets = (
        ('Context', {
            'fields': ('created_at', 'user_link', 'database_link'),
        }),
        ('Question', {
            'fields': ('question',),
        }),
        ('Generated SQL', {
            'fields': ('generated_sql_block',),
        }),
        ('AI Response', {
            'fields': ('nl_response_block',),
        }),
        ('Result Data', {
            'fields': ('row_count', 'result_table'),
        }),
        ('Error', {
            'fields': ('error_block',),
            'classes': ('collapse',),
        }),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('user', 'database')

    # ── list columns ──────────────────────────────────────────────────────────

    def user_email(self, obj):
        url = reverse('admin:auth_user_change', args=[obj.user_id])
        return format_html('<a href="{}">{}</a>', url, obj.user.email)
    user_email.short_description = "User"
    user_email.admin_order_field = 'user__email'

    def database_label(self, obj):
        url = reverse('admin:app_databaseconnection_change', args=[obj.database_id])
        return format_html('<a href="{}">{}</a>', url, obj.database.label)
    database_label.short_description = "Database"
    database_label.admin_order_field = 'database__label'

    def question_preview(self, obj):
        return _truncate(obj.question, 90)
    question_preview.short_description = "Question"

    def status_badge(self, obj):
        if obj.error:
            return mark_safe(
                '<span style="background:#7f1d1d;color:#fca5a5;padding:2px 8px;'
                'border-radius:9999px;font-size:11px">✗ Error</span>'
            )
        if obj.result_rows:
            n = len(obj.result_rows)
            return format_html(
                '<span style="background:#14532d;color:#86efac;padding:2px 8px;'
                'border-radius:9999px;font-size:11px">✓ {} row{}</span>',
                n, 's' if n != 1 else ''
            )
        return mark_safe(
            '<span style="background:#1e3a5f;color:#93c5fd;padding:2px 8px;'
            'border-radius:9999px;font-size:11px">✓ No rows</span>'
        )
    status_badge.short_description = "Status"

    def row_count(self, obj):
        n = len(obj.result_rows) if obj.result_rows else 0
        return f"{n} row{'s' if n != 1 else ''}"
    row_count.short_description = "Rows returned"

    def has_sql(self, obj):
        return mark_safe('<span style="color:#22c55e">✓</span>') if obj.generated_sql \
            else mark_safe('<span style="color:#6b7280">—</span>')
    has_sql.short_description = "SQL"

    # ── detail view fields ────────────────────────────────────────────────────

    def user_link(self, obj):
        url = reverse('admin:auth_user_change', args=[obj.user_id])
        return format_html('<a href="{}">{}</a>', url,
                           obj.user.get_full_name() or obj.user.email)
    user_link.short_description = "User"

    def database_link(self, obj):
        url = reverse('admin:app_databaseconnection_change', args=[obj.database_id])
        return format_html('<a href="{}">{} ({})</a>', url,
                           obj.database.label, obj.database.get_db_type_display())
    database_link.short_description = "Database"

    def generated_sql_block(self, obj):
        if not obj.generated_sql:
            return "—"
        return mark_safe(
            f'<pre style="background:#0d1117;color:#e5e7eb;padding:12px 16px;'
            f'border-radius:8px;font-size:12px;overflow-x:auto;white-space:pre-wrap;'
            f'border:1px solid #374151;max-height:300px;overflow-y:auto">'
            f'{escape(obj.generated_sql)}</pre>'
        )
    generated_sql_block.short_description = "Generated SQL"

    def nl_response_block(self, obj):
        if not obj.nl_response:
            return "—"
        return mark_safe(
            f'<div style="background:#0d1117;color:#e5e7eb;padding:12px 16px;'
            f'border-radius:8px;font-size:13px;line-height:1.6;white-space:pre-wrap;'
            f'border:1px solid #374151;max-height:400px;overflow-y:auto">'
            f'{escape(obj.nl_response)}</div>'
        )
    nl_response_block.short_description = "AI Response"

    def error_block(self, obj):
        if not obj.error:
            return "—"
        return mark_safe(
            f'<div style="background:#450a0a;color:#fca5a5;padding:12px 16px;'
            f'border-radius:8px;font-size:12px;white-space:pre-wrap;'
            f'border:1px solid #7f1d1d">'
            f'{escape(obj.error)}</div>'
        )
    error_block.short_description = "Error"

    def result_table(self, obj):
        if not obj.result_rows or not obj.result_columns:
            return "No result data."
        cols = obj.result_columns
        rows = obj.result_rows[:100]  # cap at 100 for admin display

        header = ''.join(
            f'<th style="padding:6px 12px;background:#1f2937;text-align:left;'
            f'font-size:11px;color:#9ca3af;text-transform:uppercase;'
            f'letter-spacing:.05em;white-space:nowrap">{escape(str(c))}</th>'
            for c in cols
        )
        body = ''
        for i, row in enumerate(rows):
            bg = '#111827' if i % 2 == 0 else '#1a2030'
            cells = ''.join(
                f'<td style="padding:5px 12px;font-size:12px;color:#e5e7eb;'
                f'font-family:monospace;white-space:nowrap">{escape(str(v))}</td>'
                for v in row
            )
            body += f'<tr style="background:{bg}">{cells}</tr>'

        suffix = ''
        if len(obj.result_rows) > 100:
            suffix = (f'<tr><td colspan="{len(cols)}" style="padding:6px 12px;'
                      f'color:#6b7280;font-size:11px">…and '
                      f'{len(obj.result_rows) - 100} more rows</td></tr>')

        return mark_safe(
            f'<div style="overflow-x:auto;max-height:400px;overflow-y:auto;'
            f'border-radius:8px;border:1px solid #374151">'
            f'<table style="border-collapse:collapse;min-width:100%">'
            f'<thead><tr>{header}</tr></thead>'
            f'<tbody>{body}{suffix}</tbody>'
            f'</table></div>'
        )
    result_table.short_description = "Result Data"


# ── LLMProvider ────────────────────────────────────────────────────────────────

@admin.register(LLMProvider)
class LLMProviderAdmin(admin.ModelAdmin):
    list_display  = ('provider_badge', 'user_email', 'masked_key_display',
                     'base_url', 'model_count', 'created_at')
    list_filter   = ('provider', 'created_at')
    search_fields = ('user__email', 'user__first_name', 'base_url')
    readonly_fields = ('created_at', 'user_link', 'masked_key_display')
    ordering      = ('provider', 'user__email')
    inlines       = [LLMModelInline]

    fieldsets = (
        ('Identity', {
            'fields': ('user_link', 'provider'),
        }),
        ('Credentials', {
            'fields': ('masked_key_display', 'base_url'),
        }),
        ('Meta', {
            'fields': ('created_at',),
        }),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('user').annotate(
            _model_count=Count('models')
        )

    def user_email(self, obj):
        url = reverse('admin:auth_user_change', args=[obj.user_id])
        return format_html('<a href="{}">{}</a>', url, obj.user.email)
    user_email.short_description = "User"
    user_email.admin_order_field = 'user__email'

    def user_link(self, obj):
        url = reverse('admin:auth_user_change', args=[obj.user_id])
        return format_html('<a href="{}">{}</a>', url, obj.user.email)
    user_link.short_description = "User"

    PROVIDER_COLOURS = {
        'gemini':     '#1a73e8',
        'openai':     '#10a37f',
        'anthropic':  '#d97706',
        'openrouter': '#7c3aed',
        'ollama':     '#374151',
    }

    def provider_badge(self, obj):
        c = self.PROVIDER_COLOURS.get(obj.provider, '#6b7280')
        return format_html(
            '<span style="background:{};color:#fff;padding:2px 8px;'
            'border-radius:9999px;font-size:11px">{}</span>',
            c, obj.get_provider_display()
        )
    provider_badge.short_description = "Provider"
    provider_badge.admin_order_field = 'provider'

    def masked_key_display(self, obj):
        return obj.masked_key() or mark_safe('<span style="color:#6b7280">—</span>')
    masked_key_display.short_description = "API Key"

    def model_count(self, obj):
        count = getattr(obj, '_model_count', obj.models.count())
        return f"{count} model{'s' if count != 1 else ''}"
    model_count.short_description = "Models"
    model_count.admin_order_field = '_model_count'


# ── LLMModel ───────────────────────────────────────────────────────────────────

@admin.register(LLMModel)
class LLMModelAdmin(admin.ModelAdmin):
    list_display  = ('display_name', 'model_id', 'provider_badge',
                     'user_email', 'is_default', 'created_at')
    list_filter   = ('provider__provider', 'is_default', 'created_at')
    search_fields = ('display_name', 'model_id', 'user__email')
    readonly_fields = ('created_at', 'user_link')
    ordering      = ('display_name',)

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('user', 'provider')

    def user_email(self, obj):
        url = reverse('admin:auth_user_change', args=[obj.user_id])
        return format_html('<a href="{}">{}</a>', url, obj.user.email)
    user_email.short_description = "User"
    user_email.admin_order_field = 'user__email'

    def user_link(self, obj):
        url = reverse('admin:auth_user_change', args=[obj.user_id])
        return format_html('<a href="{}">{}</a>', url, obj.user.email)
    user_link.short_description = "User"

    def provider_badge(self, obj):
        colours = LLMProviderAdmin.PROVIDER_COLOURS
        c = colours.get(obj.provider.provider, '#6b7280')
        return format_html(
            '<span style="background:{};color:#fff;padding:2px 8px;'
            'border-radius:9999px;font-size:11px">{}</span>',
            c, obj.provider.get_provider_display()
        )
    provider_badge.short_description = "Provider"


# ── DashboardChart ─────────────────────────────────────────────────────────────

@admin.register(DashboardChart)
class DashboardChartAdmin(admin.ModelAdmin):
    list_display  = ('title', 'chart_type_badge', 'user_email',
                     'database_label', 'position', 'created_at')
    list_filter   = ('chart_type', 'created_at')
    search_fields = ('title', 'question', 'sql', 'user__email', 'database__label')
    readonly_fields = ('created_at', 'user_link', 'database_link',
                       'sql_block', 'question')
    ordering      = ('database', 'position', 'created_at')

    fieldsets = (
        ('Identity', {
            'fields': ('user_link', 'database_link', 'title', 'chart_type', 'position'),
        }),
        ('Content', {
            'fields': ('question', 'sql_block'),
        }),
        ('Meta', {
            'fields': ('created_at',),
        }),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('user', 'database')

    def user_email(self, obj):
        url = reverse('admin:auth_user_change', args=[obj.user_id])
        return format_html('<a href="{}">{}</a>', url, obj.user.email)
    user_email.short_description = "User"

    def database_label(self, obj):
        url = reverse('admin:app_databaseconnection_change', args=[obj.database_id])
        return format_html('<a href="{}">{}</a>', url, obj.database.label)
    database_label.short_description = "Database"

    def user_link(self, obj):
        url = reverse('admin:auth_user_change', args=[obj.user_id])
        return format_html('<a href="{}">{}</a>', url, obj.user.email)
    user_link.short_description = "User"

    def database_link(self, obj):
        url = reverse('admin:app_databaseconnection_change', args=[obj.database_id])
        return format_html('<a href="{}">{}</a>', url, obj.database.label)
    database_link.short_description = "Database"

    CHART_COLOURS = {
        'bar': '#6366f1', 'line': '#22c55e', 'pie': '#ec4899',
        'scatter': '#f97316', 'radar': '#a855f7', 'funnel': '#06b6d4',
    }

    def chart_type_badge(self, obj):
        c = self.CHART_COLOURS.get(obj.chart_type, '#6b7280')
        return format_html(
            '<span style="background:{};color:#fff;padding:2px 8px;'
            'border-radius:9999px;font-size:11px">{}</span>',
            c, obj.chart_type
        )
    chart_type_badge.short_description = "Type"
    chart_type_badge.admin_order_field = 'chart_type'

    def sql_block(self, obj):
        if not obj.sql:
            return "—"
        return mark_safe(
            f'<pre style="background:#0d1117;color:#e5e7eb;padding:12px 16px;'
            f'border-radius:8px;font-size:12px;overflow-x:auto;white-space:pre-wrap;'
            f'border:1px solid #374151">{escape(obj.sql)}</pre>'
        )
    sql_block.short_description = "SQL"
