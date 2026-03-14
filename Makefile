.PHONY: setup build test clean

setup:
	pyenv virtualenv -f 3.13 jiractl
	pyenv local jiractl
	pip install setuptools
	pip install -e ".[dev]"
	pip install -r requirements.dev.txt
	pre-commit install

install:
	pip install setuptools
	pip install -r requirements.dev.txt
	pip install -e ".[dev]"

build:
	python3 -m build

test:
	pytest tests

clean:
	rm -rf dist build jiractl.egg-info

lint:
	pre-commit run --all-files
