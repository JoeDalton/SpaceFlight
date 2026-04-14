# SpaceFlight

https://github.com/JoeDalton/SpaceFlight

## Description

An attempt at a home made space combat flight simulator (heavily) inspired by Star Wars Squadrons, using python!

At the moment, most graphical assets are borrowed from assets licenced as Creative Commons. Licence files are kept alongside the assets themselves.

![alt text](https://https://github.com/JoeDalton/SpaceFlight/blob/main/docs/asteroid_screenshot.png?raw=true)


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

* To run all the tests in dedicated virtualenv, with all supported python versions:

    `invoke testall`

* To check the code cover:

    `invoke cover`

* To run precommit hooks, to check the quality:

    `invoke quality`

* To deploy :
  * `invoke deploy` deploys a version to your pypiserver - should preferrably be done by the CI

* To clean the build:
 
    `invoke clean`
    
* To add / remove a dependency:

    `poetry add/remove dependency`

  * If this is a test dependency, do `poetry add/remove dependency --test`
  * If this is a development dependency, do `poetry add/remove dependency --dev`

* To update from the template:
  * `cruft update`

  # User
  To be announced :)