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
python ./scripts/launcher.py
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
To be announced :)
