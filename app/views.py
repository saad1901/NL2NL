from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.contrib import messages
from django.http import JsonResponse, StreamingHttpResponse
from django.views.decorators.http import require_POST, require_http_methods
from django.utils import timezone
from django.conf import settings
import json
import logging
import os
import sqlite3

logger = logging.getLogger('app.views')

from .models import DatabaseConnection, QueryHistory, LLMProvider, LLMModel, DashboardChart
from .aiTools import fetch_schema
from .aiView import run_nl_query


# ── Auth ──────────────────────────────────────────────────────────────────────

def login_view(request):
    if request.user.is_authenticated:
        return redirect('/dashboard/')
    if request.method == 'POST':
        email = request.POST.get('email', '').strip()
        password = request.POST.get('password', '')
        try:
            username = User.objects.get(email=email).username
        except User.DoesNotExist:
            username = email
        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            return redirect('/dashboard/')
        messages.error(request, 'Invalid email or password.')
    return render(request, 'login.html')


def register_view(request):
    if request.user.is_authenticated:
        return redirect('/dashboard/')
    if request.method == 'POST':
        first_name = request.POST.get('first_name', '').strip()
        last_name  = request.POST.get('last_name', '').strip()
        email      = request.POST.get('email', '').strip()
        password   = request.POST.get('password', '')
        password2  = request.POST.get('password2', '')

        if not all([first_name, email, password]):
            messages.error(request, 'Please fill in all required fields.')
        elif password != password2:
            messages.error(request, 'Passwords do not match.')
        elif len(password) < 8:
            messages.error(request, 'Password must be at least 8 characters.')
        elif User.objects.filter(email=email).exists():
            messages.error(request, 'An account with this email already exists.')
        else:
            user = User.objects.create_user(
                username=email, email=email, password=password,
                first_name=first_name, last_name=last_name,
            )
            login(request, user)
            return redirect('/dashboard/')
    return render(request, 'register.html')


def logout_view(request):
    logout(request)
    return redirect('/login/')


# ── Dashboard / Chat ───────────────────────────────────────────────────────────

def dashboard_view(request):
    if not request.user.is_authenticated:
        return redirect('/login/')
    dbs = DatabaseConnection.objects.filter(user=request.user)
    if dbs.exists():
        return redirect(f'/chat/{dbs.first().id}/')
    return render(request, 'dashboard_empty.html', {'user': request.user})


def chat_view(request, db_id):
    if not request.user.is_authenticated:
        return redirect('/login/')
    db = get_object_or_404(DatabaseConnection, id=db_id, user=request.user)
    all_dbs = DatabaseConnection.objects.filter(user=request.user)
    history = QueryHistory.objects.filter(database=db, user=request.user).order_by('created_at')
    return render(request, 'chat.html', {
        'user': request.user,
        'active_db': db,
        'all_dbs': all_dbs,
        'history': history,
    })


