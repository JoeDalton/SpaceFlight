# SpaceFlight

https://github.com/JoeDalton/SpaceFlight

## Description

A home-made space combat flight simulator, heavily inspired by Star Wars Squadrons, written in Python.

Most graphical assets are borrowed from Creative Commons sources; their licence files sit alongside the assets.

<img width="2560" height="1440" alt="asteroid_screenshot" src="https://github.com/user-attachments/assets/75727762-0fe6-4b0f-b97e-f969cc833e30" />

# User

## Windows user

To install and run the game without a development environment, use the scripts in `MS_Windows_install/`. They install from your local clone, so you need the full repository on disk, not just that folder.

1. Clone (or download) this repository.
2. Run `1.1_test_python_installation.bat` to check that Python 3.12, 3.13 or 3.14 is on your `PATH`. If not, install it from [python.org](https://www.python.org/downloads/) and check "Add Python to PATH" during installation.
3. Run `2_install_space_flight.bat`. It creates a virtual environment (`venv`) in the folder and installs SpaceFlight and its dependencies.
4. Run `3.1_launch_space_flight.bat` to start the game.

Other scripts:
* `3.2_open_space_flight_environment.bat` opens a console with the game's virtual environment activated.
* `4_update_space_flight.bat` reinstalls SpaceFlight after a `git pull`, picking up new or updated dependencies.

The scripts bypass `poetry-dynamic-versioning`, which normally calls `git` during `pip install` to compute the version, so they don't need git themselves; you still need it to clone and pull.

# Developer

## Installation

Requires Python 3.12, 3.13 or 3.14.

```
pip install poetry
python3 -m venv <venv_name>
```
Activate the virtual environment, then:
```
pip install invoke
invoke develop
```

## Running the game

With the environment activated:
```
space_flight
```

## Development

| Command | Purpose |
| --- | --- |
| `invoke test` | Run the tests |
| `invoke coverage` | Run the tests with coverage (terminal, `htmlcov/` and `coverage.xml`) |
| `invoke quality` | Run the pre-commit hooks (ruff lint and format, file checks) |
| `invoke doc` | Build the Sphinx docs into `docs/build/latest` and `docs/build/<version>` |
| `invoke profile` | Profile the dev level into `profiles/dev_level.prof` (view with `snakeviz`) |
| `invoke deploy` | Publish a build to the `space_flight` Poetry repository (preferably done by the CI) |
| `invoke clean` | Remove build artefacts |

To add or remove a dependency: `poetry add/remove <dependency>`, with `--group test`, `--group dev` or `--group docs` for test, development or documentation dependencies.

`src/space_flight/_version.py` is auto-generated and must never be committed with local changes. Right after cloning, run once:

    git update-index --skip-worktree src/space_flight/_version.py

Git then ignores local modifications to it. The setting is per clone; undo it with `git update-index --no-skip-worktree src/space_flight/_version.py`.
