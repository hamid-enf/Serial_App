# Security Policy

## Supported versions

| Version | Supported |
| ------- | --------- |
| 1.0.x   | ✅ |
| < 1.0   | ❌ |

## Reporting a vulnerability

Please **do not** open a public issue for a security problem.

Use GitHub's private reporting instead:
[**Report a vulnerability**](https://github.com/hamid-enf/Serial_App/security/advisories/new).

Include, as far as you can:

- what an attacker can do (impact),
- the steps or file that trigger it,
- the version and operating system you tested on.

You can expect an acknowledgement within **7 days** and a fix or a public
advisory within **90 days**, whichever comes first.

## Scope

This is a desktop application that opens local serial ports and reads and
writes a JSON configuration file. Reports that are in scope include:

- code execution through a crafted configuration file, profile export or
  imported `.json` command set,
- path traversal through the export or log-file dialogs,
- anything that lets remote data arriving on the serial line escape the
  terminal view (for example, being executed or written outside the data
  directory).

Out of scope:

- SmartScreen or antivirus warnings for the unsigned release binary — the
  builds are produced in public CI and are not code-signed; verify the SHA-256
  published with each release,
- issues that require an attacker to already have write access to the user's
  `%APPDATA%` directory,
- crashes without a security impact (please file those as normal bugs).
