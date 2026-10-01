# c:node Shell
COMPOSE = docker compose -f infra/docker-compose.yml

.PHONY: help up down logs ps health seed-reset ui ui-install shell clean

help:
	@echo "up          - build + start the microservice stack"
	@echo "down        - stop the stack"
	@echo "logs        - tail service logs"
	@echo "ps          - service status"
	@echo "health      - curl every /health"
	@echo "seed-reset  - reload the seed graph into graph-core"
	@echo "ui-install  - install shell UI deps (pnpm)"
	@echo "ui          - run the web UI (Vite :3010)"
	@echo "shell       - run the Tauri desktop shell"

up:
	$(COMPOSE) up -d --build

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f --tail=50

ps:
	$(COMPOSE) ps

health:
	@for p in 8080:bff 8010:graph-core 8020:engine 8030:assets 8060:voice 8070:ontology-studio; do \
		port=$${p%%:*}; name=$${p##*:}; \
		printf "  %-14s " $$name; curl -s -m 5 http://localhost:$$port/health || echo "DOWN"; echo; \
	done

seed-reset:
	curl -s -X POST http://localhost:8010/reset-seed | python3 -m json.tool

ui-install:
	cd apps/shell && pnpm install

ui:
	cd apps/shell && pnpm dev

shell:
	cd apps/shell && pnpm tauri dev

clean:
	$(COMPOSE) down -v

# --- Multi-Tenant (config-driven) -------------------------------------------
TENANT ?= cnode
TCOMPOSE = docker compose -f infra/docker-compose.yml -f infra/docker-compose.tenant.yml --env-file .env
CLOUDCOMPOSE = docker compose -f infra/docker-compose.yml -f infra/docker-compose.tenant.yml -f infra/docker-compose.cloud.yml --env-file .env

.PHONY: tenant-new tenant-up tenant-down tenant-logs tenant-ps sandbox sandbox-down cloud-up cloud-down

sandbox:               ## make sandbox  — saubere cNode-Default-Instanz zum Gegenbauen (== TENANT=cnode tenant-up)
	TENANT=cnode $(TCOMPOSE) up -d --build
	@echo "→ cNode-Sandbox up.  Shell: make ui  → http://localhost:3010  ·  API: http://localhost:8080"

sandbox-down:          ## make sandbox-down  — cNode-Sandbox stoppen
	TENANT=cnode $(TCOMPOSE) down

cloud-up:              ## make cloud-up  — cNode Cloud-Profil (Cloud-LLM + API-Key-Auth) lokal starten
	TENANT=cnode $(CLOUDCOMPOSE) up -d --build
	@echo "→ cNode Cloud-Profil up (provider=api, API-Key-Auth aktiv). API: http://localhost:8080"

cloud-down:
	TENANT=cnode $(CLOUDCOMPOSE) down

tenant-new:            ## make tenant-new NAME=<slug>  — neuen lokalen Tenant scaffolden
	@test -n "$(NAME)" || (echo "NAME=<slug> erforderlich" && exit 1)
	./scripts/tenant-new.sh $(NAME)

tenant-up:             ## TENANT=<slug> make tenant-up  — Stack mit Tenant-Overlay starten
	TENANT=$(TENANT) $(TCOMPOSE) up -d
	@echo "→ Services up (Tenant: $(TENANT)).  UI: make ui  → http://localhost:3010"

tenant-down:
	TENANT=$(TENANT) $(TCOMPOSE) down

tenant-logs:
	TENANT=$(TENANT) $(TCOMPOSE) logs -f --tail=50

tenant-ps:
	TENANT=$(TENANT) $(TCOMPOSE) ps

tenant-seed:           ## TENANT=<slug> make tenant-seed  — eigene Seed-Daten in die Tenant-group laden
	@test -n "$(TENANT)" || (echo "TENANT=<slug> erforderlich" && exit 1)
	./scripts/tenant-seed.sh $(TENANT)

tenant-import:         ## TENANT=<slug> URL=<url> make tenant-import  — URL scrapen → in den Tenant-Graph
	@test -n "$(TENANT)" || (echo "TENANT=<slug> erforderlich" && exit 1)
	@test -n "$(URL)" || (echo "URL=<url> erforderlich" && exit 1)
	curl -s -X POST localhost:8020/enrich/url -H 'content-type: application/json' \
	  -d '{"url":"$(URL)","client_id":"$(TENANT)"}' | python3 -m json.tool
