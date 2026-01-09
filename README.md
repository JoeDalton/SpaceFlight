# sensoracquisition

https://github.com/Airthium/sensoracquisition

## Description

A library to centralise the post-processing of raw sensor data


# User 

## Dependencies

## Installation

`pip install .`

## Documentation

To use the project:

    from sensoracquisition import cli
    cli.main()

# Developer

## Installation

* Install poetry:
    Avec le pip du système: 
    ```
    pip install pipx
    pipx ensurepath
    pipx install poetry
    ```
    * `pipx ensurepath` can tell you it failed at setting the path and that you should do it by hand, in that case, do it !
* `poetry install`
* poetry can handle your virtual environment :

    `poetry shell`

    Or you can use your own venv.

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