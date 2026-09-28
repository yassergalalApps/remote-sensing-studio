from json import loads, dumps


def weibo_compliance_fix(session):
    def _missing_token_type(r):
        token = loads(r.text)
        token["token_type"] = "Bearer"  # nosec B105 - Fixed OAuth authorization scheme, not a credential.
        r._content = dumps(token).encode()
        return r

    session._client.default_token_placement = "query"  # nosec B105 - Configuration string for token placement, not a credential.
    session.register_compliance_hook("access_token_response", _missing_token_type)
    return session
