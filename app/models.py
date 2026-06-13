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

    # If store_credentials=True, we save the connection details
    store_credentials = models.BooleanField(default=True)

    # Connection fields — only populated when store_credentials=True
    connection_string = models.TextField(blank=True)   # OR individual fields below
    host = models.CharField(max_length=255, blank=True)
    port = models.CharField(max_length=10, blank=True)
    db_name = models.CharField(max_length=255, blank=True)
    db_user = models.CharField(max_length=255, blank=True)
    db_password = models.TextField(blank=True)         # store encrypted in production
    use_ssl = models.BooleanField(default=False)

    schema_description = models.TextField(blank=True)
    # Auto-fetched schema in AI-ready format: "table (col type, col type, ...)\n..."
    fetched_schema = models.TextField(blank=True)
    schema_fetched_at = models.DateTimeField(null=True, blank=True)
    # File-based source (CSV / Excel loaded into a per-user SQLite)
    is_file_based = models.BooleanField(default=False)
    sqlite_path = models.TextField(blank=True)   # absolute path to the SQLite file
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
    # Persisted query results so they survive page refresh
    result_columns = models.JSONField(default=list, blank=True)
    result_rows    = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
