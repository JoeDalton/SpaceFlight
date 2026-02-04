# spaceflight

https://github.com/JoeDalton/SpaceFlight

## Description

An attempt at a space flight simulator


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
python ./scripts/simulator.py
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
  * `invoke deploy` deploys a version to our pypiserver - should preferrably be done by the CI
  * `invoke deploydirty` deploys a version to /media/Commun/99_ECHANGE/Digital

* To clean the build:
 
    `invoke clean`
    
* To add / remove a dependency:

    `poetry add/remove dependency`

  * If this is a test dependency, do `poetry add/remove dependency --test`
  * If this is a development dependency, do `poetry add/remove dependency --dev`

* To update from the template:
  * `cruft update`