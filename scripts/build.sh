# 1. Generate configs
./scripts/generate.sh



# 2. Run app
docker compose up --build -d
docker compose exec nginx /ssl-setup.sh