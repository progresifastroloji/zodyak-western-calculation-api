# Public Deployment Checklist

Use this checklist before exposing the calculation service to public users.

## Required

- Publish the complete corresponding source code for the exact running version.
- Set `WESTERN_CALC_SOURCE_CODE_URL` to that public repository or source archive.
- Keep `LICENSE` and `NOTICE` in the published source.
- Before final publication, replace or expand `LICENSE` with the canonical full
  AGPL-3.0 license text from the Free Software Foundation if your hosting or
  legal review requires the full text to be bundled rather than linked.
- Keep `/source`, `/license`, and `/schema` reachable to network users.
- Keep private vault records, customer files, prompts, methodology notes, and
  interpretation copy outside this AGPL service.

## Verify

```bash
python -m unittest discover tests
```

```bash
python -m zodyak_western_calculation_api.readiness --public
```

```bash
curl -s http://127.0.0.1:5010/source
```

The `/source` response should show:

- `source_code_url_configured: true`
- `source_code_url` pointing to the public source for the deployed version
- `agpl_network_source_obligation: true`

## Do Not Publish If

- `source_code_url_configured` is false.
- The source URL points to a placeholder, private repository, or different code
  version.
- Closed app code, vault content, prompts, or commercial packaging files have
  been copied into this service.
