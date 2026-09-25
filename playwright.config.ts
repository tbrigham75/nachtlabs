import { defineConfig } from '@playwright/test';
export default defineConfig({
 testDir:'./tests/e2e', workers:1, fullyParallel:false,
 use:{baseURL:process.env.NACHTLABS_E2E_URL, trace:'off', screenshot:'off', video:'off'},
 // No webServer: the operator starts the isolated Linux services explicitly.
});
