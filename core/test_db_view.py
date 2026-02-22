from django.http import HttpResponse
from django.contrib.auth.decorators import login_required
from django.db import connection

@login_required
def test_database_connection(request):
    """Simple test view to show database status without any caching."""
    html = """
    <html>
    <head><title>Database Test</title></head>
    <body style="font-family: monospace; padding: 20px;">
    <h1>Database Connection Test</h1>
    <pre>
"""
    
    db_info = {'connected': False, 'engine': 'unknown'}
    try:
        db_engine = connection.settings_dict['ENGINE']
        db_info['engine'] = db_engine.split('.')[-1]
        
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            db_info['connected'] = True
            html += f"✓ DATABASE CONNECTED: {db_info['connected']}\n"
            html += f"✓ Engine: {db_info['engine']}\n"
            html += f"✓ Type: {type(db_info['connected'])}\n"
    except Exception as e:
        db_info['connected'] = False
        html += f"✗ ERROR: {str(e)}\n"
    
    html += f"\ndb_info dict: {db_info}\n"
    html += f"bool(db_info['connected']): {bool(db_info['connected'])}\n"
    html += """
    </pre>
    <p><a href="/core/settings/system-status/">Back to System Status</a></p>
    </body>
    </html>
    """
    
    return HttpResponse(html)
