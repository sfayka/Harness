import nextVitals from "eslint-config-next/core-web-vitals";

const config = [
  ...nextVitals,
  {
    ignores: [".harness-local-dashboard-build/**", ".next/**", "node_modules/**"],
  },
];

export default config;
