// @ts-check
import js from "@eslint/js";
import boundaries from "eslint-plugin-boundaries";
import reactHooks from "eslint-plugin-react-hooks";
import globals from "globals";
import tseslint from "typescript-eslint";

/**
 * Feature-Sliced Design layer rules (Block 2.2 of the frontend spec):
 *   shared    -> nothing
 *   entities  -> shared
 *   features  -> entities, shared
 *   widgets   -> features, entities, shared
 *   pages     -> widgets, features, entities, shared
 *   app       -> everything
 * Violations fail linting — not left to developer discipline.
 */
export default tseslint.config(
  {
    ignores: ["dist/**", "coverage/**", "playwright-report/**", "node_modules/**"],
  },
  js.configs.recommended,
  ...tseslint.configs.strictTypeChecked,
  reactHooks.configs["recommended-latest"],
  {
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: "module",
      globals: { ...globals.browser, ...globals.es2022 },
      parserOptions: {
        projectService: true,
        tsconfigRootDir: import.meta.dirname,
      },
    },
    rules: {
      "@typescript-eslint/no-unused-vars": [
        "error",
        { argsIgnorePattern: "^_", varsIgnorePattern: "^_" },
      ],
      "@typescript-eslint/consistent-type-imports": "error",
      "@typescript-eslint/restrict-template-expressions": [
        "error",
        { allowNumber: true, allowBoolean: true, allowNullish: false },
      ],
      // The spec allows `any` only with an explicit justification comment.
      "@typescript-eslint/no-explicit-any": "error",
    },
  },
  {
    files: ["src/**/*.{ts,tsx}"],
    plugins: { boundaries },
    settings: {
      "boundaries/include": ["src/**/*.{ts,tsx}"],
      "boundaries/elements": [
        { type: "app", pattern: "src/app/**" },
        { type: "pages", pattern: "src/pages/**" },
        { type: "widgets", pattern: "src/widgets/**" },
        { type: "features", pattern: "src/features/**" },
        { type: "entities", pattern: "src/entities/**" },
        { type: "shared", pattern: "src/shared/**" },
      ],
    },
    rules: {
      "boundaries/element-types": [
        "error",
        {
          default: "disallow",
          message: "${file.type} is not allowed to import from ${dependency.type}",
          rules: [
            { from: ["app"], allow: ["pages", "widgets", "features", "entities", "shared"] },
            { from: ["pages"], allow: ["widgets", "features", "entities", "shared"] },
            { from: ["widgets"], allow: ["features", "entities", "shared"] },
            { from: ["features"], allow: ["entities", "shared"] },
            { from: ["entities"], allow: ["shared"] },
            { from: ["shared"], allow: [] },
          ],
        },
      ],
      // Also forbid cross-slice imports inside the same layer (entity A must not
      // import entity B directly; route through the importing page/widget).
      "boundaries/external": "off",
    },
  },
  {
    files: ["src/**/*.test.{ts,tsx}", "src/test/**"],
    languageOptions: {
      globals: globals.vitest,
    },
    rules: {
      "@typescript-eslint/no-non-null-assertion": "off",
    },
  },
);