@require_POST
def ask_view(request, db_id):
    """
    SSE streaming endpoint.
    Emits server-sent events as the pipeline progresses, then a final
    'result' event with the full JSON payload.

    Event types:
      status  — {"step": "thinking"|"generating"|"querying"|"reading"|"summarising", "detail": "..."}
      result  — {"id", "sql", "nl_response", "columns", "rows", "error", "created_at"}
      error   — {"message": "..."}
    """
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Unauthenticated'}, status=401)

    db = get_object_or_404(DatabaseConnection, id=db_id, user=request.user)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid request body.'}, status=400)

    question = data.get('question', '').strip()
    if not question:
        return JsonResponse({'error': 'Empty question.'}, status=400)

    # ── Resolve credentials for label-only databases ──────────────────────────
    if not db.store_credentials:
        session_creds = data.get('credentials', {})
        if not session_creds:
            return JsonResponse(
                {'error': 'no_credentials',
                 'message': 'This database requires credentials. Please enter them above.'},
                status=400
            )
        db.connection_string = session_creds.get('connection_string', '')
        db.host        = session_creds.get('host', '')
        db.port        = session_creds.get('port', '')
        db.db_name     = session_creds.get('db_name', '')
        db.db_user     = session_creds.get('db_user', '')
        db.db_password = session_creds.get('db_password', '')
        db.use_ssl     = session_creds.get('use_ssl', False)
        if not db.fetched_schema:
            fetch_schema(db)

    def event_stream():
        import queue, threading

        # Resolve LLM model from user's settings
        llm_model = None
        model_id = data.get('model_id')
        if model_id:
            try:
                llm_model = LLMModel.objects.select_related('provider').get(
                    id=model_id, user=request.user
                )
            except LLMModel.DoesNotExist:
                pass
        # Fallback: use user's default model
        if not llm_model:
            llm_model = LLMModel.objects.filter(
                user=request.user, is_default=True
            ).select_related('provider').first()

        q = queue.Queue()

        def status_cb(step, detail=""):
            q.put(('status', {'step': step, 'detail': detail}))

        def run():
            try:
                result = run_nl_query(question, db, status_cb=status_cb, llm_model=llm_model)
                q.put(('result', result))
            except Exception as e:
                logger.error(f"[ASK VIEW] Unhandled error: {e}", exc_info=True)
                q.put(('error', {'message': 'Something went wrong. Please try again.'}))

        threading.Thread(target=run, daemon=True).start()

        while True:
            event_type, payload = q.get()
            yield f"event: {event_type}\ndata: {json.dumps(payload)}\n\n"
            if event_type in ('result', 'error'):
                # Save to history on result
                if event_type == 'result':
                    entry = QueryHistory.objects.create(
                        database=db,
                        user=request.user,
                        question=question,
                        generated_sql=payload.get('sql', ''),
                        nl_response=payload.get('nl_response', ''),
                        error=payload.get('error', ''),
                        result_columns=payload.get('columns', []),
                        result_rows=payload.get('rows', []),
                    )
                    # Emit a final enriched result with DB-assigned id
                    final = {
                        'id':          entry.id,
                        'question':    question,
                        'sql':         payload.get('sql', ''),
                        'nl_response': payload.get('nl_response', ''),
                        'columns':     payload.get('columns', []),
                        'rows':        payload.get('rows', []),
                        'error':       '',
                        'created_at':  entry.created_at.strftime('%H:%M'),
                    }
                    yield f"event: final\ndata: {json.dumps(final)}\n\n"
                break

    response = StreamingHttpResponse(event_stream(), content_type='text/event-stream')
    response['Cache-Control'] = 'no-cache'
    response['X-Accel-Buffering'] = 'no'
    return response


# ── Database Management ────────────────────────────────────────────────────────

def databases_view(request):
    if not request.user.is_authenticated:
        return redirect('/login/')
    dbs = list(DatabaseConnection.objects.filter(user=request.user))
    # Annotate each db with the table count from fetched_schema
    for db in dbs:
        db.table_count = len([l for l in db.fetched_schema.strip().splitlines() if l.strip()]) if db.fetched_schema else 0
    return render(request, 'databases.html', {
        'user': request.user,
        'databases': dbs,
        'databases_with_schema': sum(1 for db in dbs if db.fetched_schema),
        'databases_file_based': sum(1 for db in dbs if db.is_file_based),
    })


