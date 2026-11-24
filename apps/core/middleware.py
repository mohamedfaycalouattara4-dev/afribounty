from django.http import HttpRequest, HttpResponse

from apps.core.correlation import correlation_id, new_correlation_id


class CorrelationIdMiddleware:
    header_name = "HTTP_X_CORRELATION_ID"
    response_header = "X-Correlation-ID"

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        supplied = request.META.get(self.header_name, "").strip()
        value = supplied if 8 <= len(supplied) <= 128 else new_correlation_id()
        token = correlation_id.set(value)
        try:
            response = self.get_response(request)
            response[self.response_header] = value
            return response
        finally:
            correlation_id.reset(token)
