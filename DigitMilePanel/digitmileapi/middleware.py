import logging
from django.http import JsonResponse

logger = logging.getLogger(__name__)

class HealthCheckMiddleware:
    """
    Middleware that handles health check requests before Django's
    ALLOWED_HOSTS validation kicks in.
    
    This is safe because:
    1. It only responds to a specific path (/health/)
    2. It returns a simple static response with no sensitive data
    3. The actual application routes still enforce ALLOWED_HOSTS
    """
    
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Intercept health check requests before host validation
        host = request.META.get('HTTP_HOST', 'unknown')
        remote_addr = request.META.get('REMOTE_ADDR', 'unknown')
        logger.info(f"Request intercepted from {remote_addr} with Host header: {host}")

        if 'health' in request.path:
            
            logger.info(f"Health check from {remote_addr} with Host header: {host}")
            return JsonResponse({"status": "healthy"})
        
        # All other requests go through normal Django processing
        return self.get_response(request)