def add_database_view(request):
    if not request.user.is_authenticated:
        return redirect('/login/')

    ctx = {'user': request.user, 'db_types': DatabaseConnection.DB_TYPES}

    if request.method == 'POST':
        label              = request.POST.get('label', '').strip()
        db_type            = request.POST.get('db_type', 'postgresql')
        store_credentials  = request.POST.get('store_credentials') == 'yes'
        schema_description = request.POST.get('schema_description', '').strip()

        if not label:
            messages.error(request, 'Please provide a label for this database.')
            return render(request, 'add_database.html', ctx)

        if DatabaseConnection.objects.filter(user=request.user, label=label).exists():
            messages.error(request, f'You already have a database labelled "{label}".')
            return render(request, 'add_database.html', ctx)

        db = DatabaseConnection(
            user=request.user,
            label=label,
            db_type=db_type,
            store_credentials=store_credentials,
            schema_description=schema_description,
        )

        if store_credentials:
            input_mode = request.POST.get('input_mode', 'string')
            if input_mode == 'string':
                db.connection_string = request.POST.get('connection_string', '').strip()
            else:
                db.host        = request.POST.get('host', '').strip()
                db.port        = request.POST.get('port', '').strip()
                db.db_name     = request.POST.get('db_name', '').strip()
                db.db_user     = request.POST.get('db_user', '').strip()
                db.db_password = request.POST.get('db_password', '').strip()
                db.use_ssl     = request.POST.get('use_ssl') == 'on'

        db.save()

        # ── Fetch and store schema immediately after saving ───────────────────
        if store_credentials:
            schema = fetch_schema(db)
            if schema:
                db.fetched_schema = schema
                db.schema_fetched_at = timezone.now()
                db.save(update_fields=['fetched_schema', 'schema_fetched_at'])
                messages.success(request, f'"{label}" added and schema loaded ({len(schema.splitlines())} tables).')
            else:
                messages.warning(
                    request,
                    f'"{label}" saved but schema could not be fetched. '
                    'Check your connection details — the AI will have limited context until the schema is available.'
                )
        else:
            messages.success(request, f'"{label}" added (label-only mode, no schema fetched).')
        # ─────────────────────────────────────────────────────────────────────

        return redirect(f'/chat/{db.id}/')

    return render(request, 'add_database.html', ctx)


def upload_file_db_view(request):
    """
    Accepts a CSV / XLS / XLSX file upload.
    Loads each sheet (Excel) or the single table (CSV) into a dedicated
    per-user SQLite file at:  user_data/<user_id>/<label>.db
    Then creates a DatabaseConnection record and fetches the schema.
    """
    if not request.user.is_authenticated:
        return redirect('/login/')

    ctx = {'user': request.user}

    if request.method == 'POST':
        import pandas as pd

        label = request.POST.get('label', '').strip()
        uploaded = request.FILES.get('datafile')

        if not label:
            messages.error(request, 'Please provide a label.')
            return render(request, 'upload_file_db.html', ctx)

        if not uploaded:
            messages.error(request, 'Please select a file.')
            return render(request, 'upload_file_db.html', ctx)

        if DatabaseConnection.objects.filter(user=request.user, label=label).exists():
            messages.error(request, f'You already have a database labelled "{label}".')
            return render(request, 'upload_file_db.html', ctx)

        ext = os.path.splitext(uploaded.name)[1].lower()
        if ext not in ('.csv', '.xls', '.xlsx'):
            messages.error(request, 'Only CSV, XLS and XLSX files are supported.')
            return render(request, 'upload_file_db.html', ctx)

        # ── Build destination SQLite path ─────────────────────────────────────
        user_dir = os.path.join(settings.BASE_DIR, 'user_data', str(request.user.id))
        os.makedirs(user_dir, exist_ok=True)
        safe_label = "".join(c if c.isalnum() or c in ('_', '-') else '_' for c in label)
        sqlite_file = os.path.join(user_dir, f"{safe_label}.db")

        # ── Parse file and load into SQLite ───────────────────────────────────
        try:
            if ext == '.csv':
                sheets = {'data': pd.read_csv(uploaded)}
            else:
                xf = pd.ExcelFile(uploaded)
                sheets = {sheet: xf.parse(sheet) for sheet in xf.sheet_names}

            conn_sqlite = sqlite3.connect(sqlite_file)
            tables_loaded = []
            for sheet_name, df in sheets.items():
                # Clean column names — replace spaces/special chars with underscores
                df.columns = [
                    "".join(c if c.isalnum() or c == '_' else '_' for c in str(col)).strip('_')
                    for col in df.columns
                ]
                table_name = "".join(c if c.isalnum() or c == '_' else '_' for c in sheet_name).strip('_') or 'sheet'
                df.to_sql(table_name, conn_sqlite, if_exists='replace', index=False)
                tables_loaded.append(f"{table_name} ({len(df)} rows)")
                logger.info(f"[FILE UPLOAD] Loaded sheet '{sheet_name}' as table '{table_name}' ({len(df)} rows) for user {request.user.email}")
            conn_sqlite.close()

        except Exception as e:
            logger.error(f"[FILE UPLOAD FAILED] user={request.user.email} file={uploaded.name} error={e}", exc_info=True)
            messages.error(request, f'Failed to parse the file: {e}')
            return render(request, 'upload_file_db.html', ctx)

        # ── Create DatabaseConnection record ──────────────────────────────────
        db = DatabaseConnection.objects.create(
            user=request.user,
            label=label,
            db_type='sqlite',
            store_credentials=True,
            is_file_based=True,
            sqlite_path=os.path.relpath(sqlite_file, settings.BASE_DIR),  # store relative to BASE_DIR
            schema_description=f"Imported from {uploaded.name}",
        )

        # Fetch and store schema
        from .aiTools import fetch_schema
        schema = fetch_schema(db)
        if schema:
            db.fetched_schema = schema
            db.schema_fetched_at = timezone.now()
            db.save(update_fields=['fetched_schema', 'schema_fetched_at'])

        messages.success(request, f'"{label}" created from {uploaded.name} — {", ".join(tables_loaded)}.')
        return redirect(f'/chat/{db.id}/')

    return render(request, 'upload_file_db.html', ctx)



# ── Settings: LLM Providers & Models ──────────────────────────────────────────

def settings_view(request):
    if not request.user.is_authenticated:
        return redirect('/login/')
    providers = LLMProvider.objects.filter(user=request.user).prefetch_related('models')
    all_dbs   = DatabaseConnection.objects.filter(user=request.user)
    return render(request, 'settings.html', {
        'user': request.user,
        'providers': providers,
        'provider_choices': LLMProvider.PROVIDER_CHOICES,
        'all_dbs': all_dbs,
    })


@require_POST
def save_provider_view(request):
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Unauthenticated'}, status=401)
    provider   = request.POST.get('provider', '').strip()
    api_key    = request.POST.get('api_key', '').strip()
    base_url   = request.POST.get('base_url', 'http://localhost:11434').strip()

    valid = [p for p, _ in LLMProvider.PROVIDER_CHOICES]
    if provider not in valid:
        return JsonResponse({'error': 'Invalid provider.'}, status=400)

    obj, created = LLMProvider.objects.update_or_create(
        user=request.user, provider=provider,
        defaults={
            'api_key':  api_key,
            # Only store base_url for Ollama — cloud providers don't need it
            'base_url': base_url if provider == 'ollama' else '',
        },
    )
    logger.info(f"[SETTINGS] Provider '{provider}' {'created' if created else 'updated'} for {request.user.email}")
    return JsonResponse({'ok': True, 'id': obj.id, 'masked_key': obj.masked_key()})


@require_POST
def delete_provider_view(request, provider_id):
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Unauthenticated'}, status=401)
    obj = get_object_or_404(LLMProvider, id=provider_id, user=request.user)
    obj.delete()
    return JsonResponse({'ok': True})


@require_POST
def save_model_view(request):
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Unauthenticated'}, status=401)
    provider_id  = request.POST.get('provider_id')
    model_id     = request.POST.get('model_id', '').strip()
    display_name = request.POST.get('display_name', '').strip()
    is_default   = request.POST.get('is_default') == 'true'

    if not model_id or not display_name:
        return JsonResponse({'error': 'model_id and display_name are required.'}, status=400)

    provider = get_object_or_404(LLMProvider, id=provider_id, user=request.user)

    if is_default:
        # clear existing default for this user
        LLMModel.objects.filter(user=request.user, is_default=True).update(is_default=False)

    obj, created = LLMModel.objects.update_or_create(
        user=request.user, provider=provider, model_id=model_id,
        defaults={'display_name': display_name, 'is_default': is_default},
    )
    return JsonResponse({'ok': True, 'id': obj.id, 'display_name': display_name,
                         'model_id': model_id, 'provider_id': provider.id,
                         'provider_name': provider.get_provider_display(),
                         'is_default': obj.is_default})


