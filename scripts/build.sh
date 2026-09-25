#!/usr/bin/env bash
source "$(dirname -- "$0")/common.sh"
install -d apps/web/public/docs-assets
cp node_modules/swagger-ui-dist/swagger-ui-bundle.js apps/web/public/docs-assets/
cp node_modules/swagger-ui-dist/swagger-ui.css apps/web/public/docs-assets/
cp node_modules/swagger-ui-dist/favicon-32x32.png apps/web/public/docs-assets/
pnpm build
# Next standalone output does not automatically include public/static assets.
standalone=apps/web/.next/standalone/apps/web
install -d "$standalone/.next/static"
cp -a apps/web/.next/static/. "$standalone/.next/static/"
if [[ -d apps/web/public ]]; then install -d "$standalone/public"; cp -a apps/web/public/. "$standalone/public/"; fi
