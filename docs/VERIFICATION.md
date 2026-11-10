# ProofMode verification report

Checked: 2026-11-10 (UTC clock; the session header says 2026-11-09).
Scope: facts the build depends on. No app code, tests, commits, `uv.lock`, `.venv` or `.python-version` were created in the project. Checks that needed `uv` to resolve or sync ran in scratch copies under the session scratchpad (`<scratch dir>`). No API key was used or read.

## Summary

- (a) Model support, per the public JSON list (https://openrouter.ai/api/v1/models): `meta/muse-ember` and `meta/muse-spark-1.3` both accept `image` input and list `response_format` and `structured_outputs` in `supported_parameters`. All 10 `meta/muse-*` ids accept image input and list both parameters. `meta/muse-glimmer-30b` and its `:batch` variant accept text and image only; the other eight also accept video and file, and some accept audio. Confirmed.
- (b) Image-part format, confirmed from the OpenRouter OpenAPI spec. Chat Completions: `{"type":"image_url","image_url":{"url":"data:image/png;base64,<BASE64>"}}`. Responses API: `{"type":"input_image","image_url":"data:image/png;base64,<BASE64>"}`. The two shapes differ.
- (c) Blockers for the demo: none found on the model or API path. Non-blocking issues: (1) `uv run python --version` resolves to CPython 3.15.1, not 3.14.x, because nothing pins the interpreter (not confirmed as wanted); (2) each Muse model has exactly one endpoint (provider Meta), so there is no provider fallback; (3) no `uv.lock` exists yet, so exact pins are not confirmed in the project.

---

## 1. OpenRouter model capabilities

Sources:
- https://openrouter.ai/api/v1/models (public JSON, no key). Fetched 2026-11-10, HTTP 200, 834,800 bytes, 464 models. Parsed with stdlib `json` under `uv run python -I`.
- https://openrouter.ai/api/v1/models/meta/muse-ember/endpoints and https://openrouter.ai/api/v1/models/meta/muse-spark-1.3/endpoints (per-provider endpoint data, fetched 2026-11-10).

Status: **confirmed** for the fields below, read from the JSON list. The `created` value is converted from the unix timestamp to UTC.

### Requested ids

| id | name | created (UTC) | input_modalities | output_modalities | response_format | structured_outputs | context_length | max completion | pricing (USD per 1M tokens) |
|---|---|---|---|---|---|---|---|---|---|
| meta/muse-ember | Meta: Muse Ember | 2026-11-09 | text, image, video, file, audio | text | yes | yes | 1,048,576 | 943,718 | prompt $0.10, completion $0.50, cache read $0.004, cache write $0.125, web_search 0.0025 (unit not stated in the JSON) |
| meta/muse-spark-1.3 | Meta: Muse Spark 1.3 | 2026-09-02 | text, image, video, file | text | yes | yes | 1,048,576 | 943,718 | prompt $1.25, completion $4.25, cache read $0.15, web_search 0.0025 (unit not stated in the JSON) |

Both ids were found. No id was missing.

### Other `meta/muse*` ids in the list (all checked)

| id | created (UTC) | input_modalities | response_format | structured_outputs | context | pricing (USD per 1M: prompt / completion) |
|---|---|---|---|---|---|---|
| meta/muse-spark-open | 2026-10-15 | text, image, video, file, audio | yes | yes | 1,048,576 | 1.25 / 4.25 |
| meta/muse-wonder | 2026-10-12 | text, image, video, file, audio | yes | yes | 1,048,576 | 4.00 / 20.00 |
| meta/muse-spark-1.3-contributor | 2026-09-02 | text, image, video, file | yes | yes | 1,048,576 | 0.10 / 0.20 |
| meta/muse-spark-1.2-contributor | 2026-08-21 | text, image, video, file | yes | yes | 1,048,576 | 0.10 / 0.20 |
| meta/muse-glimmer-30b | 2026-08-09 | text, image | yes | yes | 131,072 | 0.30 / 1.20 |
| meta/muse-glimmer-30b:batch | 2026-08-09 | text, image | yes | yes | 131,072 | 0.24 / 0.96 |
| meta/muse-spark-1.2 | 2026-08-05 | text, image, video, file | yes | yes | 1,048,576 | 1.25 / 4.25 |
| meta/muse-spark-1.1 | 2026-07-16 | text, image, video, file | yes | yes | 1,048,576 | 1.25 / 4.25 |

Notes:
- The `supported_parameters` list is model-level. Both target models also list `reasoning`, `tools`, `tool_choice`, `temperature`, `top_p`, `max_tokens`.
- `top_provider.is_moderated` is `true` for `meta/muse-ember` and `meta/muse-spark-1.3`. I read this as OpenRouter moderation applying to these requests; the JSON does not explain it further, and I did not test it.
- Across the whole list, 318 of 464 models accept `image` input.

### Per-endpoint check (added because the model list is not per-provider)

- `meta/muse-ember`: one endpoint. Provider Meta, tag `meta`, `status` 0, `uptime_last_30m` 100, `uptime_last_1d` 100. Its `supported_parameters` includes `structured_outputs` and `response_format`. The endpoint object has no separate modality field, so image input is only shown at model level.
- `meta/muse-spark-1.3`: one endpoint, same provider and same parameter support.
- Confirmed: each has a single serving endpoint. Not confirmed: what `status: 0` means. The docs I read do not define it.

Not confirmed: no live inference call was made, so image input and structured-output enforcement are not verified end to end.

---

## 2. OpenRouter image input format

Status: **confirmed** from the OpenAPI spec and the Chat Completions API reference. The markdown render of the image guide drops its code samples, so the spec is the source for the exact shape.

### Chat Completions (`POST /api/v1/chat/completions`)

Source: https://openrouter.ai/docs/api/api-reference/chat/create-a-chat-completion.md, schema `ChatContentImage`.

```yaml
ChatContentImage:
  example:
    image_url:
      detail: auto
      url: https://example.com/image.jpg
    type: image_url
  properties:
    image_url:
      properties:
        detail: enum [auto, low, high, original]
        url: "URL of the image (data: URLs supported)"
      required: [url]
    type: enum [image_url]
  required: [type, image_url]
```

Base64 content part, per the same schema and the generated-image example (`data:image/png;base64,...`):

```json
{"type": "image_url", "image_url": {"url": "data:image/png;base64,<BASE64>"}}
```

Supported image types for base64 (https://openrouter.ai/docs/guides/overview/multimodal/image-understanding.md): `image/png`, `image/jpeg`, `image/webp`, `image/gif`.

### Responses API (`POST /api/v1/responses`)

Source: https://openrouter.ai/docs/openapi/openapi.yaml, schema `InputImage`.

```yaml
InputImage:
  description: "Image input content item. Provide either an image_url (a URL or a base64 data URL) or the file_id of an uploaded image."
  example:
    detail: auto
    image_url: https://example.com/image.jpg
    type: input_image
  properties:
    detail: enum [auto, high, low, original]
    file_id: string | null
    image_url: string | null
    type: enum [input_image]
```

Base64 content part (flat string, not nested):

```json
{"type": "input_image", "image_url": "data:image/png;base64,<BASE64>"}
```

Guide: https://openrouter.ai/docs/guides/overview/multimodal/image-understanding.md says "Each image is an `input_image` content part whose `image_url` can either be a URL or a base64-encoded data URL." It recommends putting text first, then images, in the user message.

Confirmed: the Chat Completions shape uses a nested `image_url` object with a `url` key. The Responses shape uses a flat string. Do not mix them.

---

## 3. OpenRouter structured outputs

Status: **confirmed**.

Sources:
- https://openrouter.ai/docs/guides/features/structured-outputs.md (fetched 2026-11-10).
- https://openrouter.ai/docs/guides/routing/provider-selection.md (provider routing, `require_parameters`).
- https://openrouter.ai/docs/api/api-reference/chat/create-a-chat-completion.md (request body field `provider` refers to `ProviderPreferences`, which contains `require_parameters`).

Chat Completions `response_format` shape, quoted from the guide:

```json
{
  "messages": [{"role": "user", "content": "What's the weather like in London?"}],
  "response_format": {
    "type": "json_schema",
    "json_schema": {
      "name": "weather",
      "strict": true,
      "schema": {
        "type": "object",
        "properties": {"location": {"type": "string"}, "temperature": {"type": "number"}, "conditions": {"type": "string"}},
        "required": ["location", "temperature", "conditions"],
        "additionalProperties": false
      }
    }
  }
}
```

Responses API equivalent: `"text": {"format": {"type": "json_schema", "name": "...", "strict": true, "schema": {...}}}`.

Provider option: `require_parameters` (boolean, default `false`). Quoted from the provider-selection guide: "When you set `require_parameters` to `true`, the request won't even be routed to that provider." Example body from the same page: `"provider": {"require_parameters": true}`.

Guide wording to note: "Support is determined per endpoint, not just per model." Endpoint support can change. Set `require_parameters: true` to route only to endpoints that support the parameters.

Not confirmed: whether `require_parameters: true` plus `response_format` changes behaviour for `meta/muse-*` at call time. Only one endpoint exists per model, so the option cannot change the route.

---

## 4. Package currency

Status: **confirmed** for latest versions (PyPI and `uv tree --outdated`). **Not confirmed** for `uv.lock` pins in the project, because the file does not exist.

Sources:
- `uv tree --outdated --depth 1` run in a scratch copy with the project's `pyproject.toml` and `README.md` (uv 0.13.5, 2026-10-21 build). The project itself has no `uv.lock`. Running uv there would create one, so I did not.
- PyPI JSON: https://pypi.org/pypi/<name>/json, fetched 2026-11-10.

Result of `uv tree --outdated --depth 1`: no package is marked `(latest: ...)`. All direct dependencies resolve to their latest PyPI release.

| package | pyproject constraint | resolved in scratch lock | PyPI latest | release date (latest) | outdated? |
|---|---|---|---|---|---|
| fastapi | >=0.162.2 | 0.162.2 | 0.162.2 | 2026-11-07 | no |
| uvicorn | >=0.54.0 | 0.54.0 | 0.54.0 | 2026-09-25 | no |
| httpx | >=0.28.1 | 0.28.1 | 0.28.1 | 2024-12-06 | no |
| pydantic | >=2.14.1 | 2.14.3 | 2.14.3 | 2026-11-05 | no |
| python-multipart | >=0.0.33 | 0.0.33 | 0.0.33 | 2026-10-31 | no |
| pytest (dev) | >=9.2.0 | 9.2.0 | 9.2.0 | 2026-10-27 | no |
| pytest-xdist (dev) | >=3.8.0 | 3.8.0 | 3.8.0 | 2025-07-01 | no |
| ruff (dev) | >=0.17.4 | 0.17.4 | 0.17.4 | 2026-11-05 | no |
| starlette (transitive via fastapi) | n/a | 1.10.0 | 1.10.0 | 2026-10-24 | no |

Transitive pins from the same scratch lock (`<scratch dir>`): anyio 4.16.0, h11 0.16.0, click 8.5.1, pydantic-core 2.50.4, typing-extensions 4.16.0, opentelemetry-api 1.45.2.

Not confirmed: the project's `uv.lock` pins. The file is absent. Once any agent runs `uv sync` or `uv run` in the project, it will be created with the versions above, subject to whatever `uv` resolves at that time.

Not upgraded: nothing in the project was changed.

---

## 5. Known issues and advisories

Status: **confirmed**: no published advisory affects the resolved versions of the direct dependencies or starlette. Details below.

Sources:
- OSV query: `POST https://api.osv.dev/v1/query` for each package at its resolved version (2026-11-10). Result: 0 vulnerabilities for python-multipart 0.0.33, starlette 1.10.0, fastapi 0.162.2, uvicorn 0.54.0, httpx 0.28.1, pydantic 2.14.3, pytest 9.2.0, pytest-xdist 3.8.0, ruff 0.17.4.
- GitHub advisory database: `https://api.github.com/advisories?ecosystem=pip&affects=<package>` (2026-11-10).
- Release list: https://api.github.com/repos/Kludex/python-multipart/releases and https://api.github.com/repos/fastapi/fastapi/releases (titles and dates only; release bodies were not read).

### python-multipart (pinned 0.0.33)

9 GitHub advisories. The highest first-patched version is 0.0.31 (GHSA-v9pg-7xvm-68hf, Negative Content-Length buffers the body). Every advisory has a first-patched version at or below 0.0.31, so 0.0.33 is above all of them. Notable entries: GHSA-5rvq-cxj2-64vf (CVE-2026-53539, high, quadratic parsing, fixed 0.0.30); GHSA-pp6c-gr5w-3c5g (CVE-2026-42561, high, unbounded part headers, fixed 0.0.27).

Confirmed: 0.0.33 is not in any listed vulnerable range. Latest release: 0.0.33 (2026-10-31), preceded by 0.0.32 (2026-06-04) and 0.0.31 (2026-06-04).

### starlette (resolved 1.10.0, via fastapi)

13 GitHub advisories. The highest first-patched version is 1.3.1 (GHSA-82w8-qh3p-5jfq, CVE-2026-54283, high: `request.form()` limits ignored for urlencoded forms). Other 2026 entries: GHSA-wqp7-x3pw-xc5r (CVE-2026-48818, high, Windows UNC paths in StaticFiles, fixed 1.1.0); GHSA-x746-7m8f-x49c (CVE-2026-48817, fixed 1.1.0); GHSA-jp82-jpqv-5vv3 (fixed 1.3.0); GHSA-86qp-5c8j-p5mr (fixed 1.0.1). 1.10.0 is above all of them. OSV also reports 0 vulnerabilities for 1.10.0.

Confirmed: 1.10.0 is not in any listed vulnerable range.

### fastapi (resolved 0.162.2)

2 GitHub advisories, both old (GHSA-8h2j-cgx8-6xv7, CVE-2021-32677, fixed 0.65.2; GHSA-qf9m-vfgh-m389, fixed 0.109.1). Confirmed: not affected. Release list: 0.162.2 (2026-11-07), 0.162.1 (2026-11-07), 0.162.0 (2026-10-23).

### Not confirmed in this section

- The fastapi and python-multipart release notes were not read. Only release titles and dates were checked, so I cannot say whether a release note mentions a security fix.
- Advisory data is a point-in-time check. The `affects=` filter may miss entries; OSV was used as a cross-check.
- Multipart form handling (`request.form()`) is covered by the advisories above. The project's own upload routes were not tested in this check.

---

## 6. Python version

Status: **requires-python confirmed**. **`uv run python --version` reports 3.15.1, not 3.14.x: NOT confirmed (wrong version).**

Sources and commands:
- `pyproject.toml`: `requires-python = ">=3.14"`. Confirmed.
- Run in a scratch copy (`.../scratchpad/verify_copy2/`, with `pyproject.toml`, `README.md`, `src/`) because `uv run` in the project would write `.venv` and `uv.lock`.
  - `uv run python --version` gave `Python 3.15.1` (`Using CPython 3.15.1`).
  - `uv run --python 3.14 python --version` gave `Python 3.14.9`.
  - `uv python find 3.14` returns `~/.local/share/uv/python/cpython-3.14-macos-aarch64-none/bin/python3.14`.
- The project has no `.python-version`, so uv chooses the newest interpreter that satisfies `>=3.14`.

Consequence: `uv run python` in the project will run 3.15.1. The global instruction says new projects default to the latest stable CPython uv provides and names 3.14 as current. These disagree. Pinning would be `uv python pin 3.14`, which writes `.python-version`. I did not run that.

Note: an earlier check in a copy without `src/` failed with "Expected a Python module at: src/proofmode/__init__.py". That was my copy error. At the start of the session the project's `src/proofmode/__init__.py` defined `def main()`, matching `[project.scripts] proofmode = "proofmode:main"`.

Mid-session change (observed 2026-11-10 while checking): another agent edited `pyproject.toml` (586 to 595 bytes). The script entry is now `proofmode = "proofmode.__main__:main"`, and `src/proofmode/__main__.py` defines `def main()` at line 10. The dependency pins and `requires-python` did not change. The check of the Python version is unaffected.

---

## Items not confirmed (consolidated)

1. Project `uv.lock` pins: file absent. Confirmed only for a fresh resolution in a scratch copy.
2. `uv run python --version` reports 3.14.x: **not confirmed**. It reports 3.15.1 (see section 6).
3. Image input and structured-output enforcement on `meta/muse-*`: confirmed at model-list level only. No live call was made.
4. Meaning of endpoint `status: 0`: not defined in the pages read.
5. fastapi and python-multipart release-note bodies: not read; only titles and dates.
6. Advisory coverage: point-in-time, from GitHub advisories and OSV. Not a full security audit.

## Method notes

- `curl` fetches: `https://openrouter.ai/api/v1/models`, `https://openrouter.ai/docs/llms.txt`, `https://openrouter.ai/docs/_llms/docs.txt`, `https://openrouter.ai/docs/_llms/api-reference.txt`, `https://openrouter.ai/docs/openapi/openapi.yaml`, several `openrouter.ai/docs/*.md` pages, the two per-model endpoint URLs, PyPI JSON, OSV, and GitHub API. All files were saved to the scratchpad and parsed with `uv run --no-project python -I`.
- Other agents changed the project during this session: `tests/` and `src/` gained files, `pyproject.toml` changed its script entry (see section 6), and `.pytest_cache/` and `.ruff_cache/` appeared at 18:40. I ran no pytest or ruff in the project and did not read or modify those files. Those caches are from other agents' runs.
- No `Co-Authored-By` or agent attribution was added. No commit was made.
