# FedMed task runner.
#
# Every target is a thin wrapper around a script, so nothing here is required.
# If make is not installed (common on Windows), run the script in the recipe
# directly and you get exactly the same result.

SHELL := /bin/bash
PYTHON ?= python
VENV ?= .venv

.DEFAULT_GOAL := help
.PHONY: help setup data certs test lint local compose compose-down experiments \
        tf-init tf-repos tf-apply tf-output push upload web run stop teardown clean

help: ## Show this list
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

# ------------------------------------------------------------------ local

setup: ## Create the virtualenv and install everything
	$(PYTHON) -m venv $(VENV)
	$(VENV)/Scripts/python.exe -m pip install --upgrade pip || $(VENV)/bin/python -m pip install --upgrade pip
	$(VENV)/Scripts/python.exe -m pip install -r requirements-dev.txt || $(VENV)/bin/python -m pip install -r requirements-dev.txt

data: ## Download PneumoniaMNIST and split it across three hospitals
	$(PYTHON) scripts/partition_data.py

certs: ## Mint the self-signed CA and aggregator certificate
	./scripts/gen_certs.sh

test: ## Run the test suite
	$(PYTHON) -m pytest

local: ## Run the federation as plain processes, no Docker
	$(PYTHON) scripts/run_local.py --rounds 10 --dp

compose: ## Run the federation as containers, the way Fargate will
	# The two flags stop the stack when the aggregator finishes. Without them
	# compose stays attached to the inference API, which never exits, and the
	# terminal looks frozen long after training is done.
	docker compose up --build --abort-on-container-exit --exit-code-from fl-server

compose-down: ## Stop the compose stack and remove its containers
	docker compose down -v

experiments: ## Produce the evaluation table and figures for the report
	$(PYTHON) scripts/run_experiments.py

# -------------------------------------------------------------------- aws

tf-init: ## Initialise Terraform
	terraform -chdir=infra init

tf-repos: ## Phase one: create only the ECR repositories, so images can be pushed
	terraform -chdir=infra apply -target=aws_ecr_repository.this

tf-apply: ## Phase two: create everything else
	terraform -chdir=infra apply

tf-output: ## Show the stack's outputs
	terraform -chdir=infra output

push: ## Build the three images and push them to ECR
	./scripts/push_images.sh

upload: ## Copy each hospital's shard into its own bucket
	./scripts/upload_data.sh

web: ## Build the dashboard against the deployed API and publish it
	./scripts/deploy_web.sh

run: ## Start one federated training run on Fargate
	./scripts/start_run.sh

stop: ## Stop every running task. Run this before you close the lab
	./scripts/stop_run.sh

teardown: ## Destroy the whole stack
	./scripts/teardown.sh

# ------------------------------------------------------------------ chores

clean: ## Remove generated artifacts, keeping the datasets
	rm -rf artifacts dashboard/dist .fedmed-run
