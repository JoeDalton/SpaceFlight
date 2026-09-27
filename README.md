# SpaceFlight

https://github.com/JoeDalton/SpaceFlight

## Description

An attempt at a home made space combat flight simulator (heavily) inspired by Star Wars Squadrons, using python!

At the moment, most graphical assets are borrowed from assets licenced as Creative Commons. Licence files are kept alongside the assets themselves.

<img width="2560" height="1440" alt="asteroid_screenshot" src="https://github.com/user-attachments/assets/75727762-0fe6-4b0f-b97e-f969cc833e30" />



# Developer

## Installation
Ensure you have python >= 3.12

With the system's python 3 pip: 
```
pip install poetry
python3 -m venv <your_prefered_virtual_environment_name>
```
Activate your new virtual environment
```
pip install invoke
invoke develop
```

## Running the game 
In the projects directory, with the environment activated
```
space_flight
```

## Development 
* To run the tests:

    `invoke test`

* To check the code coverage:

    `invoke coverage`

* To run precommit hooks, to check the quality:

    `invoke quality`

* To build the documentation (Sphinx, written to `docs/build/latest`):

    `invoke doc`

* To deploy :
  * `invoke deploy` publishes a build to the `airthium` Poetry repository - should preferrably be done by the CI

* To clean the build:
 
    `invoke clean`
    
* To add / remove a dependency:

    `poetry add/remove dependency`

  * If this is a test dependency, do `poetry add/remove --group test dependency`
  * If this is a development dependency, do `poetry add/remove --group dev dependency`
  * If this is a documentation dependency, do `poetry add/remove --group docs dependency`

* `src/space_flight/_version.py` is auto-generated and should never be committed with local changes. Right after cloning, run:

    `git update-index --skip-worktree src/space_flight/_version.py`

  This tells git to ignore local modifications to this file (it will no longer show up in `git status`/`git diff`). It's a local, per-clone setting, so each contributor needs to run it once. To undo it: `git update-index --no-skip-worktree src/space_flight/_version.py`.

# User

## Windows user

If you don't want to set up a full development environment, you can install and run the game from a local clone of this repository using the scripts in `MS_Windows_install/`.

1. Clone (or download) this repository onto your machine.
2. Open the `MS_Windows_install` folder and double-click `1.1_test_python_installation.bat` to check that a compatible Python (3.12, 3.13 or 3.14) is installed and on your `PATH`. If it isn't, install it from [python.org](https://www.python.org/downloads/) and make sure to check "Add Python to PATH" during installation.
3. Double-click `2_install_space_flight.bat`. This creates a local virtual environment (`venv`) inside the folder and installs SpaceFlight and its dependencies from your local clone.
4. Double-click `3.1_launch_space_flight.bat` to start the game.

Other scripts in that folder:
* `3.2_open_space_flight_environment.bat` opens a console with the game's virtual environment already activated, useful if you want to run commands manually.
* `4_update_space_flight.bat` reinstalls SpaceFlight after you've pulled the latest changes (`git pull`) into your local clone, picking up any new or updated dependencies.

Since installation happens from your local clone rather than a package index, you need the full repository on disk (not just the `MS_Windows_install` folder) for these scripts to work.

Note: `pip install` normally invokes `git` to determine the package's version (via `poetry-dynamic-versioning`). The `MS_Windows_install` scripts bypass this, so a system `git` installation is not required to run them — you'll still need git separately to clone/pull the repository itself.
