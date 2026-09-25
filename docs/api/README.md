
Interactive documentation loads locally bundled Swagger assets after the operator build; it does not require a public CDN. Database dependencies commit before the HTTP response is sent (FastAPI function-scoped dependencies).
