.PHONY: setup build test clean

setup:
	pyenv virtualenv -f 3.13 jiractl
	pyenv local jiractl
	pip install .

install:
	pip install .

build:
	python3 -m build

test:
	pytest tests

clean:
	rm -rf dist build jiractl.egg-info
