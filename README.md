# Zodyak Western Calculation API

Open-source technical calculation service for Western astrology.

This service is intended to contain only the Swiss Ephemeris-backed calculation
layer. It must not contain private vault records, customer data, proprietary
methodology notes, GPT prompts, interpretation copy, or commercial packaging
logic.

## License Model

Service license: AGPL-3.0-or-later.

Ephemeris dependency: Swiss Ephemeris / pyswisseph. Swiss Ephemeris is offered
by Astrodienst under a dual license model: AGPL or Swiss Ephemeris Professional
License. This service is prepared for the AGPL path.

## Initial API Surface

- `GET /healthz`
- `GET /license`
- `GET /source`
- `GET /schema`
- `POST /calculate/natal`
- `POST /calculate/transits`
- `POST /calculate/solar-return`
- `POST /calculate/lunar-return`
- `POST /calculate/progressions`
- `POST /calculate/solar-arc`
- `POST /calculate/primary-directions`
- `POST /calculate/firdaria`
- `POST /calculate/midpoints`
- `POST /calculate/parans`
- `POST /calculate/synastry`
- `POST /calculate/composite`
- `POST /calculate/davison`
- `POST /calculate/relocation`
- `POST /calculate/astrocartography`
- `POST /calculate/local-space`
- `POST /calculate/horary`
- `POST /calculate/electional`
- `POST /calculate/mundane`
- `POST /calculate/rectification`
- `POST /calculate/forecast-layers`

Current migration status:

- `/calculate/natal`: available, backed by the migrated technical natal core
- `/calculate/transits`: available, backed by the migrated technical transit core
- `/calculate/solar-return`: available
- `/calculate/lunar-return`: available
- `/calculate/progressions`: available
- `/calculate/solar-arc`: available
- `/calculate/primary-directions`: available
- `/calculate/firdaria`: available
- `/calculate/midpoints`: available
- `/calculate/parans`: available
- `/calculate/synastry`: available
- `/calculate/composite`: available
- `/calculate/davison`: available
- `/calculate/relocation`: available
- `/calculate/astrocartography`: available
- `/calculate/local-space`: available
- `/calculate/horary`: available
- `/calculate/electional`: available
- `/calculate/mundane`: available
- `/calculate/rectification`: available
- `/calculate/forecast-layers`: available, backed by migrated technical timing layers

## Boundary

Open service:

- natal calculation
- transit calculation
- solar return calculation
- lunar return calculation
- secondary progressions
- solar arc directions
- primary directions
- Firdaria
- midpoints
- parans
- synastry
- composite
- Davison
- relocation
- astrocartography
- local space
- horary
- electional
- mundane
- rectification candidate evidence
- technical forecast layers
- raw technical JSON
- license notices and tests

Closed app:

- vault writes
- customer files
- methodology notes
- GPT instructions
- interpretation and advisor language
- commercial workflows

## Local Run

```bash
python -m zodyak_western_calculation_api.app
```

For a public AGPL deployment, set the source URL to the exact public repository
or archive for the running version:

```bash
export WESTERN_CALC_SOURCE_CODE_URL="https://github.com/progresifastroloji/zodyak-western-calculation-api"
```

If this value is not set, `/source` reports that the public source URL is not
configured yet.

## Production Run

```bash
gunicorn "zodyak_western_calculation_api.app:app" --bind "0.0.0.0:${PORT:-5010}"
```

Docker:

```bash
docker build -t zodyak-western-calculation-api .
docker run -p 5010:5010 \
  -e WESTERN_CALC_SOURCE_CODE_URL="https://github.com/progresifastroloji/zodyak-western-calculation-api" \
  zodyak-western-calculation-api
```

## Public Readiness Check

Local development check:

```bash
python -m zodyak_western_calculation_api.readiness
```

Final public deployment check:

```bash
python -m zodyak_western_calculation_api.readiness --public
```

The public check fails unless `WESTERN_CALC_SOURCE_CODE_URL` is configured.

## Example Requests

```bash
curl -s http://127.0.0.1:5010/calculate/natal \
  -H "Content-Type: application/json" \
  --data @examples/natal.json
```

```bash
curl -s http://127.0.0.1:5010/calculate/transits \
  -H "Content-Type: application/json" \
  --data @examples/transits.json
```

```bash
curl -s http://127.0.0.1:5010/calculate/solar-return \
  -H "Content-Type: application/json" \
  --data @examples/solar-return.json
```

```bash
curl -s http://127.0.0.1:5010/calculate/lunar-return \
  -H "Content-Type: application/json" \
  --data @examples/lunar-return.json
```

```bash
curl -s http://127.0.0.1:5010/calculate/progressions \
  -H "Content-Type: application/json" \
  --data @examples/progressions.json
```

```bash
curl -s http://127.0.0.1:5010/calculate/solar-arc \
  -H "Content-Type: application/json" \
  --data @examples/solar-arc.json
```

```bash
curl -s http://127.0.0.1:5010/calculate/primary-directions \
  -H "Content-Type: application/json" \
  --data @examples/primary-directions.json
```

```bash
curl -s http://127.0.0.1:5010/calculate/firdaria \
  -H "Content-Type: application/json" \
  --data @examples/firdaria.json
```

```bash
curl -s http://127.0.0.1:5010/calculate/midpoints \
  -H "Content-Type: application/json" \
  --data @examples/midpoints.json
```

```bash
curl -s http://127.0.0.1:5010/calculate/parans \
  -H "Content-Type: application/json" \
  --data @examples/parans.json
```

```bash
curl -s http://127.0.0.1:5010/calculate/synastry \
  -H "Content-Type: application/json" \
  --data @examples/synastry.json
```

```bash
curl -s http://127.0.0.1:5010/calculate/composite \
  -H "Content-Type: application/json" \
  --data @examples/composite.json
```

```bash
curl -s http://127.0.0.1:5010/calculate/davison \
  -H "Content-Type: application/json" \
  --data @examples/davison.json
```

```bash
curl -s http://127.0.0.1:5010/calculate/relocation \
  -H "Content-Type: application/json" \
  --data @examples/relocation.json
```

```bash
curl -s http://127.0.0.1:5010/calculate/astrocartography \
  -H "Content-Type: application/json" \
  --data @examples/astrocartography.json
```

```bash
curl -s http://127.0.0.1:5010/calculate/local-space \
  -H "Content-Type: application/json" \
  --data @examples/local-space.json
```

```bash
curl -s http://127.0.0.1:5010/calculate/horary \
  -H "Content-Type: application/json" \
  --data @examples/horary.json
```

```bash
curl -s http://127.0.0.1:5010/calculate/electional \
  -H "Content-Type: application/json" \
  --data @examples/electional.json
```

```bash
curl -s http://127.0.0.1:5010/calculate/mundane \
  -H "Content-Type: application/json" \
  --data @examples/mundane.json
```

```bash
curl -s http://127.0.0.1:5010/calculate/rectification \
  -H "Content-Type: application/json" \
  --data @examples/rectification.json
```

```bash
curl -s http://127.0.0.1:5010/calculate/forecast-layers \
  -H "Content-Type: application/json" \
  --data @examples/forecast-layers.json
```

## Test

```bash
python -m unittest discover tests
```