@require_POST
def delete_model_view(request, model_id):
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Unauthenticated'}, status=401)
    obj = get_object_or_404(LLMModel, id=model_id, user=request.user)
    obj.delete()
    return JsonResponse({'ok': True})


def models_for_chat_view(request):
    """Returns all user models as JSON — used by chat to populate selector."""
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Unauthenticated'}, status=401)
    models_qs = LLMModel.objects.filter(user=request.user).select_related('provider')
    data = [{'id': m.id, 'display_name': m.display_name, 'model_id': m.model_id,
              'provider': m.provider.provider, 'is_default': m.is_default}
             for m in models_qs]
    return JsonResponse({'models': data})


@require_POST
def dashboard_chart_view(request, db_id):
    """
    Receives a plain-English chart request.
    Returns: { title, chart_type, labels, datasets, sql, error }
    chart_type: bar | line | pie | doughnut | area | scatter
    """
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Unauthenticated'}, status=401)

    db = get_object_or_404(DatabaseConnection, id=db_id, user=request.user)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid request.'}, status=400)

    question = data.get('question', '').strip()
    model_id = data.get('model_id')
    if not question:
        return JsonResponse({'error': 'Empty question.'}, status=400)

    llm_model = None
    if model_id:
        try:
            llm_model = LLMModel.objects.select_related('provider').get(id=model_id, user=request.user)
        except LLMModel.DoesNotExist:
            pass
    if not llm_model:
        llm_model = LLMModel.objects.filter(user=request.user, is_default=True).select_related('provider').first()

    from .aiView import run_chart_query
    result = run_chart_query(question, db, llm_model=llm_model)
    return JsonResponse(result)


def dashboard_charts_list(request, db_id):
    """Returns all saved charts for a database."""
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Unauthenticated'}, status=401)
    db = get_object_or_404(DatabaseConnection, id=db_id, user=request.user)
    charts = DashboardChart.objects.filter(database=db, user=request.user)
    data = [{
        'id':             c.id,
        'title':          c.title,
        'question':       c.question,
        'chart_type':     c.chart_type,
        'sql':            c.sql,
        'echarts_option': c.chart_data.get('echarts_option', {}),
    } for c in charts]
    return JsonResponse({'charts': data})


@require_POST
def dashboard_chart_save(request, db_id):
    """Saves a chart to the database."""
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Unauthenticated'}, status=401)
    db = get_object_or_404(DatabaseConnection, id=db_id, user=request.user)
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid request.'}, status=400)

    chart = DashboardChart.objects.create(
        database=db,
        user=request.user,
        title=data.get('title', 'Chart'),
        question=data.get('question', ''),
        chart_type=data.get('chart_type', 'bar'),
        sql=data.get('sql', ''),
        chart_data={'echarts_option': data.get('echarts_option', {})},
        position=DashboardChart.objects.filter(database=db, user=request.user).count(),
    )
    return JsonResponse({'ok': True, 'id': chart.id})


@require_POST
def dashboard_chart_delete(request, db_id, chart_id):
    """Deletes a saved chart."""
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Unauthenticated'}, status=401)
    chart = get_object_or_404(DashboardChart, id=chart_id, database__id=db_id, user=request.user)
    chart.delete()
    return JsonResponse({'ok': True})


