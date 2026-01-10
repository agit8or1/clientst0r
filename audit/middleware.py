"""
Audit logging middleware - Automatically logs ALL user actions
Logs: reads (views), creates, updates, deletes, logins, API calls
"""
from django.utils.deprecation import MiddlewareMixin
from django.contrib.contenttypes.models import ContentType
from .models import AuditLog


class AuditLoggingMiddleware(MiddlewareMixin):
    """
    Comprehensive middleware that automatically logs ALL user actions.
    Captures: view access, form submissions, API calls, authentication, etc.
    """

    # Paths to exclude from logging (static files, etc)
    EXCLUDE_PATHS = [
        '/static/',
        '/media/',
        '/favicon.ico',
        '/__debug__/',
        '/jsi18n/',
        '/admin/jsi18n/',
    ]

    # Methods that indicate data modification
    MODIFICATION_METHODS = ['POST', 'PUT', 'PATCH', 'DELETE']

    def process_request(self, request):
        """Store request start time for duration tracking."""
        import time
        request._audit_start_time = time.time()

    def process_response(self, request, response):
        """Log the request after response is generated."""
        # Skip if path is excluded
        if any(request.path.startswith(path) for path in self.EXCLUDE_PATHS):
            return response

        # Skip if user is not authenticated (except for login attempts)
        if not hasattr(request, 'user') or not request.user.is_authenticated:
            if 'login' not in request.path:
                return response

        # Determine action type based on HTTP method and path
        action = self._determine_action(request, response)
        if not action:
            return response

        # Get organization from request
        organization = self._get_organization(request)

        # Extract object information from path
        object_type, object_id, object_repr = self._extract_object_info(request, response)

        # Get client info
        ip_address = self._get_client_ip(request)
        user_agent = request.META.get('HTTP_USER_AGENT', '')[:500]

        # Build description
        description = self._build_description(request, action, object_type)

        # Calculate request duration
        duration = None
        if hasattr(request, '_audit_start_time'):
            import time
            duration = time.time() - request._audit_start_time

        # Extra data
        extra_data = {
            'method': request.method,
            'status_code': response.status_code,
            'duration': round(duration, 3) if duration else None,
        }

        # Add query params for GET requests
        if request.method == 'GET' and request.GET:
            extra_data['query_params'] = dict(request.GET)

        # Add form data for POST requests (excluding passwords)
        if request.method == 'POST' and request.POST:
            form_data = {}
            for key, value in request.POST.items():
                # Don't log sensitive fields
                if key.lower() in ['password', 'password1', 'password2', 'old_password',
                                  'new_password', 'secret', 'token', 'api_key', 'csrfmiddlewaretoken']:
                    form_data[key] = '***REDACTED***'
                else:
                    form_data[key] = value[:100]  # Limit length
            extra_data['form_data'] = form_data

        # Log the action
        try:
            user = request.user if request.user.is_authenticated else None
            AuditLog.log(
                user=user,
                action=action,
                organization=organization,
                object_type=object_type,
                object_id=object_id,
                object_repr=object_repr,
                description=description,
                ip_address=ip_address,
                user_agent=user_agent,
                path=request.path,
                extra_data=extra_data,
                success=200 <= response.status_code < 400
            )
        except Exception as e:
            # Don't break the request if audit logging fails
            import logging
            logger = logging.getLogger('audit')
            logger.error(f"Audit logging failed: {str(e)}")

        return response

    def _determine_action(self, request, response):
        """Determine the action type from request method and path."""
        method = request.method
        path = request.path.lower()

        # Handle authentication
        if 'login' in path:
            if response.status_code in [200, 302] and request.method == 'POST':
                return 'login'
            elif request.method == 'POST':
                return 'login_failed'
            return None
        elif 'logout' in path:
            return 'logout'

        # Handle CRUD operations
        if method == 'GET':
            # Log detail views (viewing specific objects)
            if self._is_detail_view(request):
                return 'read'
            # Don't log list views to reduce noise
            return None
        elif method == 'POST':
            if 'delete' in path or '/delete/' in path or request.POST.get('_method') == 'DELETE':
                return 'delete'
            elif '/edit/' in path or self._is_update(request):
                return 'update'
            else:
                return 'create'
        elif method in ['PUT', 'PATCH']:
            return 'update'
        elif method == 'DELETE':
            return 'delete'

        return None

    def _is_detail_view(self, request):
        """Check if this is a detail view (viewing a specific object)."""
        import re
        # Match paths like /passwords/123/, /assets/456/, /monitoring/racks/2/, etc.
        # But not /passwords/create/ or /assets/edit/
        if re.search(r'/create/?$', request.path) or re.search(r'/edit/?$', request.path):
            return False
        return bool(re.search(r'/\d+/?$', request.path))

    def _is_update(self, request):
        """Check if POST is actually an update."""
        if not hasattr(request, 'resolver_match'):
            return False
        return '/edit/' in request.path or 'pk' in request.resolver_match.kwargs

    def _get_organization(self, request):
        """Get the current organization from request session."""
        from core.models import Organization
        org_id = request.session.get('current_organization_id')
        if org_id:
            try:
                return Organization.objects.get(id=org_id)
            except Organization.DoesNotExist:
                pass
        return None

    def _extract_object_info(self, request, response):
        """Extract object type, ID, and representation from request."""
        object_type = ''
        object_id = None
        object_repr = ''

        # Try to get from URL resolver
        if hasattr(request, 'resolver_match') and request.resolver_match:
            # Get model name from URL pattern
            url_name = request.resolver_match.url_name
            if url_name:
                # Extract model from URL name (e.g., 'password_detail' -> 'password')
                parts = url_name.split('_')
                if len(parts) > 1 and parts[-1] in ['detail', 'edit', 'delete', 'create', 'list']:
                    object_type = '_'.join(parts[:-1])
                elif len(parts) > 0:
                    object_type = parts[0]

            # Get object ID from URL kwargs
            kwargs = request.resolver_match.kwargs
            if 'pk' in kwargs:
                try:
                    object_id = int(kwargs['pk'])
                except (ValueError, TypeError):
                    pass
            elif 'id' in kwargs:
                try:
                    object_id = int(kwargs['id'])
                except (ValueError, TypeError):
                    pass

        # Try to get object representation from context
        if object_id and object_type:
            object_repr = self._get_object_repr(object_type, object_id)

        return object_type, object_id, object_repr

    def _get_object_repr(self, object_type, object_id):
        """Get string representation of object."""
        try:
            # Map common object types to models
            model_map = {
                'password': ('vault', 'Password'),
                'asset': ('assets', 'Asset'),
                'document': ('docs', 'Document'),
                'contact': ('assets', 'Contact'),
                'website_monitor': ('monitoring', 'WebsiteMonitor'),
                'expiration': ('monitoring', 'Expiration'),
                'rack': ('monitoring', 'Rack'),
                'rack_device': ('monitoring', 'RackDevice'),
                'subnet': ('monitoring', 'Subnet'),
                'ip_address': ('monitoring', 'IPAddress'),
                'personal_vault': ('vault', 'PersonalVault'),
                'organization': ('core', 'Organization'),
                'user': ('auth', 'User'),
            }

            model_info = model_map.get(object_type)
            if not model_info:
                return ''

            app_label, model_name = model_info
            content_type = ContentType.objects.get(app_label=app_label, model=model_name.lower())
            model_class = content_type.model_class()

            obj = model_class.objects.get(pk=object_id)
            return str(obj)[:255]
        except Exception:
            return f'{object_type} #{object_id}'

    def _build_description(self, request, action, object_type):
        """Build human-readable description of action."""
        if not request.user.is_authenticated:
            return f"Anonymous {action} attempt"

        user = request.user.username
        action_text = {
            'create': 'created',
            'read': 'viewed',
            'update': 'updated',
            'delete': 'deleted',
            'login': 'logged in',
            'logout': 'logged out',
            'login_failed': 'failed login attempt',
        }.get(action, action)

        if object_type:
            # Make object type more readable
            readable_type = object_type.replace('_', ' ').title()
            return f"{user} {action_text} {readable_type}"
        return f"{user} {action_text}"

    def _get_client_ip(self, request):
        """Extract client IP address from request."""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0].strip()
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip
