# Stormcloud web

The private, invite-only evidence workspace UI. It talks only to the versioned backend REST API.

## Local development

    cp .env.example .env
    npm install
    npm run dev

Vite proxies /v1 to http://localhost:8000 by default. Override the development target with STORMCLOUD_API_PROXY, or set VITE_API_BASE_URL to an absolute API URL for a built deployment.

## Checks

    npm run test
    npm run build

This package is intentionally deployment-neutral. The Vercel project is reserved for a later deployment and is not modified by this repository.
