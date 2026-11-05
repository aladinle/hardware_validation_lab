class PrivateResponseMiddleware:
    """Keep authenticated pages and authentication forms out of shared caches."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response["Cache-Control"] = "no-store, private"
        # no-referrer makes native form POSTs send Origin: null in browsers,
        # which Django correctly rejects. Keep referrers within this origin.
        response["Referrer-Policy"] = "same-origin"
        return response


class SessionEpochMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated and request.session.get("lab_epoch", -1) != request.user.session_epoch:
            from django.contrib.auth import logout
            logout(request)
        return self.get_response(request)
