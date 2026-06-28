import datetime
import platform
import shutil
from pathlib import Path

from invoke import task

@task()
def develop(c):
    c.run("poetry install")
    c.run("poetry run pre-commit install")


@task
def test(c):
    c.run("poetry run pytest tests/")


@task()
def install(c):
    c.run("poetry install --without dev,test")


@task
def quality(c):
    c.run("poetry run pre-commit run --all-files")


@task
def check_env(c):
    c.run("pip freeze |grep numpy ; pip freeze |grep scipy ; pip freeze |grep airthium")


@task
def deploy(c):
    c.run("poetry publish --build --repository airthium")


@task
def cover(c):
    c.run(
        "poetry run pytest tests -v --cov-report term --cov-report html:htmlcov --cov-report xml --cov=./src/"
    )
    c.run("poetry run coverage report")
    c.run("poetry run coverage xml")


# @task
# def deploydirty(c):
#     c.run("rm -rf dist/*")
#     c.run("python setup.py clean")
#     date = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
#     c.run(f"python setup.py egg_info -b{date} sdist bdist_wheel")
#     targz_to_move = next(Path("./dist").glob("*.tar.gz"))

#     is_on_windows = "Windows" in platform.system()

#     if is_on_windows:
#         dirty_packages_dir = str(
#             Path("//SRV-DATA01/Commun/99_ECHANGE/Digital/dirty_packages")
#         )
#     else:
#         dirty_packages_dir = str(
#             Path("/media/Commun/99_ECHANGE/Digital/dirty_packages")
#         )
#     print(f"Moving {targz_to_move} to {dirty_packages_dir}/{targz_to_move.name}")
#     shutil.move(str(targz_to_move), dirty_packages_dir)


@task
def doc(c, path=r"./docs"):
    pass

@task
def clean(c):
    shutil.rmtree("build", ignore_errors=True)
    shutil.rmtree("dist", ignore_errors=True)
    shutil.rmtree("iframe_figures", ignore_errors=True)
    shutil.rmtree("target", ignore_errors=True)