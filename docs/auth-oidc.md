# OIDC authentication for remote MCP

OIDC mode lets an OAuth client such as ChatGPT obtain a user access token from an existing identity provider. OpenTranscribe verifies the token on every MCP request. Bearer mode remains available for clients that can securely supply a fixed secret.

The public MCP URL is `https://transcribe.example.com/mcp`. The public base URL setting is its origin, `https://transcribe.example.com`. In OIDC mode, `/.well-known/oauth-protected-resource/mcp` advertises the resource URL, authorization server, and required scope. `/mcp` returns an OAuth challenge until a valid token is presented.

## Configure the identity provider

1. Use an issuer with HTTPS discovery, signing keys, authorization code flow, PKCE S256, and access tokens containing `iss`, `aud`, `exp`, and `scope`.
2. Register a dedicated OAuth client for the MCP consumer. Allow only the exact redirect URI shown by that consumer's MCP connection page. Enable authorization code and PKCE S256. Choose a supported client authentication method; do not use a service-account grant for ChatGPT.
3. Define a scope such as `mcp:tools`. Ensure access tokens containing this scope also contain the **exact** MCP URL in `aud`. Keycloak can do this with an optional client scope named `mcp:tools` and an Audience mapper whose Included Custom Audience is `https://transcribe.example.com/mcp`.
4. Define an entitlement restricted to intended users. With the defaults below, create a realm role named `open-transcribe-user`, include realm roles in the access token, and assign that role to permitted users. A token with a valid signature but without the role is rejected.

Keycloak's current MCP guidance describes the audience mapper because it does not yet process the OAuth `resource` parameter into `aud` automatically. Keep the scope and audience mapper together. The MCP server does not depend on Keycloak-specific administration APIs.

## Configure OpenTranscribe

```text
OT_SECURITY__AUTH_MODE=oidc
OT_SECURITY__OIDC_ISSUER_URL=https://id.example.com/realms/example
OT_SECURITY__OIDC_JWKS_URL=https://id.example.com/realms/example/protocol/openid-connect/certs
OT_SECURITY__OIDC_PUBLIC_BASE_URL=https://transcribe.example.com
OT_SECURITY__OIDC_REQUIRED_SCOPE=mcp:tools
OT_SECURITY__OIDC_REQUIRED_CLAIM_PATH=realm_access.roles
OT_SECURITY__OIDC_REQUIRED_CLAIM_VALUE=open-transcribe-user
```

For the Terraform module, set `auth_mode = "oidc"` and put these non-secret `OT_SECURITY__OIDC_*` settings in `environment_variables`. Keep provider API keys in `secret_environment_variables`. The bearer token is unnecessary in OIDC mode. Deploy the new image and configuration together; changing only the Terraform mode on an older image will fail startup.

The verifier accepts RS256 JWT access tokens with the configured issuer, JWKS, exact MCP audience, required scope, unexpired `exp`, valid `nbf` if present, and the configured claim value. It does not accept opaque tokens. Use short-lived access tokens and the identity provider's normal signing-key rotation.

## Check the connection

1. Verify that `/.well-known/oauth-protected-resource/mcp` returns the expected resource URL and issuer.
2. Verify that an anonymous MCP request gets `401` and a `WWW-Authenticate` challenge with `resource_metadata`.
3. Register the MCP URL in the client, copy its exact redirect URI into the identity provider, and sign in as an entitled user.
4. Check the issued access token's `aud`, `scope`, and entitlement claim without recording or publishing the token. Test `list_transcription_models` before sending an audio source.

An authenticated user without the entitlement, or with the wrong audience or scope, must receive `401`. Keep `/healthz` available for the container's probe.