def docs_view(request):
    if not request.user.is_authenticated:
        return redirect('/login/')
    all_dbs = DatabaseConnection.objects.filter(user=request.user)

    openrouter_models = [
        ('google/gemma-3-27b-it:free',            'Gemma 3 27B',        'Free · fast'),
        ('google/gemma-4-31b-it:free',             'Gemma 4 31B',        'Free · capable'),
        ('deepseek/deepseek-chat-v3-0324:free',    'DeepSeek Chat V3',   'Free · excellent for SQL'),
        ('meta-llama/llama-3.3-70b-instruct:free', 'Llama 3.3 70B',      'Free · strong reasoning'),
        ('mistralai/mistral-7b-instruct:free',     'Mistral 7B',         'Free · lightweight'),
    ]
    gemini_models = [
        ('gemini-2.0-flash',      'Gemini 2.0 Flash',      'Free tier · fast'),
        ('gemini-2.0-flash-lite', 'Gemini 2.0 Flash Lite', 'Free tier · lightest'),
        ('gemini-1.5-flash',      'Gemini 1.5 Flash',      'Free tier · reliable'),
        ('gemini-1.5-flash-8b',   'Gemini 1.5 Flash 8B',   'Free tier · smallest'),
    ]
    return render(request, 'docs.html', {
        'user': request.user,
        'all_dbs': all_dbs,
        'openrouter_models': openrouter_models,
        'gemini_models': gemini_models,
    })


def clear_history_view(request, db_id):    
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Unauthenticated'}, status=401)
    db = get_object_or_404(DatabaseConnection, id=db_id, user=request.user)
    deleted_count, _ = QueryHistory.objects.filter(database=db, user=request.user).delete()
    logger.info(f"[CLEAR HISTORY] db='{db.label}' user='{request.user.email}' deleted={deleted_count} entries")  # noqa
    return JsonResponse({'cleared': deleted_count})


def delete_database_view(request, db_id):
    if not request.user.is_authenticated:
        return redirect('/login/')
    db = get_object_or_404(DatabaseConnection, id=db_id, user=request.user)
    db.delete()
    messages.success(request, 'Database removed.')
    return redirect('/databases/')


@require_POST
def update_database_view(request, db_id):
    """AJAX: update label and/or schema_description for a database."""
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Unauthenticated'}, status=401)
    db = get_object_or_404(DatabaseConnection, id=db_id, user=request.user)
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid request.'}, status=400)

    label = data.get('label', '').strip()
    description = data.get('schema_description', '').strip()

    if not label:
        return JsonResponse({'error': 'Label cannot be empty.'}, status=400)

    # Check uniqueness — allow keeping the same label
    if label != db.label and DatabaseConnection.objects.filter(user=request.user, label=label).exists():
        return JsonResponse({'error': f'You already have a database labelled "{label}".'}, status=400)

    db.label = label
    db.schema_description = description
    db.save(update_fields=['label', 'schema_description'])
    logger.info(f"[DB UPDATE] id={db.id} label='{label}' user='{request.user.email}'")
    return JsonResponse({'ok': True, 'label': db.label})


@require_POST
def refresh_schema_view(request, db_id):
    """AJAX: re-fetch and store the schema for a database."""
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Unauthenticated'}, status=401)
    db = get_object_or_404(DatabaseConnection, id=db_id, user=request.user)

    if not db.store_credentials:
        return JsonResponse({'error': 'Schema cannot be refreshed for label-only databases.'}, status=400)

    schema = fetch_schema(db)
    if schema:
        db.fetched_schema = schema
        db.schema_fetched_at = timezone.now()
        db.save(update_fields=['fetched_schema', 'schema_fetched_at'])
        table_count = len(schema.strip().splitlines())
        logger.info(f"[SCHEMA REFRESH] id={db.id} tables={table_count} user='{request.user.email}'")
        return JsonResponse({'ok': True, 'schema': schema, 'table_count': table_count,
                             'refreshed_at': db.schema_fetched_at.strftime('%b %d, %Y %H:%M')})
    else:
        return JsonResponse({'error': 'Could not fetch schema. Check connection details.'}, status=400)
