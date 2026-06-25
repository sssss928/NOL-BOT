# nol-ticket-bot

NOL World ticket monitor and guarded purchase helper.

This refactor keeps the public CLI compatible:

```bash
nol-bot check
nol-bot monitor
nol-bot buy
nol-bot run
```

## Install

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -e .
```

For development:

```bash
python -m pip install -e ".[dev]"
ruff check src tests
mypy src tests
pyright
pytest
```

## Configuration

Copy `.env.example` to `.env` and edit the values:

```bash
cp .env.example .env
```

Important fields:

| Name | Purpose |
| --- | --- |
| `GOODS_CODE` | NOL goods code. |
| `PLACE_CODE` | NOL place code. |
| `BIZ_CODE` | NOL business code. |
| `SEAT_GRADE_PREFERENCE` | Preferred seat grades, comma separated. |
| `MAX_TICKETS` | Number of seats to select, validated as 1-10. |
| `POLL_INTERVAL` | Initial salesinfo polling interval in seconds. |
| `QUEUE_TIMEOUT` | Maximum token/queue wait in seconds. |
| `STOP_BEFORE_PAYMENT` | If `true`, stop before payment and let the user finish manually. |
| `CONFIRM_BEFORE_PAYMENT` | If payment is automated, require typing `PAY` before clicking payment. |

The loader first checks the current working directory for `.env`, so installed CLI usage works
without relying on the package source path. `NOL_BOT_ENV_FILE=/path/to/file` can override this.

## Safety

- URLs in logs are redacted. Sensitive query/path values such as `partner_token`,
  `partner_token_r`, `user_id`, `session`, and order identifiers are not emitted.
- `purchase.run()` returns a `PurchaseResult` with `status`, `step`, `failure_reason`,
  `selected_count`, and a redacted final URL.
- Seat clicks are counted only after the DOM reports a selected marker or selected count increase.
- tokenVerify and queue waits use host allowlists, deny markers, and DOM markers instead of raw URL
  substring checks alone.

## CI and Releases

GitHub Actions are included:

- `.github/workflows/ci.yml` runs ruff, mypy, pyright, and pytest with coverage.
- `.github/workflows/release.yml` builds sdist/wheel and publishes a GitHub Release for tags like
  `v0.2.0`.

To release:

```bash
git tag v0.2.0
git push origin main --tags
```

## Testing Without Real Accounts

The test suite uses mocks and fake page/client objects. It does not require a real NOL account,
real queue, payment page, or real Chromium browser.
