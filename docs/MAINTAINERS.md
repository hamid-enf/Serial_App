# Maintainer notes

Everything here is a *repository-level* setting or a release chore — nothing in
this file affects the application itself. It exists so the public presence of
the project stays consistent when it is handed to someone else.

## One-time repository settings

These live in GitHub's settings, not in the code. With the `gh` CLI:

```bash
gh repo edit hamid-enf/Serial_App \
  --description "A professional serial terminal for Windows, Linux and macOS — an Arduino Serial Monitor replacement whose commands become one-click, configurable buttons. Python + PySide6 + pyserial." \
  --enable-wiki=false --enable-projects=false --enable-issues=true \
  --add-topic serial --add-topic serial-port --add-topic serial-monitor \
  --add-topic uart --add-topic pyserial --add-topic pyside6 --add-topic qt \
  --add-topic python --add-topic arduino --add-topic esp32 --add-topic stm32 \
  --add-topic embedded --add-topic electronics --add-topic firmware \
  --add-topic desktop-app --add-topic windows --add-topic developer-tools
```

Or by hand, in **Settings**:

- **About** (top-right of the repository page): description as above, no
  website, tick *Releases* and untick *Packages* and *Deployments*.
- **Features**: Issues on, Wiki off, Projects off. An empty wiki tab makes a
  project look abandoned.
- **Pull requests**: allow squash merging only, tick *Always suggest updating
  pull request branches* and *Automatically delete head branches*.
- **Branches → Add rule** for `main`: require a pull request, require the
  `tests` status check, and do not allow force pushes.
- **Code security**: enable Dependabot alerts, Dependabot security updates and
  secret scanning. Private vulnerability reporting must be **on** for the link
  in `SECURITY.md` to work.
- **Actions → General**: workflow permissions *Read repository contents*, plus
  *Allow GitHub Actions to create and approve pull requests* off.

## Community health files

Already in the repository, and they are what GitHub's *Community Standards*
page checks for:

| File | Purpose |
| --- | --- |
| `README.md` | Front page, badges, install and usage |
| `LICENSE` | MIT |
| `CONTRIBUTING.md` | Development setup and PR rules |
| `CODE_OF_CONDUCT.md` | Contributor Covenant 2.1 |
| `SECURITY.md` | Private disclosure process |
| `CHANGELOG.md` | Keep a Changelog format |
| `.github/ISSUE_TEMPLATE/*.yml` | Bug, feature and question forms |
| `.github/pull_request_template.md` | PR checklist |
| `.github/dependabot.yml` | Monthly pip and Actions updates |

## Cutting a release

```bash
# 1. Update the version in serial_console/__init__.py and packaging/version_info.txt
# 2. Move CHANGELOG entries from "Unreleased" into the new version heading
git commit -am "Release v1.0.0"
git tag -a v1.0.0 -m "v1.0.0"
git push origin main --tags
```

`.github/workflows/build-windows.yml` then builds the portable executable and
the Inno Setup installer on `windows-latest` and attaches both to the release,
together with their SHA-256 sums. Check the artefacts before publishing:

- `SerialCommandConsole-portable.exe --version` prints the new version,
- `SerialCommandConsole-portable.exe --selftest` exits 0.

The binaries are **unsigned**; the release notes should keep the SmartScreen
note so users are not surprised.

## Promotional material

`scripts/promo/` renders the launch clip directly from the real application
(the window is driven frame by frame offscreen, so the footage can never drift
out of date):

```bash
python scripts/promo/build_narration.py            # voice-over track
python scripts/promo/render_promo.py --aspect 16x9 --out promo/clip-16x9.mp4
python scripts/promo/render_promo.py --aspect 9x16 --out promo/clip-9x16.mp4
```

Output lands in `promo/`, which is git-ignored — publish the files on the
release page or a media host rather than committing them.
