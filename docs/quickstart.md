# Quickstart

## Install

```bash
git clone <repo> parser-universal
cd parser-universal
python -m venv .venv
. .venv/bin/activate
pip install -e ".[dev,db]"
```

## Run a smoke test

The bundled `configs/smoke.yaml` runs a `dryrun`-mode GPX load:

```bash
parser-cli run-config configs/smoke.yaml
```

Expected JSON output:

```json
{
  "mode": "sequential",
  "source": "parser_universal_smoke",
  "sink": "dryrun",
  "locators": 1,
  "rows_inserted": 1,
  "rows_failed": 0
}
```

## Use as a library

```python
import asyncio
from parser_universal.adapters.url_dispatch import URLCoordAdapter
from parser_universal.fetcher.persistent import PersistentHTTPClient
from parser_universal.fetcher.safe import SafeFetcher
from parser_universal.fetcher.strategies.httpx_persistent_impl import make_persistent_httpx
from parser_universal.orchestrator import DryRunSink, ParserOrchestrator
from parser_universal.rate_limiter.async_impl import AsyncRateLimiter

async def main():
    async with PersistentHTTPClient() as p:
        fetcher = SafeFetcher(strategies=[make_persistent_httpx(p)])
        rl = AsyncRateLimiter(rate_per_sec=2.0, burst=4)
        orch = ParserOrchestrator(
            adapter=URLCoordAdapter(),
            sinks=[DryRunSink()],
            fetcher=fetcher,
            rate_limiter=rl,
            source_name="my_pipeline",
        )
        res = await orch.run(["https://yandex.ru/maps/?ll=37.6173,55.7558"])
        print(f"inserted={res.rows_inserted} failed={res.rows_failed}")

asyncio.run(main())
```

## Postgres integration

```bash
export POSTGRES_DSN='postgresql://user:pass@host:5432/dbname'
parser-cli run-config configs/my_pipeline.yaml --sink postgres
```

Required schema is documented in [Architecture](architecture.md#postgres-schema).
