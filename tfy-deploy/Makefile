# Deploy super-hype to TrueFoundry with the current git commit as the build ref.
#
# Manifests live per environment in a subdirectory here (e.g. eo/). TrueFoundry
# builds each image from the GitHub repo at image.build_source.ref, so that ref
# must be a commit already pushed to origin. Each manifest is rendered into
# <env>/.rendered/ with its ref set to the SHA; the source .yaml files are left
# untouched.
#
# Usage (from anywhere in the repo):
#   make -C tfy-deploy deploy-eo                # backend, worker, frontend in eo/
#   make -C tfy-deploy deploy-eo SVC=backend    # a single service
#   make -C tfy-deploy deploy ENV=eo SHA=<sha>  # pin an environment and commit
#   make -C tfy-deploy TFY=echo deploy-eo       # dry run (print the tfy commands)

.DEFAULT_GOAL := help

SHA ?= $(shell git rev-parse HEAD)
TFY ?= tfy
ENV ?= eo
SVC ?= backend worker frontend
RENDER := .rendered

.PHONY: help deploy deploy-eo check-pushed

help: ## List available commands
	@echo "Deploy super-hype at ref $(SHA)"
	@echo "  make deploy-eo              Deploy backend, worker, and frontend in eo/"
	@echo "  make deploy-eo SVC=backend  Deploy a single service"
	@echo "  make deploy ENV=<env>       Deploy another environment directory"

deploy-eo: ## Deploy the eo environment (all services, or SVC=<name>)
	@$(MAKE) --no-print-directory deploy ENV=eo

deploy: check-pushed ## Deploy $(SVC) from $(ENV)/ at the current SHA
	@mkdir -p $(ENV)/$(RENDER)
	@for svc in $(SVC); do \
		sed 's|^\( *ref: \).*|\1$(SHA)|' $(ENV)/$$svc.yaml > $(ENV)/$(RENDER)/$$svc.yaml; \
		echo ">> deploying $(ENV)/$$svc at ref $(SHA)"; \
		$(TFY) deploy --file $(ENV)/$(RENDER)/$$svc.yaml --no-wait; \
	done

check-pushed: ## Fail unless SHA is on a remote branch (TrueFoundry builds from GitHub)
	@if [ -z "$$(git branch -r --contains $(SHA) 2>/dev/null)" ]; then \
		echo "ERROR: commit $(SHA) is not on any remote branch."; \
		echo "Push it first:  git push origin HEAD"; \
		exit 1; \
	fi
