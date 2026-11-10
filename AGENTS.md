# Repository Guidelines

## Project Structure & Module Organization

This repository provides the Home Assistant `cul_max` custom integration for MAX! devices connected through CUL/CUNO over TCP.

- `custom_components/cul_max/`: integration source. `__init__.py` handles setup and services; `config_flow.py` handles configuration; `coordinator.py` manages connections, device state, and command delivery; `protocol.py` encodes and decodes MAX!/MORITZ messages.
- Entity platforms live in modules such as `climate.py`, `sensor.py`, and `binary_sensor.py`; shared constants belong in `const.py`.
- `services.yaml`, `strings.json`, and `manifest.json` describe services, configuration text, and integration metadata.
- `frontend/cul-max-week-profile-card.js` contains the Lovelace card; `brand/` contains image assets.
- `custom_components/cul_max/tests/` contains protocol regression tests. Root `README.md` covers installation; extended English and German guides live alongside the integration.

## Build, Test, and Development Commands

Run commands from the repository root:

```sh
python3 -m unittest discover -s custom_components/cul_max/tests
```

Runs protocol regressions without installing Home Assistant; the tests stub the required Home Assistant constants.

```sh
git diff --check
```

Checks changed files for whitespace errors. There is no configured build pipeline, formatter, or linter. For local integration testing, copy `custom_components/cul_max` into a Home Assistant configuration directory, restart Home Assistant, and add **MAX! via CUL** through Devices & services. The frontend JavaScript is served directly without bundling.

## Coding Style & Naming Conventions

Follow surrounding code: four-space Python indentation, type annotations, module docstrings, `snake_case` functions, `PascalCase` classes, and `UPPER_SNAKE_CASE` constants. Preserve asynchronous Home Assistant APIs and `async_` naming. JavaScript uses two-space indentation, semicolons, and camelCase identifiers. Keep service schemas and documentation aligned with implementation changes.

## Testing Guidelines

Use standard-library `unittest`, with `test_*.py` files and descriptive `test_*` methods. Add regression cases for changed packet bytes, schedule validation, time zones, and boundary conditions. No coverage threshold is configured. Verify connection, pairing, and card changes in Home Assistant with hardware when relevant; report runtime checks separately from unit tests.

## Commit & Pull Request Guidelines

History uses short descriptive subjects such as “Improve setup documentation”; no mandatory commit prefix is established. Keep commits focused. Pull requests should explain the behavior change, link relevant issues, and list validation performed. Include screenshots for card changes and identify any hardware-dependent checks left unverified.
On every commit increase the version in manifest.json so that an update becomes available in the home assistant marketplace after push.
