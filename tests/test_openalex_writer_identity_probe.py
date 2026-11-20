import io
import json
import unittest
import urllib.error
import urllib.parse
from scripts.openalex_writer_identity_probe import check_identity


def env():
    return {'GITHUB_RUN_ID': '123456', 'GITHUB_SHA': 'a' * 40, 'ALEX_CHECKOUT_HEAD': 'a' * 40, 'ALEX_PIPELINE_STATE_HEAD': 'b' * 40,
            'ALEX_SITE_SERVICE_BEARER': 'synthetic-service-secret',
            'ACTIONS_ID_TOKEN_REQUEST_TOKEN': 'synthetic-request-secret',
            'ACTIONS_ID_TOKEN_REQUEST_URL': 'https://pipelines.actions.githubusercontent.com/token?x=1'}


class Response(io.BytesIO):
    def __init__(self, payload, status=200):
        super().__init__(json.dumps(payload).encode())
        self.status = status
    def __enter__(self): return self
    def __exit__(self, *args): self.close()


class Opener:
    def __init__(self, site_response=None):
        self.calls = []
        self.site_response = site_response or {'identity_verified': True, 'provider_access_authorized': False}
    def open(self, request, timeout):
        self.calls.append(request)
        parsed = urllib.parse.urlsplit(request.full_url)
        if parsed.hostname == 'pipelines.actions.githubusercontent.com':
            assert urllib.parse.parse_qs(parsed.query)['audience'] == [
                'https://alex-research-review.neil-schwartzm917549.chatgpt.site/api/private-openalex-writer-identity']
            return Response({'value': 'synthetic-oidc-token'})
        assert parsed.hostname == 'alex-research-review.neil-schwartzm917549.chatgpt.site'
        assert request.get_method() == 'POST'
        data = json.loads(request.data)
        assert data['identity_token'] == 'synthetic-oidc-token'
        return Response(self.site_response)


class IdentityProbeTest(unittest.TestCase):
    def test_verified_identity_never_authorizes_a_provider_send(self):
        opener = Opener()
        result = check_identity(env(), opener)
        self.assertEqual(result, {'status': 'identity_verified', 'provider_access_authorized': False})
        self.assertEqual(len(opener.calls), 2)
        self.assertNotIn('synthetic-', json.dumps(result))

    def test_malformed_or_untrusted_environment_makes_no_request(self):
        for changes in [{'GITHUB_RUN_ID': '../bad'}, {'GITHUB_SHA': 'bad'}, {'ALEX_CHECKOUT_HEAD': 'bad'},
                        {'ACTIONS_ID_TOKEN_REQUEST_URL': 'https://attacker.invalid/token'},
                        {'ACTIONS_ID_TOKEN_REQUEST_URL': 'https://user@pipelines.actions.githubusercontent.com/token'},
                        {'ACTIONS_ID_TOKEN_REQUEST_URL': 'https://pipelines.actions.githubusercontent.com/token?audience=other'}]:
            values = env(); values.update(changes); opener = Opener()
            self.assertEqual(check_identity(values, opener)['status'], 'unavailable')
            self.assertEqual(opener.calls, [])

    def test_unsafe_or_ambiguous_site_result_is_never_accepted(self):
        for response in [{'identity_verified': False, 'provider_access_authorized': False},
                         {'identity_verified': True, 'provider_access_authorized': True},
                         {'identity_verified': True, 'provider_access_authorized': False, 'extra': 'bad'}]:
            self.assertEqual(check_identity(env(), Opener(response))['status'], 'unavailable')

    def test_network_error_details_are_not_returned(self):
        class Failing:
            def open(self, request, timeout): raise OSError('synthetic-service-secret')
        result = check_identity(env(), Failing())
        self.assertEqual(result['status'], 'unavailable')
        self.assertNotIn('synthetic-service-secret', json.dumps(result))


if __name__ == '__main__': unittest.main()
