# Model providers

Open Settings -> AI Providers to configure DeepSeek, LaoZhang API or a compatible
endpoint. Type the model name manually; fetching a model list is not required.

1. Save a name, Base URL, model and credential variable reference.
2. Confirm that the endpoint is the intended recipient of credentials.
3. Enter or replace the key through the write-only password form, or configure it
   on the server. Existing key values are never returned.
4. Optionally run Test connection. This is an explicit model request and may cost money.
5. Select a pinned provider version and model when creating a built-in candidate experiment.
   Explicitly authorize paid calls to start it.

Saving, listing, importing or re-evaluating does not call a model.
External Agent targets keep their own models and credentials; this setting does not
replace their model configuration. External service tokens and judge models have
separate purposes.

## Central credentials

The only persistent key source is the file referenced by AGENT_API_ENV_FILE.
On Windows, the default is the current user's Desktop/api/.env. Other deployments
must supply the pointer or process environment. Explicit process variables override
central values; the UI reports the source without exposing a value.

Key writes are restricted to loopback, same-origin administration with CSRF protection.
Remote deployments use server-managed environment configuration. The central file
is updated with a lock, version check and atomic replacement, preserving unrelated
variables and access permissions. A failed write does not create a second key store.
Rotating a shared key affects other applications referencing that variable. Disabling
a provider does not delete the shared credential.

No key belongs in a dataset, trace, browser storage, source repository or platform
database. The platform stores only nonsecret provider configuration versions.

## Real-model smoke runs

The optional paired smoke uses the same model for two different tool sets, with
concurrency one and a shared limit of 128 model requests. Candidate failures and
incomplete runs remain visible; passing platform tests does not imply model success.
Unknown token usage and unknown prices remain unknown, not zero.
