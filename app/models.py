from django.db import models
from django.contrib.auth.models import User


class DatabaseConnection(models.Model):
    DB_TYPES = [
        ('postgresql', 'PostgreSQL'),
        ('mysql', 'MySQL'),
        ('mssql', 'SQL Server'),
        ('sqlite', 'SQLite'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='databases')
    label = models.CharField(max_length=100)
    db_type = models.CharField(max_length=20, choices=DB_TYPES, default='postgresql')
    store_credentials = models.BooleanField(default=True)
    connection_string = models.TextField(blank=True)
    host = models.CharField(max_length=255, blank=True)
    port = models.CharField(max_length=10, blank=True)
    db_name = models.CharField(max_length=255, blank=True)
    db_user = models.CharField(max_length=255, blank=True)
    db_password = models.TextField(blank=True)
    use_ssl = models.BooleanField(default=False)
    schema_description = models.TextField(blank=True)
    fetched_schema = models.TextField(blank=True)
    schema_fetched_at = models.DateTimeField(null=True, blank=True)
    is_file_based = models.BooleanField(default=False)
    sqlite_path = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.label} ({self.user.email})"

    class Meta:
        ordering = ['label']
        unique_together = [['user', 'label']]


class QueryHistory(models.Model):
    database = models.ForeignKey(DatabaseConnection, on_delete=models.CASCADE, related_name='queries')
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    question = models.TextField()
    generated_sql = models.TextField(blank=True)
    nl_response = models.TextField(blank=True)
    error = models.TextField(blank=True)
    result_columns = models.JSONField(default=list, blank=True)
    result_rows    = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']


# ── LLM Configuration ──────────────────────────────────────────────────────────

class LLMProvider(models.Model):
    PROVIDER_CHOICES = [
        ('gemini',    'Google Gemini'),
        ('openai',    'OpenAI'),
        ('anthropic', 'Anthropic'),
        ('ollama',    'Ollama (local)'),
    ]
    user         = models.ForeignKey(User, on_delete=models.CASCADE, related_name='llm_providers')
    provider     = models.CharField(max_length=20, choices=PROVIDER_CHOICES)
    # For cloud providers — stored as plain text (encrypt in production)
    api_key      = models.TextField(blank=True)
    # For Ollama — base URL
    base_url     = models.CharField(max_length=255, blank=True, default='http://localhost:11434')
    created_at   = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [['user', 'provider']]
        ordering = ['provider']

    def __str__(self):
        return f"{self.get_provider_display()} ({self.user.email})"

    def masked_key(self):
        if not self.api_key:
            return ''
        return self.api_key[:6] + '••••••••' + self.api_key[-3:]


class LLMModel(models.Model):
    user         = models.ForeignKey(User, on_delete=models.CASCADE, related_name='llm_models')
    provider     = models.ForeignKey(LLMProvider, on_delete=models.CASCADE, related_name='models')
    model_id     = models.CharField(max_length=100)   # exact API name e.g. "gemini-2.0-flash"
    display_name = models.CharField(max_length=100)   # friendly label e.g. "Gemini 2.0 Flash"
    is_default   = models.BooleanField(default=False)
    created_at   = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [['user', 'provider', 'model_id']]
        ordering = ['display_name']

    def __str__(self):
        return f"{self.display_name} ({self.provider.get_provider_display()})"
