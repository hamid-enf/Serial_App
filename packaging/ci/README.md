# CI workflows (staged here, not yet active)

> Building the executable locally instead? See [`docs/BUILD.md`](../../docs/BUILD.md).

These two workflow files are ready to use but live outside `.github/workflows/`,
because the automated account that authored them is not allowed to create or
update workflow files — GitHub rejects such a push with:

```
refusing to allow a GitHub App to create or update workflow
`.github/workflows/build-windows.yml` without `workflows` permission
```

Activating them takes one command from a normal (human) clone:

```bash
mkdir -p .github/workflows
git mv packaging/ci/build-windows.yml packaging/ci/tests.yml .github/workflows/
git commit -m "Enable CI workflows"
git push
```

You can also paste them into **GitHub → Actions → New workflow → set up a
workflow yourself**, which has the same effect through the web UI.

## What each one does

| File | Trigger | Result |
| --- | --- | --- |
| `tests.yml` | push / pull request | `pytest` (411 tests) on Linux and Windows, plus `ruff` and `mypy` |
| `build-windows.yml` | push to a tag `v*`, or manual dispatch | Builds the portable `.exe`, the one-folder build and the Inno Setup installer on `windows-latest`, uploads them as artifacts, and attaches them to the release when the trigger was a tag |

Once `build-windows.yml` is in place, a release is:

```bash
git tag v1.0.0
git push origin v1.0.0
```

and the signed-off artifacts appear under **Releases** a few minutes later.
